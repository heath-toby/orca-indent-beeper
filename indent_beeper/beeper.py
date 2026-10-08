"""The hook: a tone in front of every line Orca reads.

There is exactly one place to put this. ``Script.say_line`` hands the raw line
to ``SpeechPresenter.speak_line`` -- raw being the point, because the leading
whitespace is still on it at that moment and everything downstream is entitled
to strip it. Nothing else overrides ``say_line``, the web script included, so
patching ``speak_line`` covers arrowing by line, Home and End, and anything
else that presents a line, in every application, from one hook.

Orca already has a *spoken* indentation report, which is what sits a couple of
lines further into ``speak_line``. This does not touch it. If it is switched on
in Orca's preferences you get both, which is a reasonable thing to want while
you are learning the ladder; switch it off in Orca and the beep stands alone.
"""

from __future__ import annotations

import logging

from orca import speech_presenter

from .config import Config
from .indent import indentation_units, tone_for_config
from .player import TonePlayer
from .tone import render

_log = logging.getLogger("orca-indent-beeper")

_config: Config | None = None
_player: TonePlayer | None = None

# Rendered tones, keyed on the depth. Cleared whenever a setting that affects
# the sound changes, which _cache_identity detects without this having to know
# which setting moved.
_cache: dict[int, bytes] = {}
_cache_identity: tuple | None = None

# Deepest indent worth remembering a tone for. Past this the tones are being
# generated for a line nobody is reading twice, and rendering one costs well
# under a millisecond.
_CACHE_LIMIT = 512

# (owner, attribute, original) for everything patched, so uninstall can put
# back exactly what was there rather than what it assumes was there.
_patched: list[tuple[object, str, object]] = []


def _patch(owner, attribute, replacement) -> None:
    original = getattr(owner, attribute)
    _patched.append((owner, attribute, original))
    setattr(owner, attribute, replacement)


def _unpatch_all() -> None:
    while _patched:
        owner, attribute, original = _patched.pop()
        try:
            setattr(owner, attribute, original)
        except Exception as error:  # pylint: disable=broad-exception-caught
            _log.warning("IndentBeeper: could not restore %s: %s", attribute, error)


def _speech_volume_factor() -> float:
    """Orca's speech volume as a 0-1 multiplier, or 1.0 if it cannot be read."""
    try:
        from orca import speech_manager
        return min(max(speech_manager.get_manager().get_volume() / 10.0, 0.0), 1.0)
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.debug("IndentBeeper: could not read Orca's volume: %s", error)
        return 1.0


def _apply_volume() -> None:
    if _player is None or _config is None:
        return
    level = _config.volume
    if _config.follow_speech_volume:
        level *= _speech_volume_factor()
    _player.set_volume(level)


def _tone_for(units: int) -> bytes:
    """The PCM for this depth, rendering and remembering it on first use."""
    global _cache_identity
    if _config is None:
        return b""
    if _cache_identity != _config.identity:
        _cache.clear()
        _cache_identity = _config.identity
    cached = _cache.get(units)
    if cached is not None:
        return cached
    frequency, duration = tone_for_config(units, _config)
    pcm = render(frequency, duration, fade_ms=_config.fade_ms)
    if len(_cache) < _CACHE_LIMIT:
        _cache[units] = pcm
    return pcm


def beep_for_line(line: str) -> None:
    """Sound the tone for a line's indentation. Safe to call for any line."""
    if _config is None or not _config.enabled or _player is None:
        return
    if not _player.available:
        return
    units = indentation_units(line, _config.tab_units)
    if units == 0 and not _config.beep_on_no_indent:
        return
    # Re-read the speech volume per beep rather than caching it: Orca's volume
    # keys change it live, and a beep that stayed loud after the voice was
    # turned down would be the first thing anyone complained about.
    _apply_volume()
    _player.play(_tone_for(units))


def install(config: Config) -> None:
    """Start beeping. Must be called from the main thread."""
    global _config, _player
    if _patched:
        return
    _config = config
    _player = TonePlayer()
    if not _player.available:
        _log.warning("IndentBeeper: no audio output; the beep will be silent.")
    _apply_volume()

    original_speak_line = speech_presenter.SpeechPresenter.speak_line

    def _patched_speak_line(self, script, obj, start_offset, end_offset, line):
        # Before the original, so the tone leads the line rather than landing
        # on top of the first word of it.
        try:
            beep_for_line(line)
        except Exception as error:  # pylint: disable=broad-exception-caught
            _log.warning("IndentBeeper: %s", error)
        return original_speak_line(self, script, obj, start_offset, end_offset, line)

    _patch(speech_presenter.SpeechPresenter, "speak_line", _patched_speak_line)
    _log.info("IndentBeeper: installed (enabled=%s)", config.enabled)


def uninstall() -> None:
    """Stop beeping and close the audio stream."""
    global _config, _player, _cache_identity
    _unpatch_all()
    if _player is not None:
        _player.shutdown()
    _player = None
    _config = None
    _cache.clear()
    _cache_identity = None
    _log.info("IndentBeeper: uninstalled.")


def settings_changed() -> None:
    """Re-read settings. Driven off Orca's own change signal."""
    if _config is None:
        return
    _config.reload()
    _apply_volume()
    _log.info("IndentBeeper: settings changed (enabled=%s, %d Hz base, "
              "%d steps/octave, %d octaves, tab=%d)",
              _config.enabled, _config.base_frequency, _config.steps_per_octave,
              _config.octaves, _config.tab_units)


def toggle() -> bool:
    """Flip the beep on or off and say which it now is. Command handler."""
    if _config is None:
        return False
    _config.set_enabled(not _config.enabled)
    message = ("Indentation beep on" if _config.enabled else "Indentation beep off")
    try:
        from orca import presentation_manager
        presentation_manager.get_manager().present_message(message)
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("IndentBeeper: could not announce the toggle: %s", error)
    # A tone straight after the announcement, so turning it on tells you what
    # "no indent" sounds like and you have a reference for the next line.
    if _config.enabled:
        beep_for_line("")
    return True

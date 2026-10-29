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
import os
import time

from orca import speech_presenter

from .config import Config
from .indent import indentation_units, tone_for_config
from .player import TonePlayer
from .tone import render

_log = logging.getLogger("orca-indent-beeper")

# Diagnostics go to a file rather than Orca's log, and outside the package:
# Orca hashes every file in the extension directory, so anything written at
# runtime inside it would invalidate the approval.
#
#     ORCA_INDENT_BEEPER_DEBUG=1 orca --replace &
#
# Off by default and gated on a module-level flag, so an ordinary run does not
# pay for the formatting on every line it reads.
_DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "orca", "indent_beeper",
)
_DEBUG = os.environ.get("ORCA_INDENT_BEEPER_DEBUG", "").lower() in ("1", "true", "yes")
_debug_log = None


def _debug_on() -> bool:
    """True if anything would be written to the debug log.

    Worth asking before building a line that costs more than a format: the
    lag figure below queries the pipeline.
    """
    return bool(_DEBUG or (_config is not None and _config.debug))


def _debug(message: str) -> None:
    """Append a line to the debug log, if one was asked for.

    Checked per call rather than once at import, so the setting can be turned
    on in Orca's preferences and take effect immediately -- which is the only
    way in when Orca is a systemd service and cannot see an exported variable.
    """
    global _debug_log
    if not _DEBUG and not (_config is not None and _config.debug):
        return
    try:
        if _debug_log is None:
            os.makedirs(_DATA_DIR, exist_ok=True)
            _debug_log = open(os.path.join(_DATA_DIR, "debug.log"), "a")
        _debug_log.write(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} "
                         f"{message}\n")
        _debug_log.flush()
    except Exception:  # pylint: disable=broad-exception-caught
        pass

_config: Config | None = None
_player: TonePlayer | None = None

# The depth the last beep decision was made at, or None for "no idea yet".
# This is what makes the tone report a *change* rather than a depth: reading
# down a block at a constant indent is silent, and the line that steps in or
# out of it sounds. None means the next line beeps whatever its depth, which
# is what you want after switching the beep on, after a settings change, and
# on the very first line of a session -- there is nothing to have changed from.
_last_units: int | None = None

# The last line a reading hook decided about, and when. There are two code
# paths for presenting a line (see beep_for_object_line) and for some
# presentations both of them fire, as can several calls within one. A beep per
# call would be a stutter, so an identical line inside this window is taken to
# be the same presentation arriving twice.
_last_presentation: str | None = None
_last_presentation_at: float = 0.0
_PRESENTATION_WINDOW = 0.25

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


def _line_context(obj, start_offset: int, line: str) -> str:
    """What Orca handed us, beside what the object says right now.

    For the LibreOffice Writer report: moving to the next paragraph often
    beeps nothing, and then arrowing up and back down beeps, "as though it's a
    delayed response". Two explanations fit that and they need different fixes,
    so the log has to tell them apart:

    * the line arrives **stale or blank** on first arrival, so its measured
      depth is wrong and the change-gate suppresses a beep that was due; or
    * the line is right and the gate is right, and something else is eating
      the presentation.

    Re-reading the line from the object at the caret distinguishes them. Built
    only when the log is on, because it costs two AT-SPI round trips.
    """
    try:
        from orca.ax_text import AXText
        from orca.ax_object import AXObject
        caret = AXText.get_caret_offset(obj)
        fresh = AXText.get_line_at_offset(obj, max(0, caret))[0]
        role = AXObject.get_role_name(obj)
        same = "same" if fresh == line else "DIFFERENT"
        return (f"role={role} caret={caret} start={start_offset} "
                f"handed={line[:40]!r} fresh={(fresh or '')[:40]!r} {same}")
    except Exception as error:  # pylint: disable=broad-exception-caught
        return f"context unavailable: {type(error).__name__}: {error}"


def beep_for_line(line: str, source: str = "line", force: bool = False) -> None:
    """Sound the tone for a line's indentation. Safe to call for any line.

    By default the tone reports a *change* of depth: a line indented the same
    as the one before it is silent. See ``_last_units``.

    ``force`` sounds the tone whatever the depth and then forgets the depth,
    so the next line beeps too. Only the toggle's confirmation beep wants
    that -- it has to be audible, and it must not leave the next line silent
    by having claimed a depth of its own.
    """
    global _last_units
    if _config is None or _player is None:
        _debug(f"{source}: not running")
        return
    if not _config.enabled:
        _debug(f"{source}: disabled")
        return
    if not _player.available:
        _debug(f"{source}: no player")
        return
    units = indentation_units(line, _config.tab_units)
    if force:
        _last_units = None
    elif _config.beep_on_change_only:
        if not line.strip():
            # A line with nothing on it has no indentation because it has no
            # content, not because the code came back to the margin. Treating
            # it as a change to zero beeps twice for every blank line in a
            # file -- once down to the margin and once back -- and reports a
            # structural change that never happened. So leave the remembered
            # depth alone and say nothing; Orca already says "blank".
            #
            # The test is on the stripped line, and that matters. This used to
            # read "if not line", which is almost never true: Orca hands
            # speak_line the line with its terminator still on it, so a blank
            # line arrives as "\n" and sailed straight past the guard. With
            # trailing whitespace it arrived as "   \n" and sounded a pitch
            # taken from whitespace nobody typed as indentation. 44 of 200
            # beeps in Toby's log were lines with nothing on them, and each one
            # also overwrote the remembered depth, which is what put the rest
            # of the beeps in the wrong places.
            _debug(f"{source}: a line with no content is not a change "
                   f"of indentation ({line!r})")
            return
        if units == _last_units:
            _debug(f"{source}: units={units} unchanged, not beeping "
                   f"line={line[:40]!r}")
            return
        _last_units = units
    else:
        _last_units = units
    # Re-read the speech volume per beep rather than caching it: Orca's volume
    # keys change it live, and a beep that stayed loud after the voice was
    # turned down would be the first thing anyone complained about.
    _apply_volume()
    frequency, duration = tone_for_config(units, _config)
    result = _player.play(_tone_for(units))
    if _debug_on():
        _debug(f"{source}: units={units} {frequency:.1f}Hz {duration}ms "
               f"vol={_player.last_volume:.3f} push={result} "
               f"state={_player.state_name} "
               f"out={getattr(_player, 'device', '?')} "
               f"line={line[:40]!r}")


def _line_navigation_keypress() -> bool:
    """True if the last keypress was one Orca would present a whole line for.

    These are the same reasons ``scripts/default.py`` routes to ``say_line``
    -- line, page and file-boundary navigation -- plus paragraph navigation,
    which a Writer user leans on and which also presents a line. Without this
    gate, hooking the object path would beep for every focused text field and
    every tab into an entry, because the same leaf generates their speech too.
    """
    try:
        from orca import input_event_manager
        manager = input_event_manager.get_manager()
        return bool(manager.last_event_was_line_navigation()
                    or manager.last_event_was_paragraph_navigation()
                    or manager.last_event_was_page_navigation()
                    or manager.last_event_was_file_boundary_navigation())
    except Exception as error:  # pylint: disable=broad-exception-caught
        _debug(f"gate: could not ask about the last keypress: {error}")
        return False


def beep_for_presented_line(line: str, source: str) -> None:
    """Beep for a line being read, dropping the same presentation twice over."""
    global _last_presentation, _last_presentation_at
    now = time.monotonic()
    if line == _last_presentation and now - _last_presentation_at < _PRESENTATION_WINDOW:
        _debug(f"{source}: same line again within "
               f"{int((now - _last_presentation_at) * 1000)}ms, already decided")
        return
    _last_presentation = line
    _last_presentation_at = now
    beep_for_line(line, source=source)


def beep_for_object_line(obj, source: str = "object-line") -> None:
    """Beep for the line of a text object Orca is presenting.

    **Orca has two code paths for presenting a line,** and its own source says
    so, in a TODO above ``SpeechGenerator.generate_line``:

        generate_line duplicates _generate_text_line. speak_line (the sole
        caller of generate_line) should be consolidated with the
        _generate_text_line path used by present_object/generate_speech so
        there is one code path for line presentation.

    ``speak_line`` covers arrowing within a single text object, which is what
    a terminal is. A LibreOffice Writer paragraph is its own accessible, so
    moving between paragraphs presents a different *object* each time and goes
    through ``_generate_text_line`` instead -- where there was no hook, so
    reading a Writer document was entirely silent while a terminal was
    perfect. Toby: *"Not a single beep when reading, but every beep is correct
    when writing."* 158 log lines from that session contained 147 from the
    typing hook and not one from ``say-line``.

    The line is read at the caret rather than taken from the generator, which
    computes its text several ways depending on the object; the leading
    whitespace is what matters here and the line at the caret always has it.
    """
    if _config is None or not _config.enabled:
        return
    if not _line_navigation_keypress():
        return
    try:
        from orca.ax_text import AXText
        caret = AXText.get_caret_offset(obj)
        line = AXText.get_line_at_offset(obj, max(0, caret))[0]
    except Exception as error:  # pylint: disable=broad-exception-caught
        _debug(f"{source}: could not read the line: {type(error).__name__}: {error}")
        return
    if not line:
        _debug(f"{source}: no line at the caret")
        return
    beep_for_presented_line(line, source)


def beep_for_typed_indent(obj, changed_text: str) -> None:
    """Beep while the indentation of the current line is being typed.

    Reading a line and building one are different things, so this is a
    different signal from the one on speak_line. It fires only when the text
    that changed was itself whitespace *and* everything before the caret on
    this line is whitespace -- that is what "in the indentation" means. Typing
    a letter does not beep, and neither does a space in the middle of a
    sentence.

    The pitch is the whitespace *before the caret*, not the whole leading run,
    so it tracks what you have actually typed: hold space down and the tone
    climbs a step per press, backspace it away and it comes back down.
    """
    global _last_units
    if _config is None or not _config.enabled or not _config.beep_while_typing:
        return
    if not changed_text or changed_text.strip(" \t\u00a0"):
        # Not a whitespace edit, so it is not an indentation edit.
        return
    try:
        from orca.ax_text import AXText
        offset = AXText.get_caret_offset(obj)
        line, start = AXText.get_line_at_offset(obj, max(0, offset))[0:2]
    except Exception as error:  # pylint: disable=broad-exception-caught
        _debug(f"typing: could not read the line: {error}")
        return
    if line is None:
        return
    column = max(0, offset - start)
    prefix = line[:column].replace("\u00a0", " ")
    if prefix.strip(" \t"):
        # There is real text before the caret, so the caret is past the
        # indentation and this space belongs to the prose.
        _debug(f"typing: caret is past the indentation, not beeping")
        return
    units = indentation_units(prefix, _config.tab_units)
    if _config.beep_on_change_only and units == _last_units:
        _debug(f"typing: units={units} unchanged, not beeping")
        return
    # Every keystroke in the indentation changes its depth, so typing beeps
    # on all of them either way -- including backspacing the last space away,
    # which is a change to zero and sounds the bottom of the ladder. Unlike a
    # blank line, that zero is real: there was an indent and now there is not.
    _last_units = units
    _apply_volume()
    frequency, duration = tone_for_config(units, _config)
    result = _player.play(_tone_for(units)) if _player is not None else "no-player"
    _debug(f"typing: units={units} {frequency:.1f}Hz {duration}ms push={result} "
           f"prefix={prefix!r}")


def install(config: Config) -> None:
    """Start beeping. Must be called from the main thread."""
    global _config, _player, _last_units, _last_presentation
    if _patched:
        return
    _last_presentation = None
    _config = config
    _last_units = None
    _player = TonePlayer()
    if not _player.available:
        _log.warning("IndentBeeper: no audio output; the beep will be silent.")
    _apply_volume()

    original_speak_line = speech_presenter.SpeechPresenter.speak_line

    def _patched_speak_line(self, script, obj, start_offset, end_offset, line):
        # Before the original, so the tone leads the line rather than landing
        # on top of the first word of it.
        try:
            if _debug_on():
                _debug(f"say-line: {_line_context(obj, start_offset, line)}")
            beep_for_presented_line(line, "say-line")
        except Exception as error:  # pylint: disable=broad-exception-caught
            _log.warning("IndentBeeper: %s", error)
            _debug(f"say-line: ERROR {type(error).__name__}: {error}")
        return original_speak_line(self, script, obj, start_offset, end_offset, line)

    _patch(speech_presenter.SpeechPresenter, "speak_line", _patched_speak_line)

    # Flat review presents its own lines and never goes near say_line, so it
    # needs its own hook or reviewing a file is silent while arrowing through
    # the same file beeps.
    try:
        from orca import flat_review_presenter
        from orca import input_event

        presenter_class = flat_review_presenter.FlatReviewPresenter
        original_line_presentation = presenter_class._line_presentation

        def _patched_line_presentation(self, script, event=None, speech_type=1):
            try:
                # Braille events present no speech here, so they get no beep
                # either: the tone belongs with the spoken line.
                if not isinstance(event, input_event.BrailleEvent):
                    context = self.get_or_create_context(script)
                    line = context.get_current_line_string()
                    if line and line != "\n":
                        beep_for_line(line, source="flat-review")
            except Exception as error:  # pylint: disable=broad-exception-caught
                _debug(f"flat-review: ERROR {type(error).__name__}: {error}")
            return original_line_presentation(self, script, event, speech_type)

        _patch(presenter_class, "_line_presentation", _patched_line_presentation)
        _debug("installed the flat review hook")
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("IndentBeeper: could not patch flat review: %s", error)
        _debug(f"flat review hook FAILED: {error}")

    # The other line-presentation path. Orca's own TODO says there are two and
    # that they should be one; until they are, an extension that beeps for a
    # line has to hook both or it is silent in every application whose lines
    # are separate accessible objects -- LibreOffice Writer among them.
    #
    # Patched on the base class: LibreOffice's generator overrides this method
    # but calls super() in both of its branches, so the base-class patch is
    # still reached. Checked rather than assumed.
    try:
        from orca import speech_generator as _speech_generator

        generator_class = _speech_generator.SpeechGenerator
        original_text_line = generator_class._generate_text_line

        def _patched_text_line(self, obj):
            try:
                beep_for_object_line(obj, source="object-line")
            except Exception as error:  # pylint: disable=broad-exception-caught
                _debug(f"object-line: ERROR {type(error).__name__}: {error}")
            return original_text_line(self, obj)

        _patch(generator_class, "_generate_text_line", _patched_text_line)
        _debug("installed the object-line hook")
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("IndentBeeper: could not patch the object line path: %s", error)
        _debug(f"object-line hook FAILED: {error}")

    # Typing the indentation is a different act from reading it, so it gets
    # its own hooks: the text-changed handlers, which is where Orca learns
    # what was inserted or deleted and where.
    try:
        from orca.scripts import default as default_script

        for attribute in ("_on_text_inserted", "_on_text_deleted"):
            original_handler = getattr(default_script.Script, attribute)

            def _patched_text_change(self, event, _original=original_handler):
                try:
                    changed = event.any_data if isinstance(event.any_data, str) else ""
                    if changed:
                        beep_for_typed_indent(event.source, changed)
                except Exception as error:  # pylint: disable=broad-exception-caught
                    _debug(f"typing: ERROR {type(error).__name__}: {error}")
                return _original(self, event)

            _patch(default_script.Script, attribute, _patched_text_change)
        _debug("installed the typing hooks")
    except Exception as error:  # pylint: disable=broad-exception-caught
        _log.warning("IndentBeeper: could not patch the text-change handlers: %s", error)
        _debug(f"typing hooks FAILED: {error}")

    _log.info("IndentBeeper: installed (enabled=%s)", config.enabled)
    _debug(f"installed: enabled={config.enabled} player={_player.describe()}")


def uninstall() -> None:
    """Stop beeping and close the audio stream."""
    global _config, _player, _cache_identity, _last_units, _last_presentation
    _unpatch_all()
    _last_units = None
    _last_presentation = None
    if _player is not None:
        _player.shutdown()
    _player = None
    _config = None
    _cache.clear()
    _cache_identity = None
    _log.info("IndentBeeper: uninstalled.")


def settings_changed() -> None:
    """Re-read settings. Driven off Orca's own change signal."""
    global _last_units
    if _config is None:
        return
    _config.reload()
    # The remembered depth was measured under the old settings -- a changed
    # tab width means it is not even in the same units -- so forget it and let
    # the next line beep.
    _last_units = None
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
        beep_for_line("", source="toggle", force=True)
    return True

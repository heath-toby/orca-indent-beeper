"""Settings, read from Orca's own per-extension store.

Everything here is a number or a toggle, so Orca's generated preferences pane
is the whole user interface and this add-on has no dialog of its own. That is
the documented dividing line: an add-on earns its own dialog by needing
something a form cannot do -- a preview button, a file chooser, a modal
sub-dialog. This one does not, because the beep is its own preview: change the
pitch and arrow down a line, and you have heard it.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("orca-indent-beeper")

DEFAULT_ENABLED = True

# A3. The whole ladder hangs off this, so moving it moves everything.
DEFAULT_BASE_FREQUENCY = 220
BASE_FREQUENCY_MIN, BASE_FREQUENCY_MAX = 55, 880

# 24 steps to the octave is a quarter tone a space, which is NVDA's. 12 is a
# semitone a space -- louder in pitch terms, but it uses the range up four
# times as fast. 48 is an eighth tone, for finer grades of shallow indent.
DEFAULT_STEPS_PER_OCTAVE = 24
STEPS_PER_OCTAVE_OPTIONS = (12, 24, 48)

# How far the ladder climbs before it starts again. Three octaves from A3 lands
# on A6, and every octave on the way is an A, which is the easiest interval
# there is to recognise without a reference.
DEFAULT_OCTAVES = 3
OCTAVES_MIN, OCTAVES_MAX = 1, 5

# A tab is worth this many spaces. NVDA says four; editors disagree, and the
# ladder should match whatever the file is actually indented with.
DEFAULT_TAB_UNITS = 4
TAB_UNITS_MIN, TAB_UNITS_MAX = 1, 16

DEFAULT_BASE_DURATION_MS = 40
BASE_DURATION_MIN, BASE_DURATION_MAX = 10, 500

# Added each time the ladder starts again. This is the only thing telling one
# run from the next, so it has to be plainly audible.
DEFAULT_RUN_EXTRA_MS = 30
RUN_EXTRA_MIN, RUN_EXTRA_MAX = 0, 200

DEFAULT_MAX_DURATION_MS = 160
MAX_DURATION_MIN, MAX_DURATION_MAX = 40, 1000

# Raised-cosine fade at each end, in milliseconds. 0 reproduces NVDA's
# generator exactly -- including the click it ends on, which is worst at the
# top of the ladder. See tone.py.
DEFAULT_FADE_MS = 4
FADE_MIN, FADE_MAX = 0, 20

DEFAULT_VOLUME = 0.4

# Scale the beep by Orca's own speech volume, so turning Orca down turns the
# beep down with it rather than leaving it shouting over a quiet voice.
DEFAULT_FOLLOW_SPEECH_VOLUME = True

# Beep at the bottom of the ladder for a line with no indentation at all.
# On prose this means a beep per line, which some will want off; but silence
# would otherwise mean both "no indent" and "beeping is off", and a beep you
# can rely on is easier to read than one you cannot.
DEFAULT_BEEP_ON_NO_INDENT = True


class Config:
    """The current settings, re-read on demand."""

    def __init__(self, settings=None) -> None:
        self._settings = settings
        self.enabled = DEFAULT_ENABLED
        self.base_frequency = DEFAULT_BASE_FREQUENCY
        self.steps_per_octave = DEFAULT_STEPS_PER_OCTAVE
        self.octaves = DEFAULT_OCTAVES
        self.tab_units = DEFAULT_TAB_UNITS
        self.base_duration_ms = DEFAULT_BASE_DURATION_MS
        self.run_extra_ms = DEFAULT_RUN_EXTRA_MS
        self.max_duration_ms = DEFAULT_MAX_DURATION_MS
        self.fade_ms = DEFAULT_FADE_MS
        self.volume = DEFAULT_VOLUME
        self.follow_speech_volume = DEFAULT_FOLLOW_SPEECH_VOLUME
        self.beep_on_no_indent = DEFAULT_BEEP_ON_NO_INDENT

    @classmethod
    def load(cls, settings=None) -> "Config":
        config = cls(settings)
        config.reload()
        return config

    def reload(self) -> None:
        """Re-read every value, clamping anything out of range."""
        settings = self._settings
        if settings is None:
            _log.warning("IndentBeeper: no settings store; using defaults.")
            return

        def number(key, default, low, high, cast):
            try:
                value = cast(settings.get(key, default))
            except (TypeError, ValueError):
                _log.warning("IndentBeeper: ignoring unusable %s", key)
                return default
            return min(max(value, low), high)

        self.enabled = bool(settings.get("enabled", DEFAULT_ENABLED))
        self.base_frequency = number(
            "base-frequency", DEFAULT_BASE_FREQUENCY,
            BASE_FREQUENCY_MIN, BASE_FREQUENCY_MAX, int)
        self.steps_per_octave = int(
            settings.get("steps-per-octave", DEFAULT_STEPS_PER_OCTAVE))
        if self.steps_per_octave not in STEPS_PER_OCTAVE_OPTIONS:
            _log.warning("IndentBeeper: ignoring steps-per-octave %r",
                         self.steps_per_octave)
            self.steps_per_octave = DEFAULT_STEPS_PER_OCTAVE
        self.octaves = number("octaves", DEFAULT_OCTAVES,
                              OCTAVES_MIN, OCTAVES_MAX, int)
        self.tab_units = number("tab-units", DEFAULT_TAB_UNITS,
                                TAB_UNITS_MIN, TAB_UNITS_MAX, int)
        self.base_duration_ms = number(
            "base-duration-ms", DEFAULT_BASE_DURATION_MS,
            BASE_DURATION_MIN, BASE_DURATION_MAX, int)
        self.run_extra_ms = number("run-extra-ms", DEFAULT_RUN_EXTRA_MS,
                                   RUN_EXTRA_MIN, RUN_EXTRA_MAX, int)
        self.max_duration_ms = number(
            "max-duration-ms", DEFAULT_MAX_DURATION_MS,
            MAX_DURATION_MIN, MAX_DURATION_MAX, int)
        self.fade_ms = number("fade-ms", DEFAULT_FADE_MS, FADE_MIN, FADE_MAX, int)
        self.volume = number("volume", DEFAULT_VOLUME, 0.0, 1.0, float)
        self.follow_speech_volume = bool(
            settings.get("follow-speech-volume", DEFAULT_FOLLOW_SPEECH_VOLUME))
        self.beep_on_no_indent = bool(
            settings.get("beep-on-no-indent", DEFAULT_BEEP_ON_NO_INDENT))

        # A ceiling below the base duration would make every run shorter than
        # the first, which reads as the ladder going backwards.
        if self.max_duration_ms < self.base_duration_ms:
            self.max_duration_ms = self.base_duration_ms

    def set_enabled(self, enabled: bool) -> None:
        """Flip the toggle and remember it across restarts."""
        self.enabled = bool(enabled)
        if self._settings is not None:
            self._settings.set("enabled", self.enabled)

    @property
    def identity(self) -> tuple:
        """Everything a rendered tone depends on.

        The tone cache is keyed on this, so changing any of it in Orca's
        preferences invalidates the cache without anything having to notice
        which setting moved.
        """
        return (
            self.base_frequency, self.steps_per_octave, self.octaves,
            self.tab_units, self.base_duration_ms, self.run_extra_ms,
            self.max_duration_ms, self.fade_ms,
        )

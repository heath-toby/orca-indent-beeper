"""Indent Beeper for Orca -- the depth of a line's indentation, as a tone.

Orca 51 user extension. Install to $XDG_DATA_HOME/orca/extensions/ and approve
with ``orca --approve-extension indent_beeper``; Orca re-checks the hash of
every file in the package on each start, so re-approve after editing. Nothing
is written inside the package -- the tones are generated into memory -- so
there is no data directory to keep outside it.
"""

__version__ = "1.0.0"

import logging

from orca import gsettings_registry
from orca.extension import Extension, ExtensionPreference

# Import submodules as `from .module import name`, never as
# `from . import module`. The loader imports us as
# orca_user_extension.<name> but never creates `orca_user_extension`
# itself, and `from . import module` goes through __import__ with the
# full dotted path, which insists on importing that absent grandparent.
from .beeper import install as _install
from .beeper import settings_changed as _settings_changed
from .beeper import toggle as _toggle
from .beeper import uninstall as _uninstall
from .config import (
    BASE_DURATION_MAX,
    BASE_DURATION_MIN,
    BASE_FREQUENCY_MAX,
    BASE_FREQUENCY_MIN,
    DEFAULT_BASE_DURATION_MS,
    DEFAULT_BASE_FREQUENCY,
    DEFAULT_BEEP_ON_NO_INDENT,
    DEFAULT_BEEP_WHILE_TYPING,
    DEFAULT_DEBUG,
    DEFAULT_ENABLED,
    DEFAULT_FADE_MS,
    DEFAULT_FOLLOW_SPEECH_VOLUME,
    DEFAULT_MAX_DURATION_MS,
    DEFAULT_OCTAVES,
    DEFAULT_RUN_EXTRA_MS,
    DEFAULT_STEPS_PER_OCTAVE,
    DEFAULT_TAB_UNITS,
    DEFAULT_VOLUME,
    FADE_MAX,
    FADE_MIN,
    MAX_DURATION_MAX,
    MAX_DURATION_MIN,
    OCTAVES_MAX,
    OCTAVES_MIN,
    RUN_EXTRA_MAX,
    RUN_EXTRA_MIN,
    TAB_UNITS_MAX,
    TAB_UNITS_MIN,
    Config,
)

_log = logging.getLogger("orca-indent-beeper")

# Where Orca keeps per-extension settings: schema "extensions", one
# relocatable path per extension namespace, all under the single key
# "settings". The namespace is the extension's source id -- the name of this
# package -- which is the last component of __name__ once the loader has
# imported us as orca_user_extension.<namespace>.
_SETTINGS_SCHEMA = "extensions"
_SETTINGS_KEY = "settings"
_NAMESPACE = gsettings_registry.GSettingsRegistry.sanitize_gsettings_path(
    __name__.rsplit(".", 1)[-1]
)


class IndentBeeper(Extension):
    """Sounds a tone whose pitch rises with a line's indentation."""

    GROUP_LABEL = "Indent Beeper"
    DESCRIPTION = (
        "Plays a short tone before each line, rising a quarter tone for every "
        "space of indentation and four for every tab, so the depth of a line "
        "is heard rather than counted out."
    )
    VERSION = "1.0.0"  # keep in sync with __version__; read by AST, must be a literal
    AUTHOR = "Toby"

    def __init__(self) -> None:
        super().__init__()
        self._config: Config | None = None
        # Kept alive deliberately: the change signal stops firing once the
        # Gio.Settings object is garbage-collected.
        self._watch = None

    def _get_commands(self) -> list:
        """Returns this extension's keyboard commands."""

        from orca import command_manager, keybindings

        keybinding = keybindings.KeyBinding("i", keybindings.ORCA_CTRL_MODIFIER_MASK)
        return [
            command_manager.KeyboardCommand(
                name="indentBeeperToggle",
                function=_toggle,
                group_label=self.GROUP_LABEL,
                description="Toggles the indentation beep",
                desktop_keybinding=keybinding,
                laptop_keybinding=keybinding,
            )
        ]

    def get_preferences(self) -> list:
        """Returns the preferences Orca's generated dialog will show.

        Declared rather than hand-built, which is the right way round here:
        every setting is a number or a toggle, and the beep is its own preview
        -- change a value, arrow down a line, hear it. An add-on only earns a
        dialog of its own by needing something a form cannot do.
        """

        return [
            ExtensionPreference.boolean(
                "enabled", "Beep the indentation of each line", DEFAULT_ENABLED,
            ),
            ExtensionPreference.boolean(
                "beep-on-no-indent",
                "Beep for lines with no indentation",
                DEFAULT_BEEP_ON_NO_INDENT,
            ),
            ExtensionPreference.boolean(
                "beep-while-typing",
                "Beep while typing the indentation of a line",
                DEFAULT_BEEP_WHILE_TYPING,
            ),
            ExtensionPreference.integer(
                "tab-units", "Spaces a tab counts as", DEFAULT_TAB_UNITS,
                TAB_UNITS_MIN, TAB_UNITS_MAX,
            ),
            ExtensionPreference.integer(
                "base-frequency", "Pitch for no indentation, in Hz",
                DEFAULT_BASE_FREQUENCY, BASE_FREQUENCY_MIN, BASE_FREQUENCY_MAX,
            ),
            ExtensionPreference.enum(
                "steps-per-octave", "Pitch steps per octave",
                (
                    (12, "12 - a semitone per space"),
                    (24, "24 - a quarter tone per space"),
                    (48, "48 - an eighth tone per space"),
                ),
                DEFAULT_STEPS_PER_OCTAVE,
            ),
            ExtensionPreference.integer(
                "octaves", "Octaves to climb before starting again",
                DEFAULT_OCTAVES, OCTAVES_MIN, OCTAVES_MAX,
            ),
            ExtensionPreference.integer(
                "base-duration-ms", "Tone length in milliseconds",
                DEFAULT_BASE_DURATION_MS, BASE_DURATION_MIN, BASE_DURATION_MAX,
            ),
            ExtensionPreference.integer(
                "run-extra-ms", "Milliseconds added each time the pitch starts again",
                DEFAULT_RUN_EXTRA_MS, RUN_EXTRA_MIN, RUN_EXTRA_MAX,
            ),
            ExtensionPreference.integer(
                "max-duration-ms", "Longest tone in milliseconds",
                DEFAULT_MAX_DURATION_MS, MAX_DURATION_MIN, MAX_DURATION_MAX,
            ),
            ExtensionPreference.floating(
                "volume", "Beep volume", DEFAULT_VOLUME, 0.0, 1.0,
            ),
            ExtensionPreference.boolean(
                "follow-speech-volume",
                "Scale the beep with Orca's speech volume",
                DEFAULT_FOLLOW_SPEECH_VOLUME,
            ),
            ExtensionPreference.integer(
                "fade-ms", "Fade at each end of the tone, in milliseconds",
                DEFAULT_FADE_MS, FADE_MIN, FADE_MAX,
            ),
            ExtensionPreference.boolean(
                "debug", "Log diagnostics to indent_beeper/debug.log", DEFAULT_DEBUG,
            ),
        ]

    # --- Lifecycle ------------------------------------------------------

    def on_ready(self) -> None:
        """Starts beeping."""

        self._start()

    def on_enabled(self) -> None:
        """Starts beeping after a reload."""

        self._start()

    def on_disabled(self) -> None:
        """Stops beeping, restores Orca's speak_line and closes the stream."""

        self._stop()

    def on_shutdown(self) -> None:
        """Deliberately does nothing.

        Orca runs shutdown hooks in a daemon thread with a timeout, but tearing
        this extension down means a GStreamer state change and un-monkey-
        patching, both of which are main-thread work. Doing it off-thread risks
        a warning, an assertion or a hung exit -- and buys nothing, because the
        process is exiting anyway. on_disabled, which Orca does call on the
        main thread, still does the real teardown.
        """

    def _start(self) -> None:
        if self._config is not None:
            return
        self._config = Config.load(self.settings)
        self._watch_settings()
        _install(self._config)

    def _stop(self) -> None:
        _uninstall()
        self._watch = None
        self._config = None

    # --- Reacting to settings changes -----------------------------------

    def _watch_settings(self) -> None:
        """Re-read settings whenever the store changes.

        Orca's generated preferences dialog writes the store directly and does
        not call back into the extension, so without this a change made there
        would not take effect until the next reload. It is also how the toggle
        keybinding and the dialog stay in step with each other.
        """
        if self._watch is not None:
            return
        try:
            registry = gsettings_registry.get_registry()
            gs = registry.get_settings(
                _SETTINGS_SCHEMA,
                registry.get_active_profile(),
                f"extensions/{_NAMESPACE}",
            )
            if gs is None:
                _log.warning("IndentBeeper: no settings object to watch; "
                             "changes need a reload.")
                return
            gs.connect(f"changed::{_SETTINGS_KEY}", self._on_settings_key_changed)
            self._watch = gs
        except Exception as error:  # pylint: disable=broad-exception-caught
            _log.warning("IndentBeeper: could not watch settings (%s); "
                         "changes need a reload.", error)

    def _on_settings_key_changed(self, _settings, _key) -> None:
        _settings_changed()

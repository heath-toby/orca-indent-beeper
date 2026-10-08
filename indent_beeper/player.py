"""One audio stream, open for the session, fed a tone at a time.

A beep on every line is a beep on every press of Down, held down. Opening the
audio device per beep is out of the question at that rate: it costs tens of
milliseconds, it can drop the beep entirely under key repeat, and on PipeWire
it churns a stream node per press.

So the pipeline is built once and left in PLAYING, and each beep is a buffer
pushed into an appsrc. Nothing is written to disk and nothing is reopened. The
sink runs with sync disabled, which is what makes a push play straight away
rather than being scheduled against the pipeline clock and then dropped for
arriving late -- a beep is wanted now or not at all.

    appsrc ! audioconvert ! volume ! autoaudiosink
"""

from __future__ import annotations

import logging

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

from .tone import SAMPLE_RATE

_log = logging.getLogger("orca-indent-beeper")

_CAPS = (
    "audio/x-raw,format=S16LE,"
    f"rate={SAMPLE_RATE},channels=2,layout=interleaved"
)

# Frames of silence pushed once at startup, purely to complete the pipeline's
# transition to PLAYING. Five milliseconds: enough to preroll, far too short
# to notice.
_PRIME_FRAMES = SAMPLE_RATE // 200

_gst_initialised = False


def _ensure_gst() -> None:
    global _gst_initialised
    if not _gst_initialised:
        Gst.init(None)
        _gst_initialised = True


class TonePlayer:
    """Plays short PCM buffers down one long-lived stream."""

    def __init__(self) -> None:
        _ensure_gst()
        self._pipeline: Gst.Pipeline | None = None
        self._source: Gst.Element | None = None
        self._volume: Gst.Element | None = None
        self._sink_name = "?"
        self._sync = None
        self.last_volume = 0.0
        self._build()

    def _build(self) -> None:
        try:
            self._pipeline = Gst.parse_launch(
                f"appsrc name=src caps={_CAPS} "
                "! audioconvert ! volume name=vol ! autoaudiosink name=sink"
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            _log.error("IndentBeeper: could not build the pipeline: %s", error)
            self._pipeline = None
            return

        self._source = self._pipeline.get_by_name("src")
        self._volume = self._pipeline.get_by_name("vol")
        sink = self._pipeline.get_by_name("sink")
        if self._source is None or self._volume is None or sink is None:
            _log.error("IndentBeeper: the pipeline is missing expected elements")
            self._pipeline = None
            return

        self._source.set_property("format", Gst.Format.TIME)
        self._source.set_property("is-live", True)
        # Let appsrc stamp each buffer as it arrives, so the caller never has
        # to track a running timestamp across beeps that are seconds apart.
        self._source.set_property("do-timestamp", True)
        # Never block the caller: this is reached from Orca's main loop, and a
        # full queue must drop a beep rather than freeze the screen reader.
        self._source.set_property("block", False)
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        bus.connect("message::warning", self._on_warning)

        # READY before PLAYING, and before touching sync: autoaudiosink picks
        # its real sink on the way to READY, so until then the bin is empty and
        # there is nothing to set sync on. Doing it at build time looked right
        # and silently left sync enabled.
        if self._pipeline.set_state(Gst.State.READY) == Gst.StateChangeReturn.FAILURE:
            _log.error("IndentBeeper: the pipeline would not get to READY")
            self._pipeline = None
            return
        self._sink_name, self._sync = _disable_sync(sink)

        result = self._pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            _log.error("IndentBeeper: the pipeline would not start")
            self._pipeline = None
            return
        # A live source goes to PLAYING asynchronously, and measurably it does
        # not get there on a timeout alone: it waits for a buffer. So the first
        # real beep was being pushed into a pipeline still in PAUSED, and lost.
        # Prime it with a few milliseconds of silence, which completes the
        # transition without being heard, and then the first tone lands in a
        # pipeline that is already playing.
        self._source.emit(
            "push-buffer",
            Gst.Buffer.new_wrapped(bytes(_PRIME_FRAMES * 4)),
        )
        self._pipeline.get_state(250 * Gst.MSECOND)
        _log.info("IndentBeeper: pipeline start returned %s, now %s",
                  result.value_nick, self.state_name)
        if self.state_name != "playing":
            _log.warning("IndentBeeper: pipeline is %s after priming; play() "
                         "will restart it per beep", self.state_name)

    def _on_error(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        error, info = message.parse_error()
        _log.error("IndentBeeper: %s (%s)", error, info)

    def _on_warning(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        warning, info = message.parse_warning()
        _log.debug("IndentBeeper: %s (%s)", warning, info)

    @property
    def available(self) -> bool:
        """True if a beep would actually be heard."""
        return self._pipeline is not None and self._source is not None

    @property
    def state_name(self) -> str:
        """The pipeline's current state, for the log."""
        if self._pipeline is None:
            return "none"
        return self._pipeline.get_state(0)[1].value_nick

    def describe(self) -> str:
        """What this player actually ended up being, for the log."""
        return (f"sink={self._sink_name} sync={self._sync} "
                f"state={self.state_name} rate={SAMPLE_RATE}")

    def set_volume(self, volume: float) -> None:
        """Set the output level, 0.0 to 1.0."""
        level = min(max(volume, 0.0), 1.0)
        self.last_volume = level
        if self._volume is not None:
            self._volume.set_property("volume", level)

    def play(self, pcm: bytes) -> str:
        """Push one tone. Returns immediately; the tone sounds on its own.

        Returns what happened, as a short string for the log.
        """
        if self._source is None or self._pipeline is None:
            return "no-source"
        # A stream left idle can be taken out of PLAYING underneath us -- the
        # session manager may suspend it, and a state change anywhere in the
        # pipeline can leave it PAUSED. Pushing into that goes nowhere, so put
        # it back first rather than losing the beep.
        state = self._pipeline.get_state(0)[1]
        if state != Gst.State.PLAYING:
            self._pipeline.set_state(Gst.State.PLAYING)
            _log.debug("IndentBeeper: pipeline was %s; restarted it", state.value_nick)
        buffer = Gst.Buffer.new_wrapped(pcm)
        result = self._source.emit("push-buffer", buffer)
        if result != Gst.FlowReturn.OK:
            _log.debug("IndentBeeper: push returned %s", result)
        return (result.value_nick if state == Gst.State.PLAYING
                else f"{result.value_nick} (was {state.value_nick})")

    def shutdown(self) -> None:
        """Close the stream. Called when the extension is disabled."""
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
        self._pipeline = None
        self._source = None
        self._volume = None


def _disable_sync(element: Gst.Element) -> tuple[str, object]:
    """Turn clock sync off on a sink, descending into a bin to find it.

    Returns (name, sync) for what it reached, so the caller can log whether it
    actually got there. A sink that still has sync enabled drops a buffer for
    arriving late, which for a beep means silence.
    """
    if isinstance(element, Gst.Bin):
        iterator = element.iterate_sinks()
        while True:
            result, child = iterator.next()
            if result != Gst.IteratorResult.OK:
                break
            return _disable_sync(child)
        return (element.get_name(), "no-child-sink")
    try:
        element.set_property("sync", False)
        return (element.get_name(), element.get_property("sync"))
    except Exception as error:  # pylint: disable=broad-exception-caught
        return (element.get_name(), f"unsettable ({error})")

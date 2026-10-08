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
        _disable_sync(sink)

        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            _log.error("IndentBeeper: the pipeline would not start")
            self._pipeline = None

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

    def set_volume(self, volume: float) -> None:
        """Set the output level, 0.0 to 1.0."""
        if self._volume is not None:
            self._volume.set_property("volume", min(max(volume, 0.0), 1.0))

    def play(self, pcm: bytes) -> None:
        """Push one tone. Returns immediately; the tone sounds on its own."""
        if self._source is None:
            return
        buffer = Gst.Buffer.new_wrapped(pcm)
        result = self._source.emit("push-buffer", buffer)
        if result != Gst.FlowReturn.OK:
            _log.debug("IndentBeeper: push returned %s", result)

    def shutdown(self) -> None:
        """Close the stream. Called when the extension is disabled."""
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
        self._pipeline = None
        self._source = None
        self._volume = None


def _disable_sync(element: Gst.Element) -> bool:
    """Turn clock sync off on a sink, descending into a bin to find it.

    Returns True if it reached something. A sink that still has sync enabled
    drops a buffer for arriving late, which for a beep means silence.
    """
    if isinstance(element, Gst.Bin):
        found = False
        iterator = element.iterate_sinks()
        while True:
            result, child = iterator.next()
            if result != Gst.IteratorResult.OK:
                break
            found = _disable_sync(child) or found
        return found
    try:
        element.set_property("sync", False)
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        return False

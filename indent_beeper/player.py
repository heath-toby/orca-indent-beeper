"""One reusable pipeline, driven PLAYING -> NULL for every tone.

    appsrc ! audioconvert ! volume ! autoaudiosink

**The device is released between tones, and that is the whole point of this
file.** Three add-ons on this machine play short sounds often, and which of
them survives a Bluetooth output is decided by exactly one thing:

1. ``audio_themes`` returns its pipeline to **NULL** when each sound ends, so
   the device is closed between sounds. It plays as many sounds as you like on
   A2DP and never cuts off.
2. ``capitalbeep`` prerolls to **PAUSED** and parks there between beeps -- its
   own comment says "so that repeated beeps only need a seek, not a device
   reopen" -- which holds the device open. Its tone vanishes if you hear it
   often enough.
3. This add-on used to hold one stream in **PLAYING** for the session. Its tone
   got shorter and shorter over a run of beeps and then disappeared.

Wired output is fine in all three cases. A2DP is not: its latency is large and
variable, and a stream held open across many short sounds drifts from the
transport until what we hand over lands behind the play point and is discarded
-- progressively, which is why the tone shrinks before it goes. Closing the
device after each tone means nothing is carried from one beep to the next.

Two consequences worth stating plainly:

- A tone costs a device open, measured at 36-47 ms and paid on Orca's main
  loop. That cost is why the first version of this file kept one stream open.
  ``audio_themes`` pays it on every focus change and is the better precedent.
- A tone carries *stream* time, not wall-clock time. The old pipeline was a
  live source -- ``is-live`` with ``do-timestamp`` -- so every buffer named a
  moment on the clock that the sink had to hit, and getting that wrong on a
  drifting device is what cost us the tone. A tone is now a clip stamped
  ``pts=0`` with its own duration, exactly as a file source would deliver it.

  **Both halves of that are load-bearing.** Dropping the wall clock but
  leaving the buffer unstamped altogether made the beep vanish outright:
  with no duration the sink posted EOS before the tone could play -- measured
  at 26-30 ms for a 61 ms tone -- and the EOS handler below then closed the
  device on top of it. Stamped, EOS comes at 94-104 ms, which is the tone plus
  the sink's own latency. If a change here ever makes the beep silent, measure
  the interval from play() to EOS first; it is the whole story in one number.
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

# The most the volume element will be asked for. See set_volume.
MAX_GAIN = 2.0

_gst_initialised = False


def _ensure_gst() -> None:
    global _gst_initialised
    if not _gst_initialised:
        Gst.init(None)
        _gst_initialised = True


class TonePlayer:
    """Plays one short PCM buffer at a time, closing the device after each."""

    def __init__(self) -> None:
        _ensure_gst()
        self._pipeline: Gst.Pipeline | None = None
        self._source: Gst.Element | None = None
        self._volume: Gst.Element | None = None
        self._sink_element: Gst.Element | None = None
        self._sink_name = "?"
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
        # Deliberately NOT a live source, and deliberately not timestamped:
        # see the module docstring. Each tone is a clip, not a moment in a
        # stream.
        self._source.set_property("is-live", False)
        self._source.set_property("do-timestamp", False)
        self._source.set_property("block", False)

        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_error)
        bus.connect("message::warning", self._on_warning)

        self._sink_element, self._sink_name = _descend_to_sink(sink)

    def _on_eos(self, _bus: Gst.Bus, _message: Gst.Message) -> None:
        """The tone finished: close the device.

        This is the line that matters. A message can still be in flight after
        shutdown() has dropped the pipeline, so never assume it is there.
        """
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)

    def _on_error(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        error, info = message.parse_error()
        _log.error("IndentBeeper: %s (%s)", error, info)
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)

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

    @property
    def device(self) -> str:
        """The output the tone went to, for the log.

        Read from ``current-device`` rather than ``device``: the writable one
        is only what was asked for, which is nothing. It is empty between
        tones now that the device is closed after each one, so the log shows
        it for the tone that is sounding.
        """
        if self._sink_element is None:
            return "?"
        try:
            return self._sink_element.get_property("current-device") or "closed"
        except Exception:  # pylint: disable=broad-exception-caught
            return "?"

    def describe(self) -> str:
        """What this player actually ended up being, for the log."""
        return (f"sink={self._sink_name} state={self.state_name} "
                f"rate={SAMPLE_RATE} lifecycle=playing-then-null")

    def set_volume(self, volume: float) -> None:
        """Set the output level.

        Above 1.0 is allowed and is where the default sits. The generator
        peaks at 0.43 of full scale, so a gain of 2 still leaves half the
        range unused -- the ceiling is here to stop a bad setting asking for
        something absurd, not to keep the signal clean.
        """
        level = min(max(volume, 0.0), MAX_GAIN)
        self.last_volume = level
        if self._volume is not None:
            self._volume.set_property("volume", level)

    def play(self, pcm: bytes) -> str:
        """Play one tone, from the top, closing the device when it ends.

        A tone still sounding is cut short in favour of the new one, which is
        what ``audio_themes`` does: at key-repeat speed the tone you want is
        the one for the line you are on.

        Returns what happened, as a short string for the log.
        """
        if self._source is None or self._pipeline is None:
            return "no-source"
        # Back to NULL first: it both interrupts anything still sounding and
        # guarantees appsrc a fresh segment, so the tone starts at zero.
        self._pipeline.set_state(Gst.State.NULL)
        result = self._pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            _log.debug("IndentBeeper: the pipeline would not start")
            return "no-start"
        flow = self._source.emit("push-buffer", _as_clip(pcm))
        if flow != Gst.FlowReturn.OK:
            _log.debug("IndentBeeper: push returned %s", flow)
            return flow.value_nick
        # End the clip, so the sink drains it and the bus tells us to close.
        self._source.emit("end-of-stream")
        return "ok"

    def shutdown(self) -> None:
        """Close the stream. Called when the extension is disabled."""
        pipeline, self._pipeline = self._pipeline, None
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
            bus = pipeline.get_bus()
            if bus is not None:
                # Otherwise the watch keeps a GSource -- and this object --
                # alive for the rest of the session.
                bus.remove_signal_watch()
        self._source = None
        self._volume = None
        self._sink_element = None


def _as_clip(pcm: bytes) -> Gst.Buffer:
    """Wrap PCM as a clip that starts at zero and knows how long it is.

    Without the duration the sink has no idea how much time the buffer
    occupies, drains nothing, and posts EOS immediately -- which the EOS
    handler turns into a closed device and a beep nobody hears.
    """
    buffer = Gst.Buffer.new_wrapped(pcm)
    buffer.pts = 0
    buffer.dts = 0
    frames = len(pcm) // 4            # stereo, 16-bit
    buffer.duration = frames * Gst.SECOND // SAMPLE_RATE
    return buffer


def _descend_to_sink(element: Gst.Element) -> tuple[Gst.Element | None, str]:
    """Find the real sink inside autoaudiosink's bin.

    Nothing is configured on it any more. ``buffer-time`` and ``latency-time``
    used to be forced to 100 ms and 10 ms here, on the reasoning that the
    defaults are sized for music; measured on an A2DP sink that halved its
    ring buffer, and neither setting survives a pipeline that returns to NULL
    between tones anyway. ``audio_themes`` sets neither and is the add-on that
    works.

    Returns (element, name), so a failure to descend shows up in the log.
    """
    if isinstance(element, Gst.Bin):
        iterator = element.iterate_sinks()
        result, child = iterator.next()
        if result != Gst.IteratorResult.OK:
            return (None, element.get_name())
        return _descend_to_sink(child)
    return (element, element.get_name())

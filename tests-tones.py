"""Every claim about the beep, checked in one run.

Run against the installed extension, after ./install.sh:

    python3 tests-tones.py

Three things are being asserted. That the waveform is NVDA's, sample for
sample, when the fade is off -- that is what "NVDA's beep style" has to mean to
be worth saying. That the ladder climbs and wraps as specified. And that the
tone comes out of the far end of a real GStreamer chain at the pitch and length
asked for, rather than merely being generated correctly in memory.
"""
import math
import os
import struct
import time
import sys
import wave

import orca.extension_loader  # noqa: F401
sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))

import gi  # noqa: E402
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

from indent_beeper import config as cfg  # noqa: E402
from indent_beeper import indent, tone  # noqa: E402
from indent_beeper.player import _CAPS  # noqa: E402

rows, fails = [], 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    rows.append((name, want, got, "ok" if ok else "FAIL"))


def close(name, got, want, tol):
    global fails
    ok = abs(got - want) <= tol
    if not ok:
        fails += 1
    rows.append((name, f"{want:.3f}", f"{got:.3f}", "ok" if ok else "FAIL"))


# --- the waveform is NVDA's ------------------------------------------------
# NVDA's generator, reimplemented from nvdaHelper/local/beeps.cpp purely to
# compare against. If this ever stops matching, one of the two moved.
def nvda_generate(hz, length_ms, left=50, right=50):
    sample_rate, amplitude = 44100, 14000
    per_cycle = int(sample_rate / hz)
    total = int((length_ms / 1000.0) / (1.0 / sample_rate))
    total += per_cycle - (total % per_cycle)
    lpan, rpan = (left / 100.0) * amplitude, (right / 100.0) * amplitude
    sin_freq = (2.0 * math.pi) / (sample_rate / hz)
    return total, [
        (
            int(min(max(math.sin((n % sample_rate) * sin_freq) * 2.0, -1.0), 1.0) * lpan),
            int(min(max(math.sin((n % sample_rate) * sin_freq) * 2.0, -1.0), 1.0) * rpan),
        )
        for n in range(total)
    ]


# The waveform is NVDA's sample for sample. The *length* deliberately is not:
# NVDA sizes the tone with a truncated samples-per-cycle while advancing the
# phase at the exact frequency, so its tones stop mid-wave. Compare the shape
# over the length they share, and assert the lengths differ on purpose.
worst = 0
longer = 0
for hz in (220.0, 226.45, 440.0, 880.0, 1760.0):
    want_n, want = nvda_generate(hz, 40, 100, 100)
    got = list(struct.iter_unpack("<hh", tone.render(hz, 40, fade_ms=0)))
    shared = min(len(got), want_n)
    worst = max(worst, max(abs(a[0] - b[0]) for a, b in zip(got[:shared], want[:shared])))
    if len(got) > want_n:
        longer += 1
check("the waveform is NVDA's, sample for sample", worst, 0)
check("every tone runs a little past NVDA's, to reach the zero crossing",
      longer, 5)

# The clipping is the timbre: a plain sine would never sit at full scale. With
# a gain of 2 the wave is flat wherever |sin| >= 1/2, which is 240 degrees of
# every 360 -- two thirds. Derived rather than measured, so the row says what
# the number means and would catch a change in CLIP_GAIN rather than tracking
# it.
clipped_fraction = 1.0 - (2.0 / math.pi) * math.asin(1.0 / tone.CLIP_GAIN)
flat = sum(1 for s, _ in struct.iter_unpack("<hh", tone.render(440.0, 40, fade_ms=0))
           if abs(s) >= tone.AMPLITUDE - 1)
total = len(tone.render(440.0, 40, fade_ms=0)) // 4
close("two thirds of every cycle is clipped flat", flat / total,
      clipped_fraction, 0.01)
# ...and the fade takes a little of that away at each end, which is the only
# difference it makes to the body of the tone.
flat_faded = sum(1 for s, _ in struct.iter_unpack("<hh", tone.render(440.0, 40, fade_ms=4))
                 if abs(s) >= tone.AMPLITUDE - 1)
check("a fade, if asked for, only trims the ends", flat_faded < flat, True)

# Where the tone stops, with no fade to hide it. This is the whole reason the
# length calculation changed: a clipped wave sits at full scale two thirds of
# the time, so stopping at the wrong moment is a vertical edge.
def last_sample(hz, ms, **kwargs):
    raw = struct.iter_unpack("<hh", tone.render(hz, ms, **kwargs))
    return abs(list(raw)[-1][0]) / tone.AMPLITUDE


endings = [last_sample(*indent.tone_for_units(u), fade_ms=0) for u in range(73)]

# An integer number of samples cannot land exactly on the crossing, and the
# residue is bounded by half a sample of phase -- which is nothing at 220 Hz
# (200 samples per cycle) and a quarter of full scale at 1760 Hz (25 samples
# per cycle). Derived rather than measured, so the row says why the number is
# what it is.
def half_sample_bound(hz):
    return min(1.0, tone.CLIP_GAIN * math.sin(math.pi * hz / tone.SAMPLE_RATE))


worst_allowed = [half_sample_bound(indent.tone_for_units(u)[0]) for u in range(73)]
check("no rung ends further from zero than half a sample of phase allows",
      all(e <= b + 1e-9 for e, b in zip(endings, worst_allowed)), True)
check("so the worst ending on the ladder is a quarter of full scale",
      round(max(endings), 2), 0.23)
check("and three quarters of the ladder ends within a twentieth of zero",
      sum(1 for e in endings if e <= 0.05), 50)


# What it used to do, kept as the reason the row above exists: sizing the tone
# with NVDA's truncated samples-per-cycle leaves most of the ladder stopping on
# an edge.
def truncated_count(hz, ms):
    per_cycle = tone.samples_per_cycle(hz)
    total = int(tone.SAMPLE_RATE * ms / 1000)
    return total + per_cycle - (total % per_cycle)


def ending_for(count, hz):
    step = 2.0 * math.pi * hz / tone.SAMPLE_RATE
    return abs(min(max(math.sin((count - 1) * step) * tone.CLIP_GAIN, -1.0), 1.0))


was_bad = sum(1 for u in range(73)
              if ending_for(truncated_count(*indent.tone_for_units(u)),
                            indent.tone_for_units(u)[0]) > 0.5)
check("the old length calculation stopped above half scale on most rungs",
      was_bad, 60)

# The fade is still there for anyone who wants it, and still does what it did.
faded = list(struct.iter_unpack("<hh", tone.render(1760.0, 40, fade_ms=4)))
check("asking for a fade still ends the tone at exactly zero", faded[-1][0], 0)
check("and it still reaches full amplitude",
      max(abs(s) for s, _ in faded), tone.AMPLITUDE)
check("no fade is the default now", tone.DEFAULT_FADE_MS, 0.0)

# --- counting the indentation ---------------------------------------------
check("a space is one rung", indent.indentation_units(" x"), 1)
check("a tab is four", indent.indentation_units("\tx"), 4)
check("a tab is four spaces' worth",
      indent.indentation_units("\tx"), indent.indentation_units("    x"))
check("a configured tab width is honoured",
      indent.indentation_units("\tx", tab_units=8), 8)
check("a non-breaking space counts as a space",
      indent.indentation_units("  x"), 2)
check("only leading whitespace counts", indent.indentation_units("  a    b"), 2)
check("mixed tabs and spaces add up", indent.indentation_units("\t  \tx"), 10)
check("an all-whitespace line counts all of it",
      indent.indentation_units("      "), 6)
check("an empty line is no indent", indent.indentation_units(""), 0)
check("an unindented line is no indent", indent.indentation_units("x  y"), 0)

# --- the ladder -----------------------------------------------------------
close("no indent is the base A", indent.tone_for_units(0)[0], 220.0, 0.01)
close("one space is a quarter tone up",
      indent.tone_for_units(1)[0], 220.0 * 2 ** (1 / 24), 0.01)
close("six tabs is the octave", indent.tone_for_units(24)[0], 440.0, 0.01)
close("twelve tabs is two octaves", indent.tone_for_units(48)[0], 880.0, 0.01)
close("eighteen tabs is the top, A6", indent.tone_for_units(72)[0], 1760.0, 0.01)
check("the run is 73 rungs, both end As included", indent.steps_per_run(), 73)
close("the next space starts again at the bottom",
      indent.tone_for_units(73)[0], 220.0, 0.01)
check("...and holds the tone longer",
      indent.tone_for_units(73)[1] > indent.tone_for_units(0)[1], True)
check("each further run is longer still",
      indent.tone_for_units(146)[1] > indent.tone_for_units(73)[1], True)
check("the growth stops somewhere",
      indent.tone_for_units(100000)[1], cfg.DEFAULT_MAX_DURATION_MS)
check("nothing is ever spoken: a depth always yields a tone",
      all(indent.tone_for_units(u)[0] > 0 for u in range(0, 500)), True)

# A pitch alone is ambiguous by design; the duration is what disambiguates.
same_pitch = [u for u in range(0, 300) if abs(indent.tone_for_units(u)[0] - 220.0) < 0.01]
check("the base pitch recurs once per run", same_pitch, [0, 73, 146, 219, 292])
check("...but each recurrence has its own length",
      len({indent.tone_for_units(u)[1] for u in same_pitch}), len(same_pitch))

# --- settings drive it ----------------------------------------------------
class Settings:
    def __init__(self, **values): self._v = values
    def get(self, key, default=None): return self._v.get(key, default)
    def set(self, key, value): self._v[key] = value

c = cfg.Config.load(Settings())
close("a Config gives the default ladder", indent.tone_for_config(0, c)[0], 220.0, 0.01)
c = cfg.Config.load(Settings(**{"steps-per-octave": 12}))
close("a semitone per space doubles the climb rate",
      indent.tone_for_config(12, c)[0], 440.0, 0.01)
c = cfg.Config.load(Settings(**{"base-frequency": 110}))
close("the base pitch moves the whole ladder",
      indent.tone_for_config(24, c)[0], 220.0, 0.01)
c = cfg.Config.load(Settings(**{"octaves": 1}))
check("fewer octaves means an earlier wrap", indent.steps_per_run(24, 1), 25)
c = cfg.Config.load(Settings(**{"base-frequency": 99999, "tab-units": 999,
                                "steps-per-octave": 7, "volume": 5.0}))
check("an out-of-range pitch is clamped", c.base_frequency, cfg.BASE_FREQUENCY_MAX)
check("an out-of-range tab width is clamped", c.tab_units, cfg.TAB_UNITS_MAX)
check("an unknown step count falls back", c.steps_per_octave,
      cfg.DEFAULT_STEPS_PER_OCTAVE)
check("an out-of-range volume is clamped", c.volume, cfg.VOLUME_MAX)
check("the default is the level of the Mac version Toby wrote",
      round(tone.AMPLITUDE / 32767 * cfg.DEFAULT_VOLUME * 0.46, 2), 0.22)
check("and nothing in range can clip",
      tone.AMPLITUDE / 32767 * cfg.VOLUME_MAX < 1.0, True)
c = cfg.Config.load(Settings(**{"base-duration-ms": 200, "max-duration-ms": 50}))
check("a ceiling below the base is raised to it", c.max_duration_ms, 200)
c = cfg.Config.load(Settings())
before = c.identity
c.reload()
check("the cache identity is stable across a reload", c.identity, before)
c = cfg.Config.load(Settings(**{"fade-ms": 9}))
check("the cache identity changes with a setting", c.identity != before, True)

# --- out of the far end of a real pipeline --------------------------------
# The same appsrc chain the add-on plays through, ending in a file so the
# result can be measured instead of listened for.
Gst.init(None)
out = os.path.join(os.environ.get("TMPDIR", "/tmp"), "indent-beeper-chain.wav")
pipeline = Gst.parse_launch(
    f"appsrc name=src caps={_CAPS} ! audioconvert ! volume name=vol "
    f"! wavenc ! filesink location={out}")
src = pipeline.get_by_name("src")
src.set_property("format", Gst.Format.TIME)
src.set_property("do-timestamp", True)
pipeline.get_by_name("vol").set_property("volume", 1.0)
pipeline.set_state(Gst.State.PLAYING)
depths = [0, 24, 48, 72, 73]
for units in depths:
    hz, ms = indent.tone_for_units(units)
    src.emit("push-buffer", Gst.Buffer.new_wrapped(tone.render(hz, ms)))
src.emit("end-of-stream")
pipeline.get_bus().timed_pop_filtered(
    5 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
pipeline.set_state(Gst.State.NULL)

with wave.open(out) as handle:
    rate, channels, width = handle.getframerate(), handle.getnchannels(), handle.getsampwidth()
    frames, raw = handle.getnframes(), handle.readframes(handle.getnframes())
check("the chain preserves the sample rate", rate, tone.SAMPLE_RATE)
check("the chain preserves stereo 16-bit", (channels, width), (2, 2))
check("every frame pushed comes out again", frames,
      sum(tone.frame_count(*indent.tone_for_units(u)) for u in depths))

stride = channels * width
offset = 0
for units in depths:
    hz, ms = indent.tone_for_units(units)
    count = tone.frame_count(hz, ms)
    segment = [struct.unpack_from("<h", raw, (offset + i) * stride)[0]
               for i in range(count)]
    # Measure between the first and last rising crossing rather than counting
    # crossings over the whole window: the tone now ends one sample past its
    # last cycle, and counting would score that closing sample as a missing
    # half period.
    rising = [i for i in range(1, count)
              if segment[i - 1] < 0 <= segment[i]]
    measured = ((len(rising) - 1) * rate / (rising[-1] - rising[0])
                if len(rising) > 1 else 0.0)
    close(f"{units} rungs arrives at the right pitch", measured, hz, hz * 0.005 + 1.0)
    offset += count
os.remove(out)

# --- typing the indentation -----------------------------------------------
# A different signal from reading a line: it fires only when the edit was
# whitespace AND everything before the caret on that line is whitespace. The
# pitch follows what is before the caret, so holding space down climbs a step
# per press and backspacing comes back down.
from orca.ax_text import AXText  # noqa: E402
from indent_beeper import beeper as B  # noqa: E402

import orca.input_event_manager as _iem  # noqa: E402


class FakeEventManager:
    """Answers the questions the two gates ask about the last keypress.

    Both gates exist to keep the hooks off the accessibility bus when nothing
    a person did could have caused the event. The reading gate asks whether
    the last key was line navigation; the typing gate asks whether it could
    have typed or removed an indent. Both also require it to be *recent*,
    because Orca's own helpers answer about the last input event however old.
    """

    def __init__(self, line=False, paragraph=False, page=False, boundary=False,
                 typing=False, keyboard=True):
        self.line, self.paragraph, self.page = line, paragraph, page
        self.boundary, self.typing, self.keyboard = boundary, typing, keyboard

    def last_event_was_keyboard(self, within=None):
        return self.keyboard

    def last_event_was_line_navigation(self):
        return self.line

    def last_event_was_paragraph_navigation(self):
        return self.paragraph

    def last_event_was_page_navigation(self):
        return self.page

    def last_event_was_file_boundary_navigation(self):
        return self.boundary

    def last_event_was_return_tab_or_space(self):
        return self.typing

    def last_event_was_backspace(self):
        return self.typing


def set_last_event(**kwargs):
    manager = FakeEventManager(**kwargs)
    _iem.get_manager = lambda: manager


# The typing rows below are all about a person typing an indent, so the gate
# is open for them.
set_last_event(typing=True, line=True)

class FakeLine:
    """Stands in for a text object showing one line, with a caret in it."""
    def __init__(self, text, caret):
        self.text, self.caret = text, caret

AXText.get_caret_offset = staticmethod(lambda o: o.caret)
AXText.get_line_at_offset = staticmethod(lambda o, off: (o.text, 0, len(o.text)))

played = []
B._config = cfg.Config.load(Settings())
# The rows below exercise the pitch ladder and repeat depths freely, which
# change detection would silence. Change detection has its own block.
B._config.beep_on_change_only = False
B._cache.clear()
B._cache_identity = None

class FakePlayer:
    available = True
    last_volume = 0.0
    state_name = "playing"
    def set_volume(self, level): self.last_volume = level
    def play(self, pcm): played.append(len(pcm)); return "ok"

B._player = FakePlayer()


def typed(text, caret, changed):
    """Return the units beeped for an edit, or None for no beep."""
    played.clear()
    B.beep_for_typed_indent(FakeLine(text, caret), changed)
    if not played:
        return None
    for units in range(0, 400):
        if len(B._tone_for(units)) == played[0]:
            return units
    return "?"


check("typing the first space beeps one rung", typed(" ", 1, " "), 1)
check("the second beeps two", typed("  ", 2, " "), 2)
check("the fifth beeps five", typed("     ", 5, " "), 5)
check("a tab beeps four", typed("\t", 1, "\t"), 4)
check("backspacing a space comes back down", typed("   ", 3, " "), 3)
check("deleting the last of the indent returns to the base",
      typed("", 0, " "), 0)
check("typing a letter does not beep", typed("x", 1, "x"), None)
check("a space in the middle of prose does not beep",
      typed("hello world", 6, " "), None)
check("a space after text on an indented line does not beep",
      typed("    def f(a, b)", 13, " "), None)
check("a space typed before existing text still beeps",
      typed("   text", 3, " "), 3)
check("a non-breaking space typed as indentation beeps",
      typed("\u00a0\u00a0", 2, "\u00a0"), 2)
check("an empty edit does not beep", typed("   ", 3, ""), None)
B._config.beep_while_typing = False
check("the typing beep can be switched off", typed("  ", 2, " "), None)
B._config.beep_while_typing = True
B._config.enabled = False
check("the master toggle silences typing too", typed("  ", 2, " "), None)
B._config.enabled = True

# --- the tone reports a CHANGE of indentation, not a depth ----------------
# Toby's specification, verbatim: "if I go from one line with two spaces to a
# line with four, I hear the sound for four spaces. But if I then stay on 4
# spaces, I hear nothing. When 4 becomes 2, I hear the 2 spaces sound. Then
# when two becomes 0, I hear the zero spaces sound. If we then stay on zero
# spaces, no noise. When zero becomes 1 again, we get the sound for 1 space."

check("beeping on change only is the default", cfg.DEFAULT_BEEP_ON_CHANGE_ONLY, True)

B._player = FakePlayer()
B._config = cfg.Config.load(Settings())


def read(line):
    """The depth beeped for reading `line`, or None if it was silent."""
    played.clear()
    B.beep_for_line(line, source="test")
    if not played:
        return None
    for units in range(0, 400):
        if len(B._tone_for(units)) == played[0]:
            return units
    return "?"


def read_all(*lines):
    return [read(line) for line in lines]


B._last_units = None
check("his sequence, exactly as described",
      read_all("  two", "    four", "    four again", "  two", "zero", "zero again", " one"),
      [2, 4, None, 2, 0, None, 1])

# Each half of it on its own, so a failure says which rule broke.
B._last_units = None
check("the first line read always beeps", read("    x"), 4)
check("the same depth twice is silent", read("    y"), None)
check("the same depth many times stays silent",
      read_all("    a", "    b", "    c"), [None, None, None])
check("stepping in beeps the new depth", read("        deep"), 8)
check("stepping out beeps the new depth", read("  shallow"), 2)
check("coming back to the margin beeps the bottom of the ladder",
      read("margin"), 0)
check("staying at the margin is silent, however many lines",
      read_all("one", "two", "three"), [None, None, None])
check("leaving the margin beeps again", read(" x"), 1)
check("one space and two spaces are different depths", read("  x"), 2)
check("a tab and four spaces are the same depth, so no second beep",
      read_all("\tx", "    y"), [4, None])
check("a tab after a tab is silent", read("\tz"), None)

# A blank line has no indentation because it has no content. Counting it as a
# change to zero would beep twice per blank line -- down to the margin and
# back -- and report a structural change that never happened.
B._last_units = None
check("a blank line between two lines at one depth stays silent throughout",
      read_all("    def f():", "", "    def g():"), [4, None, None])
check("a blank line does not hide a real change that follows",
      read_all("", "        deeper"), [None, 8])
# A line holding only whitespace is blank too, and this reverses an earlier
# decision that it "has a depth of its own". It does not: there is nothing
# indented on it, the pitch came from whitespace nobody typed as indentation,
# and claiming a depth overwrote the one being tracked -- which is what put
# the following beeps in the wrong places.
check("a line of only spaces is blank too, and says nothing",
      read_all("    ", "        "), [None, None])
check("...and leaves the remembered depth for the next real line",
      read_all("    def f():", "        ", "    def g():"), [4, None, None])

# The reason the old guard never fired: Orca hands speak_line the line with
# its terminator still attached, so a blank line arrives as "\n".
B._last_units = None
check("a blank line still carrying its newline says nothing",
      read_all("    def f():", "\n", "    def g():"), [4, None, None])
B._last_units = None
check("nor does one with trailing whitespace before the newline",
      read_all("    def f():", "        \n", "    def g():"), [4, None, None])
B._last_units = None
check("but a real line keeps its terminator and still beeps",
      read_all("        deeper\n"), [8])

# Switching the beep on has to be audible whatever the last depth was, and it
# must not then silence the next line by claiming a depth of its own.
B._last_units = 4
played.clear()
B.beep_for_line("", source="toggle", force=True)
check("the toggle confirmation always beeps", bool(played), True)
check("the forced beep forgets the depth", B._last_units, None)
check("so the line after switching on beeps whatever it is", read("    x"), 4)

# Turning change-only off restores a beep on every line.
B._config.beep_on_change_only = False
B._last_units = None
check("with change-only off, every line beeps",
      read_all("    a", "    b", "zero", "zero"), [4, 4, 0, 0])
B._config.beep_on_change_only = True

# Typing is a change on every keystroke by definition, so it beeps on all of
# them -- including backspacing the last space away, which Toby asked for
# explicitly: "I want to know every indentation change, including backspacing
# from one space to zero."
B._last_units = None
check("typing climbs a rung per space",
      [typed(" ", 1, " "), typed("  ", 2, " "), typed("   ", 3, " ")], [1, 2, 3])
check("backspacing comes back down", typed("  ", 2, " "), 2)
check("backspacing the last space away beeps zero", typed("", 0, " "), 0)
check("a second edit that leaves the depth alone is silent",
      typed("", 0, " "), None)
check("typing after a read at the same depth is silent",
      (read("        x"), typed("        ", 8, " ")), (8, None))
B._last_units = None

# Settings changing invalidates the remembered depth: a different tab width
# means it is not even in the same units any more.
B._last_units = 4
B.settings_changed()
check("a settings change forgets the depth", B._last_units, None)

B._config = cfg.Config.load(Settings())
B._config.beep_on_change_only = False
B._last_units = None

# --- the device must be released between tones -----------------------------
# This is the regression for the fault that made the tone shrink away to
# nothing over a run of beeps on a Bluetooth output. Of the three add-ons here
# that play short sounds often, the one that survives A2DP -- audio_themes --
# is the one that returns its pipeline to NULL when each sound ends.
# capitalbeep parks in PAUSED and its tone vanishes; this add-on used to hold
# one stream in PLAYING and its tone shrank first. Wired output forgives all
# three.
from indent_beeper.player import TonePlayer, _descend_to_sink  # noqa: E402
import indent_beeper.player as P  # noqa: E402

player = TonePlayer()
check("nothing holds the device before a tone is played",
      player.state_name, "null")
check("the player reports itself available", player.available, True)
sink_element, sink_name = (_descend_to_sink(player._pipeline.get_by_name("sink"))
                           if player._pipeline else (None, "none"))
check("the real sink inside the bin can be found", sink_element is not None, True)
check("and the log can name it", bool(sink_name), True)

# A tone is a clip, not a moment in a stream. The old pipeline was a live
# source whose every buffer carried a wall-clock time the sink had to place it
# at, and mis-placing that on a drifting device is what cost us the tone.
check("the source is not live", player._source.get_property("is-live"), False)
check("...and nothing is timestamped",
      player._source.get_property("do-timestamp"), False)


def pump(predicate, seconds=3.0):
    """Run the main context until predicate holds, or give up."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


short = tone.render(440.0, 40)

# The one number that matters. A sink posts EOS only after it has played what
# it was given, so the interval from play() to the device closing is the tone's
# own length plus the sink's latency. An un-stamped buffer gives the sink no
# duration to drain: EOS then arrives in half the tone's length, the handler
# closes the device on top of it, and the beep is silent. Measured 26-30 ms
# un-stamped against 94-104 ms stamped, for a 61 ms tone.
short_ms = len(short) / 4 / tone.SAMPLE_RATE * 1000
clip = P._as_clip(short)
check("a tone is stamped from zero", clip.pts, 0)
close("...and carries its own duration",
      clip.duration / 1e6, short_ms, 1.0)

played_at = time.monotonic()
check("a tone plays", player.play(short), "ok")
check("...and the device is closed again once it ends",
      pump(lambda: player.state_name == "null"), True)
check("...only after the tone has actually had time to sound",
      (time.monotonic() - played_at) * 1000 > short_ms, True)
check("a second tone reuses the same pipeline", player.play(short), "ok")
check("...and closes the device again too",
      pump(lambda: player.state_name == "null"), True)

# A tone still sounding is cut short in favour of the new one, which is what
# audio_themes does: at key-repeat speed the tone you want is the one for the
# line you are on.
long_tone = tone.render(220.0, 180)
player.play(long_tone)
check("a tone arriving over a sounding one is accepted",
      player.play(short), "ok")
check("...and that one finishes normally",
      pump(lambda: player.state_name == "null"), True)

player.shutdown()
check("shutdown drops the pipeline", player._pipeline, None)
check("...and the player stops claiming to be available", player.available, False)
check("...and playing afterwards is a no-op, not a crash",
      player.play(short), "no-source")

# --- the other line-presentation path ------------------------------------
# Orca presents a line two ways and its own TODO says so: speak_line, which
# covers arrowing within one text object, and _generate_text_line, used by
# present_object for an object that *is* a line. LibreOffice Writer paragraphs
# are separate accessibles, so reading a Writer document took the second path
# and was silent -- 158 log lines from Toby's session held 147 from the typing
# hook and not one from say-line.
B._player = FakePlayer()
B._config = cfg.Config.load(Settings())
B._config.beep_on_change_only = False


def object_line(text, caret=0):
    """The depth beeped for presenting an object whose line is `text`."""
    played.clear()
    B._last_presentation = None
    B.beep_for_object_line(FakeLine(text, caret), source="test-object")
    if not played:
        return None
    for units in range(0, 400):
        if len(B._tone_for(units)) == played[0]:
            return units
    return "?"


set_last_event(line=True)
check("arrowing by line beeps for an object's line", object_line("\tword"), 4)
check("...and an unindented one is the bottom of the ladder",
      object_line("word"), 0)
set_last_event(paragraph=True)
check("paragraph navigation beeps too", object_line("\t\tword"), 8)
set_last_event(page=True)
check("so does page navigation", object_line("\tword"), 4)
set_last_event(boundary=True)
check("so does jumping to the start or end of the file",
      object_line("\tword"), 4)
set_last_event()
check("but a keypress that is not line navigation does not beep",
      object_line("\tword"), None)
set_last_event(line=True)
check("and neither does an object with no line at the caret",
      object_line(""), None)


check("a navigation key that is no longer recent does not beep",
      (set_last_event(line=True, keyboard=False), object_line("\tword"))[1],
      None)
set_last_event(line=True)


def failing_manager():
    raise RuntimeError("no manager")


_iem.get_manager = failing_manager
check("a manager that raises closes the gate rather than beeping",
      object_line("\tword"), None)
set_last_event(line=True)

# --- the same presentation arriving twice ---------------------------------
# Both paths can fire for one presentation, and several _generate_text_line
# calls can happen within one. That is a stutter, not two beeps.
B._config.beep_on_change_only = False
B._last_presentation = None
played.clear()
B.beep_for_presented_line("\tword", "test-a")
first = len(played)
B.beep_for_presented_line("\tword", "test-b")
check("the same line again straight away is one beep, not two",
      (first, len(played)), (1, 1))
B.beep_for_presented_line("\t\tword", "test-c")
check("...but a different line is its own beep", len(played), 2)
B._last_presentation_at -= B._PRESENTATION_WINDOW + 0.01
B.beep_for_presented_line("\t\tword", "test-d")
check("...and the same line after the window is a new presentation",
      len(played), 3)

# Two arrivals from the *same* hook are two presentations, not one seen
# twice -- holding Down through a run of identical lines. Suppressing those
# turned "beep for every line" into "beep at most once every 250ms", which at
# a repeat rate of 20 a second silences three lines in four.
played.clear()
B._last_presentation = None
B._last_presentation_source = None
B.beep_for_presented_line("}\n", "say-line")
B.beep_for_presented_line("}\n", "say-line")
B.beep_for_presented_line("}\n", "say-line")
check("the same line from the same hook is a beep each time", len(played), 3)
played.clear()
B.beep_for_presented_line("}\n", "object-line")
check("...but from the other hook it is the one presentation again",
      len(played), 0)

B._last_presentation = None

# --- the typing hook must not interrogate AT-SPI for other people's text ---
# It fires on any pure-whitespace insertion anywhere in the session. In one
# 90-second sample 147 of them came from a terminal printing indented output,
# each costing a caret query and a line query to conclude "not typing".
B._config = cfg.Config.load(Settings())
B._player = FakePlayer()


def typed_now(text, caret, changed):
    played.clear()
    B._last_units = None
    B.beep_for_typed_indent(FakeLine(text, caret), changed)
    return len(played)


set_last_event(typing=True)
check("a typed space still beeps", typed_now(" x", 1, " "), 1)
set_last_event(typing=False)
check("...but whitespace arriving with no typing keypress does not",
      typed_now(" x", 1, " "), 0)
set_last_event(keyboard=False, typing=True)
check("...nor when the keypress is too old to have caused it",
      typed_now(" x", 1, " "), 0)
set_last_event(typing=True)
check("a whitespace run longer than anyone types is not typing",
      typed_now(" " * 20 + "x", 20, " " * 20), 0)
check("...while a run short enough to be typed is",
      typed_now("    x", 4, "    "), 1)

width_name = max(len(r[0]) for r in rows)
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width_name}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)

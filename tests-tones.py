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
from gi.repository import Gst  # noqa: E402

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


worst = 0
for hz in (220.0, 226.45, 440.0, 880.0, 1760.0):
    want_n, want = nvda_generate(hz, 40, 100, 100)
    got = list(struct.iter_unpack("<hh", tone.render(hz, 40, fade_ms=0)))
    if len(got) != want_n:
        check(f"frame count at {hz:.0f} Hz", len(got), want_n)
        continue
    worst = max(worst, max(abs(a[0] - b[0]) for a, b in zip(got, want)))
check("waveform is NVDA's, sample for sample, with no fade", worst, 0)

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
flat_faded = sum(1 for s, _ in struct.iter_unpack("<hh", tone.render(440.0, 40))
                 if abs(s) >= tone.AMPLITUDE - 1)
check("the fade only trims the ends", flat_faded < flat, True)

# The fade exists because NVDA's whole-cycle rounding does not actually land on
# a zero crossing: samplesPerCycle is truncated while the phase is not.
raw = list(struct.iter_unpack("<hh", tone.render(1760.0, 40, fade_ms=0)))
check("without a fade the tone ends on a full-scale edge",
      abs(raw[-1][0]) == tone.AMPLITUDE, True)
faded = list(struct.iter_unpack("<hh", tone.render(1760.0, 40)))
check("with a fade it ends at zero", faded[-1][0], 0)
check("and still reaches full amplitude",
      max(abs(s) for s, _ in faded), tone.AMPLITUDE)

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
check("an out-of-range volume is clamped", c.volume, 1.0)
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
    crossings = sum(1 for i in range(1, count)
                    if (segment[i - 1] < 0) != (segment[i] < 0))
    measured = crossings / 2 / (count / rate)
    # Zero-crossing counting is granular to one crossing over the window, so
    # allow a per-tone tolerance rather than a flat one.
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
check("a whitespace-only line has a depth of its own, unlike an empty one",
      read_all("    ", "        "), [4, 8])
check("...and an empty line next to it still changes nothing",
      read_all("", "        "), [None, None])

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

# --- the sink must stay synchronised, and the buffers must carry the gaps ---
# These two rows are the regression for the bug that made the add-on useless:
# the beeps ran into one another and most were never heard as separate sounds.
# One continuous stream is carrying discrete tones, so the timestamp on each
# buffer is the only thing saying where the silence between them goes. Turning
# the sink's clock sync off throws that away and renders them back to back.
from indent_beeper.player import TonePlayer, _configure_sink  # noqa: E402

player = TonePlayer()
sink = player._pipeline.get_by_name("sink") if player._pipeline else None
_name, sync = _configure_sink(sink) if sink is not None else ("none", None)
check("the audio sink keeps clock sync ON", sync, True)
check("the pipeline is playing before the first tone", player.state_name, "playing")
player.shutdown()

# And the timestamps themselves: four tones pushed at a known interval must
# come out stamped at that interval, not packed end to end.
stamps = []
probe_pipeline = Gst.parse_launch(
    f"appsrc name=src caps={_CAPS} ! audiorate ! wavenc "
    f"! filesink location={os.path.join(os.environ.get('TMPDIR', '/tmp'), 'ib-ts.wav')}")
probe_src = probe_pipeline.get_by_name("src")
probe_src.set_property("format", Gst.Format.TIME)
probe_src.set_property("is-live", True)
probe_src.set_property("do-timestamp", True)
probe_src.get_static_pad("src").add_probe(
    Gst.PadProbeType.BUFFER,
    lambda _pad, info: (stamps.append(info.get_buffer().pts), Gst.PadProbeReturn.OK)[1])
probe_pipeline.set_state(Gst.State.PLAYING)
for _ in range(4):
    probe_src.emit("push-buffer", Gst.Buffer.new_wrapped(tone.render(440.0, 40)))
    time.sleep(0.2)
probe_src.emit("end-of-stream")
probe_pipeline.get_bus().timed_pop_filtered(
    5 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
probe_pipeline.set_state(Gst.State.NULL)
usable = [s for s in stamps if s != Gst.CLOCK_TIME_NONE]
check("every pushed tone is timestamped", len(usable), 4)
if len(usable) == 4:
    gaps = [(usable[i + 1] - usable[i]) / 1e6 for i in range(3)]
    close("the timestamps carry the real gap, not the tone length",
          sum(gaps) / 3, 200.0, 25.0)
    check("...which is far longer than the tone itself",
          all(g > 100 for g in gaps), True)
scratch = os.path.join(os.environ.get("TMPDIR", "/tmp"), "ib-ts.wav")
if os.path.exists(scratch):
    with wave.open(scratch) as handle:
        filled = handle.getnframes() / handle.getframerate() * 1000
    # audiorate fills the gaps from the timestamps, so the stream is far longer
    # than the tone data. If sync were off, the sink would produce the short
    # version instead -- which is what "cut off and disjointed" sounded like.
    close("gaps become real silence in the stream", filled, 640.0, 120.0)
    os.remove(scratch)

width_name = max(len(r[0]) for r in rows)
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width_name}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)

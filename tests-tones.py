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

width_name = max(len(r[0]) for r in rows)
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width_name}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)

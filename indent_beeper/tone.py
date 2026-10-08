"""The beep: NVDA's clipped sine, generated here rather than borrowed.

NVDA's indentation tone is not a plain sine. Its generator takes a sine,
multiplies it by two and hard-clips the result to full scale, which flattens
the top and bottom of every cycle. What you hear is part way between a sine
and a square wave: it carries odd harmonics, so it stays audible against
speech at a low level and over a small speaker, which is the whole point of
a tone you are meant to hear *while* something is being read to you.

The idea is NVDA's and the numbers below match it, because matching them is
how it comes out sounding right. The implementation is this file's own.

One detail is load-bearing and easy to miss. The tone's length is rounded
*up* to a whole number of cycles, so the waveform begins and ends at a zero
crossing. That is what keeps it from clicking, and it is why this does not
need the fade in and out that a plain gated sine does.
"""

from __future__ import annotations

import math
import struct

# NVDA's own figures, kept deliberately.
SAMPLE_RATE = 44100
# 14000 of a signed 16-bit full scale of 32767, so about 0.43. Headroom is
# wanted: the clipping below adds harmonics, and a clipped wave at full scale
# is unpleasant.
AMPLITUDE = 14000
# The sine is multiplied by this before clipping. 1.0 would be a pure sine;
# 2.0 spends roughly two thirds of each cycle clipped flat.
CLIP_GAIN = 2.0


def samples_per_cycle(frequency: float) -> int:
    """Whole samples in one cycle at this frequency, truncated as NVDA does."""
    return max(1, int(SAMPLE_RATE / frequency))


def frame_count(frequency: float, duration_ms: int) -> int:
    """Frames in a tone, rounded up to a whole number of cycles.

    Rounding up is what puts the end of the tone at a zero crossing. Asking
    for 40 ms at 220 Hz gives 40.8 ms, and the extra is inaudible next to the
    click you would get from stopping mid-cycle.
    """
    per_cycle = samples_per_cycle(frequency)
    total = int(SAMPLE_RATE * duration_ms / 1000)
    total += per_cycle - (total % per_cycle)
    return total


# Milliseconds of raised-cosine fade at each end. This is the one place where
# this deliberately does not do what NVDA does, and the reason is measurable.
# Rounding the length up to a whole number of cycles is *meant* to end the
# tone at a zero crossing, but samples_per_cycle is a truncated integer while
# the phase advances at the exact frequency, so the two drift apart and the
# tone can stop anywhere in the cycle. At 1760 Hz it stops at full negative
# scale -- a square edge, which clicks, and clipping has already put plenty of
# high harmonics there for the click to hide in. The higher the pitch the worse
# it gets, so the tone that clicks hardest is the one for the deepest indent.
#
# Four milliseconds of each end of a 40 ms tone is a tenth of it and leaves the
# timbre alone; what it removes is the edge. Set DEFAULT_FADE_MS to 0 to get
# NVDA's generator sample for sample, which is what the test asserts.
DEFAULT_FADE_MS = 4.0


def render(
    frequency: float,
    duration_ms: int,
    amplitude: int = AMPLITUDE,
    fade_ms: float = DEFAULT_FADE_MS,
) -> bytes:
    """Return one tone as interleaved stereo signed 16-bit little-endian PCM."""
    total = frame_count(frequency, duration_ms)
    # The exact frequency, not the truncated samples_per_cycle: NVDA's
    # generator is explicit about this, and using the truncated value would
    # detune every tone by up to half a sample per cycle.
    radians_per_sample = (2.0 * math.pi) / (SAMPLE_RATE / frequency)
    fade = min(total // 2, int(SAMPLE_RATE * fade_ms / 1000))
    frames = bytearray()
    pack = struct.Struct("<hh").pack
    for index in range(total):
        value = math.sin(index * radians_per_sample) * CLIP_GAIN
        value = min(max(value, -1.0), 1.0)
        if fade:
            if index < fade:
                value *= 0.5 - 0.5 * math.cos(math.pi * index / fade)
            elif index >= total - fade:
                remaining = total - 1 - index
                value *= 0.5 - 0.5 * math.cos(math.pi * remaining / fade)
        sample = int(value * amplitude)
        frames += pack(sample, sample)
    return bytes(frames)

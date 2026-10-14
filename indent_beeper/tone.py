"""The beep: NVDA's clipped sine, generated here rather than borrowed.

NVDA's indentation tone is not a plain sine. Its generator takes a sine,
multiplies it by two and hard-clips the result to full scale, which flattens
the top and bottom of every cycle. What you hear is part way between a sine
and a square wave: it carries odd harmonics, so it stays audible against
speech at a low level and over a small speaker, which is the whole point of
a tone you are meant to hear *while* something is being read to you.

The idea is NVDA's and the numbers below match it, because matching them is
how it comes out sounding right. The implementation is this file's own.

One detail is load-bearing and easy to miss: where the tone stops. A clipped
wave spends two thirds of every cycle at full scale, so stopping at the wrong
moment is a vertical edge straight to zero, and that clicks. NVDA rounds the
length up to a whole number of cycles to avoid it, but rounds using a
*truncated* samples-per-cycle while advancing the phase at the exact
frequency, so the two drift apart and the tone stops wherever it stops. On
this ladder 60 of the 73 rungs stopped above half scale and several stopped at
exactly full scale.

The length is now worked out from the exact frequency, which really does land
on a zero crossing -- within 0.03 of zero on all but one rung. That is Toby's
fix from pitermach/IndentBeeper#5, where he hit the same thing writing the
Hammerspoon version, and it is better than patching the edge with a fade.
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
    """Whole samples in one cycle at this frequency, truncated as NVDA does.

    Kept because it is what NVDA's generator uses, and the waveform test
    compares against NVDA. Nothing here sizes a tone with it any more: see
    frame_count.
    """
    return max(1, int(SAMPLE_RATE / frequency))


def frame_count(frequency: float, duration_ms: int) -> int:
    """Frames in a tone, rounded up to a whole number of cycles.

    Worked out from the exact frequency rather than from a truncated
    samples-per-cycle, so the last frame really is at a zero crossing. Asking
    for 60 ms at 220 Hz gives 63.7 ms, and the extra is inaudible next to the
    edge you would otherwise stop on.
    """
    cycles = math.ceil(duration_ms / 1000 * frequency)
    # One past the final cycle, so the closing zero is actually sounded.
    return int(cycles * SAMPLE_RATE / frequency + 0.5) + 1


# Milliseconds of raised-cosine fade at each end, and now zero by default.
#
# The fade was here to hide an ending that landed on a full-scale edge, which
# it did -- but 4 ms in and 4 ms out of a 60 ms tone is 13% of the tone spent
# ramping, and on a wave that is already flat-topped the result is an envelope
# you can hear. Toby's word for it was that the tone sounded "overly clipped".
# Now that frame_count ends on an actual zero crossing there is no edge left to
# hide, so the ramp goes. The parameter stays, because a fade is still the
# right answer if anyone changes the length calculation back.
DEFAULT_FADE_MS = 0.0


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

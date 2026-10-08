"""How much a line is indented, and what that should sound like.

The ladder is NVDA's: start at the A below middle A and climb a quarter tone
for every space, a tab counting as four. Where this parts company with NVDA is
what happens at the top. NVDA gives up and speaks the number of spaces
instead; here the ladder simply starts again from the bottom, and each time
round the tone is held a little longer. Nothing is ever spoken, because a beep
is quicker than a sentence and that is the whole point of having one.

So a pitch on its own is ambiguous -- 220 Hz is no indent, and it is also 73
spaces, and 146 -- and the length of the tone is what tells those apart. Short
means the first three octaves; longer means you have been round again.

Three octaves from A3 lands on A6, and every octave on the way up is an A,
which is the easiest interval there is to place without a reference tone.
"""

from __future__ import annotations

import re

from .config import (
    DEFAULT_BASE_DURATION_MS,
    DEFAULT_BASE_FREQUENCY,
    DEFAULT_FADE_MS,
    DEFAULT_MAX_DURATION_MS,
    DEFAULT_OCTAVES,
    DEFAULT_RUN_EXTRA_MS,
    DEFAULT_STEPS_PER_OCTAVE,
    DEFAULT_TAB_UNITS,
)

_LEADING_WHITESPACE = re.compile(r"[ \t]*")


def indentation_units(line: str, tab_units: int = DEFAULT_TAB_UNITS) -> int:
    """Rungs of the ladder for the leading whitespace of ``line``.

    A space is one rung, a tab is ``tab_units``. A non-breaking space counts as
    a space: it is one semantically, and a line pulled out of a web page or a
    word processor is full of them.

    Only leading whitespace counts. A line that is nothing but whitespace
    counts all of it -- there is no text for the indentation to sit in front
    of, but it is still a blank line at some depth, and saying so is useful.
    """
    if not line:
        return 0
    leading = _LEADING_WHITESPACE.match(line.replace(" ", " ")).group()
    return sum(tab_units if char == "\t" else 1 for char in leading)


def steps_per_run(
    steps_per_octave: int = DEFAULT_STEPS_PER_OCTAVE,
    octaves: int = DEFAULT_OCTAVES,
) -> int:
    """How many rungs one climb of the ladder has.

    One more than the number of steps in the range: the bottom A and the top A
    are both sounded, so three octaves at a quarter tone a step is 73 rungs,
    0 to 72, and the wrap happens on the 74th space.
    """
    return steps_per_octave * octaves + 1


def tone_for_units(
    units: int,
    base_frequency: float = DEFAULT_BASE_FREQUENCY,
    steps_per_octave: int = DEFAULT_STEPS_PER_OCTAVE,
    octaves: int = DEFAULT_OCTAVES,
    base_duration_ms: int = DEFAULT_BASE_DURATION_MS,
    run_extra_ms: int = DEFAULT_RUN_EXTRA_MS,
    max_duration_ms: int = DEFAULT_MAX_DURATION_MS,
) -> tuple[float, int]:
    """Return (frequency in Hz, duration in ms) for that many rungs."""
    run, step = divmod(max(0, units), steps_per_run(steps_per_octave, octaves))
    frequency = base_frequency * 2 ** (step / steps_per_octave)
    duration = min(base_duration_ms + run * run_extra_ms, max_duration_ms)
    return frequency, duration


def tone_for_config(units: int, config) -> tuple[float, int]:
    """Return (frequency, duration) for ``units`` under a Config."""
    return tone_for_units(
        units,
        base_frequency=config.base_frequency,
        steps_per_octave=config.steps_per_octave,
        octaves=config.octaves,
        base_duration_ms=config.base_duration_ms,
        run_extra_ms=config.run_extra_ms,
        max_duration_ms=config.max_duration_ms,
    )


def describe(units: int, config) -> str:
    """A one-line account of what a given depth will sound like, for logs."""
    frequency, duration = tone_for_config(units, config)
    run = units // steps_per_run(config.steps_per_octave, config.octaves)
    return (f"{units} units -> {frequency:.1f} Hz for {duration} ms"
            + (f" (run {run + 1})" if run else ""))


__all__ = [
    "DEFAULT_FADE_MS",
    "describe",
    "indentation_units",
    "steps_per_run",
    "tone_for_config",
    "tone_for_units",
]

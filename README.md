# Indent Beeper for Orca

Hear how deeply a line is indented instead of counting it out. A short tone
plays before each line, rising a quarter tone for every space and four steps
for every tab, so the shape of a file arrives in your ear while you arrow
through it.

The idea is [NVDA's](https://www.nvaccess.org/) indentation tones, which are
the best thing about reading code with a screen reader. The code here is its
own; the numbers match NVDA's because matching them is what makes it sound
right.

## How it sounds

The ladder starts at **A3, 220 Hz** — the A below middle A — for a line with no
indentation at all, and climbs **a quarter tone** (half a semitone) per space.
A tab is worth four spaces, so one tab is a tone and a half up, and **every six
tabs is exactly an octave**:

1. No indentation at all — A3, 220 Hz
2. One space — 226 Hz
3. One tab — B3, 247 Hz
4. Six tabs — A4, 440 Hz
5. Twelve tabs — A5, 880 Hz
6. Eighteen tabs — A6, 1760 Hz

Every octave on the way up lands on an A, which is the easiest interval there
is to place without a reference tone. And because four quarter tones make a
whole tone, **one tab is exactly one whole tone**, so indentation counted in
tabs climbs a whole-tone scale: A, B, C#, D#, F, G, and back to A at six tabs.

### Past the top

Eighteen tabs is as high as it goes. Rather than give up and start talking —
NVDA speaks the number of spaces at this point — **the ladder simply starts
again from the bottom, and the tone is held a little longer each time round**:

1. 73 spaces — A3 again, but held 70 ms instead of 40
2. 146 spaces — A3 again, 100 ms
3. 219 spaces — A3 again, 130 ms

So a pitch on its own is deliberately ambiguous — 220 Hz is no indent, and it
is also 73 spaces, and 146 — and the length of the tone is what tells them
apart. Short means the first three octaves; longer means you have been round
again. Nothing is ever spoken, because a beep is quicker than a sentence and
that is the whole point of having one.

The growth stops at 160 ms by default. "And so on" has to stop somewhere: a
line indented by a thousand spaces is a broken file, not a deep nest, and it
should not be answered with a tone that outlasts the line.

### The waveform

NVDA's tone is not a plain sine. Its generator takes a sine, doubles it and
hard-clips the result, which flattens the top and bottom of every cycle —
exactly two thirds of each one. What you hear is part way between a sine and a
square: it carries odd harmonics, so it stays audible against speech at a low
level and through a small speaker, which is what a tone you are meant to hear
*while* something is being read to you has to do.

This reproduces that generator sample for sample, with one deliberate
difference. NVDA rounds the length up to a whole number of cycles so the tone
ends at a zero crossing — but the cycle length it uses is a truncated integer
while the phase advances at the exact frequency, so the two drift apart and the
tone can stop anywhere. At 1760 Hz it stops at full scale, which clicks, and
the clipping has already put plenty of high harmonics there for the click to
hide in. So the tone that clicks hardest is the one for the deepest indent.

Four milliseconds of raised-cosine fade at each end fixes it and leaves the
timbre alone. Set **Fade at each end of the tone** to 0 if you would rather
have NVDA's output exactly, click included.

## Usage

**Orca+Ctrl+I** toggles the beep, says which it now is, and — when switching it
on — sounds the bottom of the ladder, so you have a reference for the next
line. The setting is remembered across restarts.

Everything else lives in **Orca Preferences → User Extensions → Indent
Beeper**:

1. **Beep the indentation of each line** — the same toggle as the keybinding.
2. **Beep for lines with no indentation** — on by default. Turning it off keeps
   prose quiet, at the cost of silence meaning both "no indent" and "switched
   off".
3. **Spaces a tab counts as** — 4, as in NVDA. Set it to whatever the files you
   read are actually indented with.
4. **Pitch for no indentation** — 220 Hz. Moves the whole ladder.
5. **Pitch steps per octave** — 24 for a quarter tone per space, 12 for a
   semitone (steeper, but it uses the range four times as fast), 48 for an
   eighth tone (finer grades of shallow indent).
6. **Octaves to climb before starting again** — 3.
7. **Tone length** — 40 ms.
8. **Milliseconds added each time the pitch starts again** — 30.
9. **Longest tone** — 160 ms.
10. **Beep volume**, and **scale the beep with Orca's speech volume** — on by
    default, so turning Orca down turns the beep down with it.
11. **Fade at each end of the tone** — see above.

This add-on declares its settings to Orca rather than carrying a dialog of its
own, because every one of them is a number or a toggle and the beep is its own
preview: change a value, arrow down a line, hear it.

### Orca's spoken indentation is separate

Orca has its own *spoken* indentation report, under Speech in Orca's
preferences. This does not touch it. Leave it on and you get both, which is
useful while you are learning the ladder; turn it off and the beep stands
alone, which is the point.

## Requirements

- [Orca](https://orca.gnome.org/) **51 or later** — this is a user extension,
  and the extension system did not exist before 51.
- GStreamer with `appsrc` and `autoaudiosink` (`gst-plugins-base` and
  `gst-plugins-good` on most distributions), and its Python bindings.
- Python 3.10+

## Installation

```bash
./install.sh
orca --replace &
```

The installer copies the package to
`~/.local/share/orca/extensions/indent_beeper/` and approves it with
`orca --approve-extension indent_beeper`.

Orca approves extensions **by content hash** and refuses to load one whose
files have changed since approval, so after editing anything under
`indent_beeper/` re-run `./install.sh` — it re-approves as part of installing.

Nothing is ever written inside the package: the tones are generated into
memory, so there is no data directory to keep outside it and nothing to
invalidate the hash behind your back.

## How it works

There is exactly one place this needs to hook. Orca's `Script.say_line` hands
the raw line to `SpeechPresenter.speak_line` — raw being the point, because the
leading whitespace is still on it at that moment and everything downstream is
entitled to strip it. Nothing overrides `say_line`, the web script included, so
patching `speak_line` covers arrowing by line, Home, End and anything else that
presents a line, in every application, from one hook. The beep goes in before
the original runs, so the tone leads the line rather than landing on top of its
first word.

A beep on every line is a beep on every press of Down, held down. Opening the
audio device per beep is out of the question at that rate, so the pipeline is
built once and left playing, and each beep is a buffer pushed into an `appsrc`:

```
appsrc ! audioconvert ! volume ! autoaudiosink
```

The sink runs with clock sync disabled, which is what makes a push play
straight away rather than being scheduled and then dropped for arriving late —
a beep is wanted now or not at all. Rendered tones are cached by depth, so
arrowing through a file costs a dictionary lookup per line.

## Tests

`tests-tones.py` runs against the installed extension:

```bash
./install.sh && python3 tests-tones.py
```

48 rows. It reimplements NVDA's C generator from `nvdaHelper/local/beeps.cpp`
and asserts this one matches it sample for sample with the fade off; it checks
the ladder climbs, wraps and lengthens as described, and that an out-of-range
setting is clamped rather than trusted; and it pushes tones through a real
GStreamer chain ending in a file, so the pitch and length that come out the far
end are measured rather than assumed.

## Licence

MIT. The tone generator is an independent implementation: the behaviour it
reproduces is not itself protected, and a clipped sine is about as old as
digital audio.

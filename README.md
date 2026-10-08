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

1. 73 spaces — A3 again, but held 90 ms instead of 60
2. 146 spaces — A3 again, 120 ms
3. 219 spaces — A3 again, 150 ms

So a pitch on its own is deliberately ambiguous — 220 Hz is no indent, and it
is also 73 spaces, and 146 — and the length of the tone is what tells them
apart. Short means the first three octaves; longer means you have been round
again. Nothing is ever spoken, because a beep is quicker than a sentence and
that is the whole point of having one.

The growth stops at 180 ms by default. "And so on" has to stop somewhere: a
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

## Where it beeps

1. **Reading a line** — arrowing by line, Page Up and Down, Home and End, and
   anything else that presents a line, in any application.
2. **Flat review** — reviewing by line beeps too, since flat review presents
   its own lines and never goes near the ordinary line-reading path.
3. **Typing the indentation** — a space or tab typed while everything before
   the caret on that line is whitespace beeps one rung higher, and backspacing
   it away comes back down. So you hear an indent being built as well as read.
   Typing a letter does not beep, and neither does a space in the middle of a
   sentence.

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
3. **Beep while typing the indentation of a line** — on by default.
4. **Spaces a tab counts as** — 4, as in NVDA. Set it to whatever the files you
   read are actually indented with.
5. **Pitch for no indentation** — 220 Hz. Moves the whole ladder.
6. **Pitch steps per octave** — 24 for a quarter tone per space, 12 for a
   semitone (steeper, but it uses the range four times as fast), 48 for an
   eighth tone (finer grades of shallow indent).
7. **Octaves to climb before starting again** — 3.
8. **Tone length** — 60 ms. NVDA uses 40, which is a shade short.
9. **Milliseconds added each time the pitch starts again** — 30.
10. **Longest tone** — 180 ms.
11. **Beep volume**, and **scale the beep with Orca's speech volume** — on by
    default, so turning Orca down turns the beep down with it.
12. **Fade at each end of the tone** — see above.
13. **Log diagnostics** — see below.

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

Reading a line hooks `SpeechPresenter.speak_line`, which is where
`Script.say_line` hands the line over — raw being the point, because the
leading whitespace is still on it at that moment and everything downstream is
entitled to strip it. Nothing overrides `say_line`, the web script included, so
that one patch covers line navigation in every application. The beep goes in
before the original runs, so the tone leads the line rather than landing on top
of its first word.

Flat review needs its own hook on `FlatReviewPresenter._line_presentation`,
because it presents its own lines and never calls `say_line`. Braille events
are skipped there, matching Orca: they present no speech, so they get no tone.

Typing hooks the two text-change handlers, `Script._on_text_inserted` and
`_on_text_deleted`, which is where Orca learns what was inserted or removed.
That signal is deliberately narrow — the edit has to be whitespace *and*
everything before the caret on that line has to be whitespace — so it fires
for an indent being built and not for prose.

The pipeline is primed with five milliseconds of silence at startup, which
looks odd and is load-bearing: a live `appsrc` does not finish its transition
to PLAYING until a buffer arrives, so without the priming the first real tone
was pushed into a pipeline still in PAUSED and lost.

A beep on every line is a beep on every press of Down, held down. Opening the
audio device per beep is out of the question at that rate, so the pipeline is
built once and left playing, and each beep is a buffer pushed into an `appsrc`:

```
appsrc ! audioconvert ! volume ! autoaudiosink
```

**The sink stays synchronised to the clock, and that is load-bearing.** One
continuous stream is carrying discrete sounds separated by seconds of nothing,
and the only thing saying where that silence goes is the timestamp on each
buffer. `do-timestamp` stamps them as they arrive and does so accurately: four
tones pushed 300 ms apart come out stamped 0, 301, 603 and 904 ms.

Turning sync off throws that away — the sink then renders each buffer the
instant it arrives, back to back, so four short tones pushed over 1.2 seconds
become a sixth of a second of continuous warble, drifting further behind the
keyboard with every press, and most beeps are never heard as separate sounds
at all. Two test
rows guard against it coming back.

Rendered tones are cached by depth, so arrowing through a file costs a
dictionary lookup per line.

## Tests

`tests-tones.py` runs against the installed extension:

```bash
./install.sh && python3 tests-tones.py
```

68 rows. It reimplements NVDA's C generator from `nvdaHelper/local/beeps.cpp`
and asserts this one matches it sample for sample with the fade off; it checks
the ladder climbs, wraps and lengthens as described, and that an out-of-range
setting is clamped rather than trusted; and it pushes tones through a real
GStreamer chain ending in a file, so the pitch and length that come out the far
end are measured rather than assumed. The typing rows check the narrow signal
in both directions: which edits beep, which are correctly ignored, and that
both the typing toggle and the master toggle silence it.

If something is not beeping, switch on **Log diagnostics** in Orca
Preferences → User Extensions → Indent Beeper and read the log:

```bash
tail -f ~/.local/share/orca/indent_beeper/debug.log
```

It is a setting rather than only an environment variable for a reason: where
Orca runs as a systemd user service, `ORCA_INDENT_BEEPER_DEBUG=1 orca --replace`
sets the variable on the shell's Orca, which then hands over to the
service-managed process that never saw it — so the log stays empty. The setting
needs no restart. The environment variable still works if Orca is started from
a shell with the service stopped.

Every beep logs its source (`say-line`, `flat-review` or `typing`), the depth,
the pitch, the volume, what the audio push returned and the pipeline's state —
and every decision *not* to beep logs its reason. The log lives outside the
package, because Orca hashes everything inside it.

## Licence

MIT. The tone generator is an independent implementation: the behaviour it
reproduces is not itself protected, and a clipped sine is about as old as
digital audio.

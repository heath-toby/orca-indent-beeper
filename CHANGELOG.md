# Changelog

## 1.5.0

Six fixes from a code review of 1.4.0.

**"Beep for every line" had quietly become "beep at most once every 250 ms".**
1.4.0 added a stutter guard, because both line-presentation paths can fire for
one presentation. But it keyed on the line text alone, so two *genuine*
presentations of the same text — holding Down through blank lines, a run of
`}`, a repeated table row — counted as one. With beep-on-change-only switched
off, which is the mode that exists to beep per line, a repeat rate of 20 a
second silenced three lines in four. Only a *different* hook reporting the same
line is a duplicate now.

**The typing hook interrogated AT-SPI about other people's text.** It fires on
any pure-whitespace insertion anywhere in the session and then asks for the
caret offset and the line before concluding "not typing". In one 90-second
sample, 147 of those arrived from a terminal printing indented output — about
one and a half a second, two accessibility round trips each. Two free checks
now come first: a whitespace run longer than eight characters is a program
writing rather than a person typing, and the last keypress must have been
recent and must have been space, tab, return or backspace, which are the only
keys that build or remove an indent.

**The reading gate had no recency bound.** Orca's `last_event_was_*` helpers
answer about the last input event however old it is, so a presentation that no
keypress caused — focus moving on a timer, a dialog opening by itself —
inherited the arrow key pressed before it. A keystroke and the event it causes
are milliseconds apart, so both gates now require the keypress to be within a
second. A mouse click in between already closed the gate on its own, because
Orca's helpers return nothing once the last input event is not a keyboard
event.

**`device` reported `?` in every beep line ever logged.** 1.4.0 fixed
`describe()` to re-resolve the sink, having found that `autoaudiosink` holds a
placeholder until it profiles the hardware — and left the identical defect one
property along. `current-device` was read from the element captured at
construction, which is a `fakesink` and has no such property, so the read
raised every time. It resolves the sink when asked now, and reports the real
output. `describe()` also no longer prints a stale sink name after shutdown.

**`shutdown()` kept the pipeline alive for the session.** The autoaudiosink bin
added in 1.4.0 was not cleared, and a GStreamer child holds a reference to its
parent — the same leak that removing the bus signal watch is there to prevent.

**A load-bearing comment was false.** It said LibreOffice's generator "calls
super() in both of its branches, so the base-class patch is still reached.
Checked rather than assumed." There are three exits, and an object supporting
text whose line is empty returns `[messages.BLANK]` without calling super() at
all. Nothing misbehaves — a blank line has no indentation to report and two
separate guards would have suppressed it — but the comment is the reason the
patch sits where it does, and the next person would have trusted it.

Also: the debug log rolls past 2MB, keeping one previous log as `debug.log.1`,
because diagnostics get left on. 136 test rows, up from 128.

## 1.4.0

**Reading a LibreOffice Writer document was completely silent.** Reported by
Toby: *"Not a single beep when reading, but every beep is correct when
writing."*

**Orca has two code paths for presenting a line,** and says so itself, in a
TODO above `SpeechGenerator.generate_line`:

> generate_line duplicates _generate_text_line. speak_line (the sole caller of
> generate_line) should be consolidated with the _generate_text_line path used
> by present_object/generate_speech so there is one code path for line
> presentation.

1.3.0 hooked only the first. `speak_line` covers arrowing within a single text
object, which is what a terminal is — hence a terminal being perfect. A
LibreOffice Writer paragraph is its own accessible, so moving between
paragraphs presents a different *object* each time and goes through
`_generate_text_line`, where there was no hook at all. The debug log settled it
in one reading: of 158 lines from Toby's session, 147 came from the typing hook
and **not one** from `say-line`.

- **Hooks `_generate_text_line` as well.** Patched on the base
  `SpeechGenerator`: LibreOffice's generator overrides the method but calls
  `super()` in both of its branches, so the base-class patch is still reached.
  Checked rather than assumed.

- **Gated on the last keypress having been line navigation** — line, page or
  file-boundary navigation, which are the reasons `scripts/default.py` routes
  to `say_line`, plus paragraph navigation, which a Writer user leans on and
  which also presents a line. Without the gate this leaf would beep for every
  focused text field and every tab into an entry, because it generates their
  speech too. A manager that raises closes the gate rather than beeping.

- **The same presentation arriving twice is one beep.** Both paths can fire for
  a single presentation, and several `_generate_text_line` calls can happen
  within one; an identical line inside 250 ms is taken to be the same
  presentation rather than a second one. That is a stutter guard, and it is
  separate from the change gate, which still decides whether a *different*
  depth is worth a tone.

- The line is read at the caret rather than taken from the generator, which
  computes its text several different ways depending on the object. The leading
  whitespace is the whole point here, and the line at the caret always has it.

Also: the debug log now records the line it suppressed on the "unchanged" path,
and every `say-line` records the line Orca handed over beside the line the
object holds at that moment, flagged `same` or `DIFFERENT`. Without that the
three possible explanations for a missing beep were indistinguishable, which is
why this took a second attempt.

Also fixed: `TonePlayer.describe()` reported the sink name captured at
construction, and `autoaudiosink` has not chosen a real sink while the pipeline
is at NULL — it holds a placeholder named `fake-audio-sink` until it profiles
the hardware on the way to PLAYING. So every log this add-on has ever written
said `sink=fake-audio-sink`, which reads exactly like "the beep is going
nowhere" and was never true. The name is now re-read when asked for: at NULL it
still says `fake-audio-sink`, and after one tone it says
`sink-actual-sink-pulse`.

128 test rows, up from 117.

## 1.3.0

**The tone stops where it should, and lines with nothing on them stay quiet.** Two faults
that between them accounted for the beeps sounding wrong and landing in the wrong places.

### Fixed

- **A line with nothing on it no longer beeps.** The guard for this was `if not line`,
  which is almost never true: Orca hands `speak_line` the line with its terminator still
  attached, so a blank line arrives as `"\n"` and went straight past it. With trailing
  whitespace it arrived as `"    \n"` and sounded a pitch taken from whitespace nobody
  typed as indentation. **44 of 200 beeps in a twenty-minute log were lines with no content
  on them**, and because each one also overwrote the remembered depth, the real lines
  either side of it beeped when they should have been silent. The guard now tests the
  stripped line.

  This reverses 1.2.0's decision that a whitespace-only line "has a depth of its own". It
  does not: nothing is indented on it.

- **The tone no longer stops on a vertical edge.** The length is now worked out from the
  exact frequency instead of from a truncated samples-per-cycle, so the last frame really
  does land on a zero crossing. Measured across the 73 rungs, **60 of them used to stop
  above half of full scale** and several stopped at exactly full scale. The remaining
  residue is bounded by half a sample of phase — nothing at 220 Hz, a quarter of full scale
  at 1760 Hz, where a cycle is only 25 samples long. This is Toby's fix from
  [pitermach/IndentBeeper#5](https://github.com/pitermach/IndentBeeper/pull/5), where he hit
  the same thing writing the Hammerspoon version.

- **The device is released between tones, which is what finally fixed the tone shrinking
  away to nothing.** Of the three add-ons here that play short sounds often, exactly one
  survives a Bluetooth output, and the difference is its pipeline's lifecycle:

  1. `audio_themes` returns its pipeline to **NULL** when each sound ends. Toby: *"it can
     play as many sounds as you like, and they won't cut off."*
  2. `capitalbeep` prerolls to **PAUSED** and parks there between beeps — its own comment
     says "so that repeated beeps only need a seek, not a device reopen" — which holds the
     device open. Its tone vanishes if you hear it often enough.
  3. This add-on held one stream in **PLAYING** for the session. Its tone got shorter and
     shorter over a run of beeps and then disappeared.

  Wired output forgives all three; A2DP forgives none but the first. So the player now
  builds one pipeline, drives it PLAYING for each tone and back to NULL when the tone ends,
  and the tone is an ordinary clip rather than a live buffer stamped with a wall-clock
  moment the sink has to hit. Nothing is carried from one beep to the next.

  The cost is a device open per tone, measured at 36-47 ms on Orca's main loop. That cost
  is exactly why the first version held one stream open; `audio_themes` pays it on every
  focus change and is the better precedent.

  A tone is stamped `pts=0` with its own duration, the way a file source would deliver it.
  Dropping the wall clock but leaving the buffer unstamped altogether silenced the beep
  completely: with no duration the sink posted EOS in **26-30 ms for a 61 ms tone** — before
  the audio could play — and the EOS handler closed the device on top of it. Stamped, EOS
  comes at **94-104 ms**, the tone plus the sink's own latency. A test row now measures that
  interval, because it is the whole fault in one number.

- **The sink's `buffer-time` and `latency-time` are no longer forced** to 100 ms and 10 ms.
  That was set on the reasoning that the defaults are sized for music; measured on an A2DP
  sink it halved the ring buffer, and `audio_themes` sets neither.

- **Superseded within the hour: the stream lifetime bounds.** It used to be opened once and
  held for the whole session. When the default output changed — a dock unplugged, Bluetooth
  headphones connected — PipeWire moved the stream to the new device rather than failing it,
  but the sink element kept the buffer size and latency it had negotiated for the old one. A
  Bluetooth sink's latency is large and variable, so every buffer was then scheduled against
  a stale picture and the tone arrived for a line you had left seconds ago. The stream is
  now closed after ten seconds of quiet and reopened on the next beep, so nothing survives
  long enough to inherit the wrong device.

  Orca's own sounds have never had this problem and the way they avoid it is the model:
  `sound.py` sets its pipeline to PLAYING for each sound and a timeout puts it back to NULL
  when the sound ends. This add-on cannot go quite that far — a beep per line under key
  repeat is tens of streams a second — so it keeps the stream through a burst and drops it
  after. Measured: no reopens at all during a burst of six beeps 120 ms apart, pushes still
  0.2 ms, and **38.7 ms on the first beep after a pause**, on Bluetooth, which is the
  slowest case.

  An idle teardown and a maximum stream age were added first, as bounds on a fault that was
  not yet understood. Both are gone: a pipeline that returns to NULL after every tone has no
  lifetime to bound.

- **The log records which output the tone went to**, read live from pulsesink's
  `current-device`. If that changes between two beeps, the stream was moved underneath us.

### Changed

- **The fade is off by default**, because there is no longer an edge for it to hide. Four
  milliseconds in and out of a 60 ms tone is 13% of the tone spent ramping, and on a wave
  that is flat-topped two thirds of the time that envelope is audible. The setting stays,
  and is the right answer again if the length calculation is ever reverted.

- **The beep is as loud as the Mac version**, which peaks at 0.21 of full scale. The
  generator peaks at 0.427 and the beep is scaled again by Orca's speech volume, so the
  default beep volume is now 1.1 and the ceiling is 2.0 rather than 1.0. There is headroom
  to spare: 2.0 against a speech volume of 10 peaks at 0.855, so nothing in range clips.

### Notes

- Measured and ruled out while chasing this: the audio path. The pipeline was rebuilt
  exactly and fed tones 33, 80, 150, 500 and 2500 ms apart — every buffer rendered in full,
  nothing dropped, nothing truncated, `push-buffer` returning in 0.1–0.2 ms, and no drift
  against the clock. Aliasing in the clipped wave was measured too, at 0.014% of the tone's
  energy worst case, which rules out the 44.1 kHz-into-192 kHz resampling on this machine.

- A "lateness" figure was added to the debug line and then removed the same afternoon: on a
  live appsrc, `query_position` returns the timestamp of the last buffer pushed, so
  comparing it with the pipeline clock reports the time since the last beep. It read
  +239 ms on a brand-new pipeline and +239 ms after a rebuild, which is how it got caught.
  The output device name replaced it.

- Tests: **112 rows**, up from 95. Each fix was checked by reverting it and confirming only
  its own rows went red.

## 1.2.0

**The tone now reports a change of indentation rather than a depth.** Reading down a block
of code at a constant indent is silent; the line that steps in or out of it sounds. Coming
back to the left margin is a change like any other and sounds the bottom of the ladder;
staying there is silent after the first line.

### Added

- **Beep only when the indentation changes** — Orca Preferences → User Extensions → Indent
  Beeper, on by default. Turn it off to beep every line, which is NVDA's behaviour and what
  1.0.0 and 1.1.0 did.

### Changed

- **Replaces 1.1.0's "Least indentation worth a beep, in spaces"**, which was a
  misunderstanding of the request and lasted one release. A floor silences shallow
  indentation permanently; what was wanted was silence for *unchanged* indentation at any
  depth, including zero. Every depth beeps again, as long as it has changed. The 1.0.0
  setting "Beep for lines with no indentation" is likewise gone — an unindented line beeps
  when the indentation changes to zero, and is silent when it has not.
- **A line with nothing on it changes nothing.** A blank line has no indentation because it
  has no content, not because the code came back to the margin. Counting it as a change to
  zero would beep twice for every blank line in a file — once down and once back — and
  report a structural change that never happened; Orca already says "blank". A line of
  *only whitespace* is different: that has a real depth, and it beeps.
- **Typing beeps on every keystroke in the indentation**, because every keystroke there is
  a change. Backspacing the last space away beeps the bottom of the ladder: there was an
  indent and now there is not. 1.1.0 had wrongly gone quiet instead.
- The remembered depth is forgotten — so the next line beeps whatever it is — on switching
  the beep on with Orca+Ctrl+I, on any settings change (a changed tab width means the
  remembered depth is not even in the same units), and at the start of a session. The
  toggle's confirmation tone sounds whatever the last depth was, and deliberately does not
  claim a depth of its own.

### Tests

- `tests-tones.py` is **95 rows**, all green, including the requested sequence asserted
  verbatim: two, four, four again, two, zero, zero again, one space → `[2, 4, None, 2, 0,
  None, 1]`.

## 1.1.0

Superseded by 1.2.0 within the hour, on the author's correction: a minimum depth was not
what was wanted. Kept here because the tag exists.

### Added

- **A minimum depth worth a beep.** Orca Preferences → User Extensions → Indent Beeper →
  **Least indentation worth a beep, in spaces**, default **2**, meaning more than one
  space. Below the threshold there is no tone at all: a line at the left margin is silent,
  and so is a line with one stray space, while a tab still sounds at four units. Reading
  prose is therefore quiet, which is the point — every line of a paragraph sits at the
  margin, a tone on all of them carries no information, and an ear soon stops hearing it.
  Returning to the margin and staying there says nothing, rather than beeping the bottom of
  the ladder once per line.

  Set it to 0 for the old behaviour. The cost of a threshold is that silence now means
  either "not indented enough to matter" or "the beep is off"; toggling with Orca+Ctrl+I
  still beeps once to confirm, which is how you tell those apart — that confirmation tone
  deliberately ignores the threshold, or switching the add-on on would be silent.

### Changed

- **Replaces the 1.0.0 setting "Beep for lines with no indentation"**, which was the same
  idea with only two positions. An install that had turned it *off* wanted the margin
  quiet, so it is carried across as a threshold of 1 — exactly its old behaviour, nothing
  overridden. Everyone else gets the new default of 2.
- Typing the indentation now goes quiet when backspacing drops below the threshold, instead
  of reporting its way down to the margin. Reading and typing agree about what is too
  shallow to mention.

### Tests

- `tests-tones.py` is 68 rows → **92**, all green. The new rows cover the predicate itself,
  the read path, the typing path, the toggle's forced confirmation tone, clamping, and the
  carry-over from the setting this replaces.

## 1.0.0

- First release. NVDA's clipped-sine beep, verified sample for sample against
  `nvdaHelper`'s `generateBeep` with the fade off: A3 220 Hz for no indentation, a quarter
  tone per space, a tab worth four.
- Where it parts company with NVDA: at the top of three octaves (A6, 1760 Hz, 73 rungs) the
  ladder starts again from the bottom and the tone is held 30 ms longer each time round, to
  a ceiling of 180 ms. Nothing is ever spoken — a beep is quicker than a sentence, which is
  the whole reason to have one.
- Hooks `SpeechPresenter.speak_line` for caret movement, `FlatReviewPresenter.
  _line_presentation` for flat review, and the default script's text-change handlers so the
  tone climbs as the indentation is typed.
- Toggle on Orca+Ctrl+I, remembered across restarts. 13 declared preferences, no dialog of
  its own — the beep is its own preview.

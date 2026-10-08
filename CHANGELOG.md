# Changelog

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

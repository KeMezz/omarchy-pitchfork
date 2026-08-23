# Pitchfork design notes

Why the plugin is built the way it is. The front page covers installing and
using it; this covers the parts that would otherwise be rediscovered by
reading the source.

## Tuning model

`Tunings.js` holds the model and every pitch calculation the panel makes. Notes
are stored as names — a 6-string guitar is
`["E2", "A2", "D3", "G3", "B3", "E4"]` — rather than as frequencies. A table of
frequencies would be magic numbers no reader can check against a fretboard, and
it would hide the octave, which is the single likeliest thing to get wrong here
and the thing the tests assert hardest. Frequencies are derived from the names
against the `CONCERT_A_HZ` constant.

Resolution is to the nearest string rather than to the nearest semitone, which
is the reason to choose an instrument at all. A string a whole tone flat still
reports the string the player meant, so the direction to turn the peg is never
ambiguous. Chromatic would call the same pitch a D2 and say nothing about the E
being tuned.

### Three axes, not one list

The panel used to offer one flat list mixing instruments and references —
`Guitar standard`, `Drop D`, `Bass 4-string`. That list grows multiplicatively:
half-step down across five instruments is five new rows, and a reader scanning
it cannot tell which axis a row varies.

What replaced it:

| Axis | Control | What it is |
| --- | --- | --- |
| Family | Three chips, always visible | Chromatic, Guitar, Bass |
| Instrument | Dropdown | The string set: 6- or 7-string guitar, 4-, 5- or 6-string bass |
| Tuning | Dropdown | A transform over that set |

References are transforms rather than a second table of note names. `shift`
moves every string, `drop` moves only the bottom one, and `voicing` replaces the
set outright for the named alternates that are not a transposition of anything
(DADGAD). So `Half-step down` is one entry that serves every instrument, and
`Drop` names itself from the note the bottom string lands on — Drop D on a
6-string guitar, Drop A on a 7-string. A reference that does not apply to an
instrument is simply absent from its menu: DADGAD lists `only: ["guitar6"]`.

**Chromatic is a family, not an instrument and not a mode flag.** It has no
instruments, so `instrumentOptions("chromatic")` is empty, so the tuning menu is
empty too, and the panel hides both rows: a chromatic tuner is asked nothing
because there is nothing it needs to know. The empty string set then falls out
of the same code path everything else uses — a nearest-string search over no
strings is the nearest semitone, and the target strip has nothing to draw.

The chip row rather than a fourth dropdown is deliberate: the family decides
which instruments and which references the two rows below it can even offer, so
it is the one choice that has to be readable without opening anything.

### One validator

`normalize(stored)` is the only thing that decides whether a combination is
legal, and everything goes through it — reading the state file, clicking a chip,
choosing a row. It always answers a triple the three controls can display, so a
state the panel cannot render is not reachable by clicking, only corrected. The
tests assert that on a spread of malformed records, and that the answer is
idempotent, so re-reading what the panel wrote changes nothing.

That is also where migration lives. `legacyTunings` maps every flat preset id
the old schema could hold onto the new triple, because `main` is the release
channel and anything shipped is installed: silently resetting a player's
instrument on upgrade is not an acceptable failure. An unrecognised record
degrades to chromatic, which asks nothing and works for any instrument.

### The state file

The state file was `input.json` and is now `settings.json`, because it carries
the instrument and the reference alongside the input. **Nothing migrates the old
name, and that does lose something**: remembering a *non-default* input was the
whole purpose of `input.json`, so anyone who had picked an interface is silently
returned to the PipeWire default. That failure is quiet in the worst way —
`pw-cat` does not complain about the substitution, so it presents as a tuner
that simply stopped finding notes. Pick the input again after upgrading, and
delete the stale `input.json`.

A missing `settings.json` is read as first-run defaults — the PipeWire default
input, and chromatic.

## Panel chrome

The panel is built from the shell's own `qs.Ui` kit, with one exception.

`PitchDropdown.qml` is the plugin's own dropdown, and it exists for its popup
height. The kit's `Dropdown` sets the popup's **outer** height to the height its
rows need; the popup then subtracts its border and padding from that to size the
list, so the list is always a few pixels shorter than its content and every menu
scrolls by exactly that sliver. A list that can be dragged two pixels reads as
broken rather than as scrollable.

`PitchDropdown` sizes the popup's **content** box instead, and picks between two
heights:

- **rows ≤ 8** — the exact height of the rows, and the list is set
  `interactive: false`, so it cannot be dragged or wheeled at all.
- **rows > 8** — seven full rows plus half of the eighth. The cut-off row is
  itself the affordance: it says there is more without leaving an ambiguous gap.

Both menus on the tuning axis are short enough to always land in the first case,
which a test asserts. Only the input list can overflow.

The delegate also marks the row currently in force, which the kit's dropdown
does not: it paints only the cursor, so an open menu says where you are but not
what you already chose.

Two smaller notes on the component:

- It imports `qs.Ui` explicitly. `BorderSurface` lives there, and a plugin file
  outside that directory gets no implicit import of it — `qmllint` resolves it
  through `-I` and passes, and the shell then reports `BorderSurface is not a
  type` at runtime.
- It emits `changed` and never assigns its own `value`. The kit's dropdown
  writes the selection onto `value`, which destroys the caller's binding to it;
  the panel needs that binding intact, because choosing an instrument can reset
  the tuning row underneath it and the trigger has to follow.

### Showing that a string is in tune

Being in tune tints the whole reading card — background, border, note colour and
needle together — and fills the matched string's slot in the strip. Colour on
the note text alone is something the player has to look for, which is the
opposite of what a tuner is for while both hands are on the instrument.

Every colour comes from the theme: `Color.accent` for in tune, `Color.urgent`
for the needle off it, and the bar's own foreground for everything else. There
are no hex literals in the QML. Note that the bar icon binds `Color.accent`
directly rather than going through `BarIconButton`'s `active`/`activeColor` —
that pair is the urgent colour, and being in tune is the opposite of urgent.

## Audio architecture

Quickshell has no audio capture API, and QML has no realistic path to running a
pitch detector in the render thread. The plugin therefore uses the same pattern
the Omarchy shell itself uses for `inotifywait`: a subprocess writes lines, and
QML parses them.

```
PipeWire input
  │
  │  pw-cat --record - --raw --rate 16000 --channels 1 --format s16
  ▼
scripts/pitch-detect.py          ← the only component that touches audio
  │
  │  one JSON object per line on stdout, flushed per reading
  ▼
Panel.qml: Process { stdout: SplitParser { onRead: ... } }
```

### Detector protocol

One JSON object per line on stdout. Keep this stable; it is what makes the
detector and the panel independently replaceable.

| Field        | Meaning                                                        |
| ------------ | -------------------------------------------------------------- |
| `hz`         | Detected fundamental in Hz, or `0.0` when there is no pitch.    |
| `confidence` | `0.0`–`1.0`, derived from YIN aperiodicity.                     |
| `level`      | Input RMS as a fraction of full scale. Drives the level meter.  |
| `source`     | Detector identity.                                             |
| `error`      | Optional human-readable problem. `hz` is `0.0` alongside it.    |
| `aperiodicity` | Diagnostic. The value the rejection threshold tested. Absent when the frame never reached detection. |

A reading is emitted per hop, so about 15 per second. stderr is diagnostic only
and is not part of the protocol.

### How detection works

YIN, in two stages, because a tuner has to resolve a cent or two while a bass
low B sits near 31 Hz — and those two requirements pull the window length in
opposite directions.

1. **Coarse.** The 2048-sample window (128 ms at 16 kHz) is box-decimated by 8
   to 2 kHz, and a cumulative-mean-normalized difference function is evaluated
   over lags 4–71, i.e. 28–500 Hz. The first dip below 0.12 wins, which is what
   keeps the result off octave multiples.
2. **Refine.** The period is re-searched at the full 16 kHz over ±8 lags around
   the coarse estimate, then parabolic interpolation puts it between samples.
   Without that interpolation one sample of period error is about 8 cents at a
   bass low E, which no tuner can use.

Two filters keep wrong notes off the screen:

- **Aperiodicity rejection** above 0.20 reports no pitch. A tone buried in
  wideband noise still scores under 0.08, while a window straddling two
  different notes — what the detector sees for one hop after a new string is
  plucked — lands between 0.23 and 0.33.
- **A median of the last three readings** removes isolated octave and
  half-period errors, which rejection alone cannot catch because they can look
  perfectly periodic. The cost is that a newly plucked string takes an extra
  hop or two to settle. Every hardware tuner does the same.

### Measured behaviour

`--selftest` is the regression check, and it asserts these:

| Case                                        | Result             |
| ------------------------------------------- | ------------------ |
| Clean tones, 30.87–329.63 Hz                | within 0.05 cents  |
| Same tones under wideband noise             | within 1.3 cents   |
| Silence, and wideband noise alone           | no pitch reported  |
| Cost per frame                              | 1.9 ms of a 64 ms budget (3% of one core) |

Those numbers come from synthetic signals. A real instrument through a real
input is a harder case; the self test is there to catch regressions, not to
predict accuracy in a room.

### The detector runs only while the panel is open

`Process.running` is bound to the panel's `opened` state, and the detector's
own child is bound to the detector: `pitch-detect.py` sets `PR_SET_PDEATHSIG`
on `pw-cat` so the kernel kills the capture process if the detector dies
without cleaning up — Quickshell may `SIGKILL` it, in which case no `finally`
of ours runs. An orphaned `pw-cat` would be an open capture stream with no UI
attached, which is exactly the thing this plugin must never leave behind.

Three mechanisms cover the three ways it can end: an orderly exit calls
`terminate()`, a `SIGKILL` is caught by `PR_SET_PDEATHSIG`, and anything else
leaves `pw-cat` writing to a closed pipe.

A detector that exits is not restarted while the panel stays open — Quickshell
only re-evaluates `Process.running` when `opened` changes — so the panel keeps
the error the detector reported on its way out and tells the reader that
reopening is the retry.

## Dependencies

Everything here is checked against a stock Omarchy 4.0 system.

| Dependency | Status on a stock system | Used for |
| ---------- | ------------------------ | -------- |
| `python3` ≥ 3.12 | Present (3.14)     | The pitch detector. |
| `node` | Development only  | `make test`. Not needed to run the plugin. |
| `pw-cat`   | Present, shipped by PipeWire | Capturing raw PCM from the input. |

The 3.12 floor is `math.sumprod`, which is what makes a stdlib-only detector
viable: the difference function is expanded into two energy terms and a dot
product, so the only per-sample work happens inside a C loop. A Python-level
inner loop here is what forces tuners like this one into numpy.

No external package is required, and adding one should be a deliberate decision
rather than a convenience:

- **`aubio`, `numpy`, and `sox` are all absent** from a stock system, and none
  of them are needed.
- A bundled or compiled binary, an installer, a systemd unit, `sudo`, or
  `pkexec` would all put the plugin into the marketplace's manual security
  review queue. None of them are used.
- No network access.
- No privileged actions.

### Choosing an input

The panel lists capture devices only. PipeWire publishes no monitor nodes — the
`<sink>.monitor` sources `pactl` reports are a PulseAudio compatibility
invention — so a sink's output cannot be picked from the dropdown even though
`pitch-detect.py --list-inputs` lists those names, because that command reads
`pactl` rather than the PipeWire graph.

The Input row is a `PitchDropdown` like the other two, and it is the only one of
the three whose list can overflow. Its options are built from `Pipewire.nodes`,
filtered to real capture sources. It deliberately never reads
`PwNode.properties`: that is invalid until a node is bound, and the built-in
audio panel documents that reading it while capture streams appear can
destabilise Quickshell's Pipewire service — and this plugin creates a capture
stream every time its panel opens.

While a popup owns the keyboard, `PanelKeyCatcher.blocked` stops the panel's own
cursor model from double-driving on j/k. All three dropdowns are in that
condition, so any control added to the panel that takes the keyboard has to join
it.

Which input to pick matters more than it sounds. A laptop's internal microphone
array is a poor tuner input: its broadband noise floor sits high enough that a
quietly played instrument never becomes the most periodic thing in the window.
An unplugged electric instrument is not audible to it at all — that needs an
audio interface, and no software setting substitutes for one.

```
scripts/pitch-detect.py --list-inputs                   # the same list, in a shell
pactl set-source-volume @DEFAULT_SOURCE@ 100%           # the array is often low
```

### Microphone access

The plugin opens an audio input while its panel is open, and only then. It
captures to memory, analyses each window, and discards it; nothing is written
to disk and nothing leaves the machine.

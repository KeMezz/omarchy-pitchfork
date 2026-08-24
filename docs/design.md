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
the instrument and the reference alongside the input. When the current file is
absent, startup checks these records in order:

1. `~/.config/omarchy-tuner/settings.json`, the previous directory with the
   current multi-axis schema;
2. `~/.config/omarchy-pitchfork/input.json`, a defensive path for the old
   single-input schema under the renamed directory;
3. `~/.config/omarchy-tuner/input.json`, the original single-input record.

The directory creation and all reads complete before hydration, so a fast
missing-file result cannot install defaults ahead of a slower legacy read. A
selected legacy record is normalised and atomically written as the complete
current `settings.json`; subsequent starts therefore take the current file and
the migration happens once. Legacy files are left in place as a recovery copy.
Capture also waits for hydration, so opening the panel during startup cannot
launch `pw-cat` on the default input before a saved target is known.

When neither the current nor a legacy record exists, first-run defaults are the
PipeWire default input and chromatic tuning.

Each monitor has its own panel instance. Before a write, the panel synchronously
reads the newest record, merges only the locally changed fields, and completes a
blocking atomic write through that same reader. Those tiny transactions share
the QML thread, so a second monitor sees the first one's change even before its
file notification is delivered. A watched change also uses that blocking
reader: consecutive notifications cannot be coalesced into a stale async
completion. A click during initial hydration is queued and merged by the same
path.

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

### Plain text is a security boundary

Every QML `Text` element pins `textFormat: Text.PlainText`. The panel displays
PipeWire device names and descriptions, an input id restored from disk, and
detector error output; none of those strings is authored by the QML. Leaving
the default `Text.AutoText` would let markup-shaped content be interpreted as
rich text, including loading resources referenced by that content from inside
the long-lived shell process.

`scripts/check-text-format.py` enforces the rule over every `Text`, including
inline declarations. Apart from QML's formatter-managed `id`, it requires the
exact binding to be the first member of the object and searches every `Text {`
and `Text on property {` declaration independently. QML identifiers, including
Unicode escapes, are decoded before comparison. That deliberately fail-closed
rule avoids interpreting embedded JavaScript: nested templates,
regex/division ambiguity, ASI and unrelated braces cannot hide a sink or lend
it a binding from another object. Unsafe or noncanonical direct `textFormat`
occurrences are rejected too, catching direct assignments, `PropertyChanges`,
and quoted `Binding` property names in QML or imported runtime JavaScript. This
is a fail-closed regression policy rather than a JavaScript interpreter;
deliberately computed property names are outside its claim. Its stdlib tests
cover canonical order,
inline elements, nested children, comments, strings, regex literals, sibling
elements, non-plain formats, and expressions that merely start with the
PlainText token. This is part of `make check`, alongside `qmllint`.

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

YIN, in two stages, because a tuner has to resolve a cent or two while a
down-tuned 5- or 6-string bass reaches A0 at 27.5 Hz — and those two
requirements pull the window length in opposite directions.

1. **Coarse.** The 2048-sample window (128 ms at 16 kHz) is box-decimated by 3
   to about 5.33 kHz, and a cumulative-mean-normalized difference function is
   evaluated over lags 10–223, i.e. 24–500 Hz. The first dip below 0.12 wins,
   which is what keeps the result off octave multiples. The dense coarse grid
   is deliberate: at 8:1 decimation A#3 and D#4 could settle one octave low;
   even 4:1 could do the same for a harmonic-rich A#4.
2. **Refine.** The period is re-searched at the full 16 kHz over ±3 lags around
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

`--selftest` is a synthetic smoke and performance check. Its pass/fail bounds
are deliberately looser than the values usually observed on a clean generated
tone; the bounds, rather than one developer machine's latest measurements, are
the maintained contract:

| Case | Required result |
| ---- | --------------- |
| Thirteen clean targets from A0 (27.50 Hz) through B4 (493.88 Hz), including A#3, D#4 and A#4 | a pitch at the correct octave, within 2 cents |
| Representative noisy tones at 41.20, 82.41 and 196.00 Hz | within 5 cents |
| Silence, and wideband noise alone | no pitch reported |
| Average cost over 100 frames | below the 64 ms hop budget |

Those numbers come from synthetic signals. A real instrument through a real
input is a harder case; the self test is there to catch regressions, not to
predict accuracy in a room.

`tests/pitch_detect_test.py` is the deeper stdlib-only regression suite. It
feeds continuous PCM through the deployed window, hop, and smoother path for
every semitone in the full 24–500 Hz chromatic range, at two phases and with
one, three, and six harmonics. That superset covers every unique note produced
by the shipped instrument/tuning combinations, including A0, A#3, D#4 and A#4.
It also checks tuning margin around A0 and E4, distinguishes range rejection
from aperiodicity rejection, and verifies that any unexpected `pw-cat` EOF is
surfaced as an error even when the child reports status zero or leaves a partial
final PCM block.

The same suite pins both parent-death failures called out during the community
marketplace review: a failed `prctl` must abort before capture, and a parent
change immediately after arming must exit before `exec`. A Linux integration
test then kills a helper with `SIGKILL` and observes that its guarded child also
stops. `make test` runs this suite, the `Text.PlainText` policy-lint tests, the
Node tuning-model tests, and `--selftest`; `make check` adds manifest and QML
validation.

The GitHub Actions workflow runs that portable test set plus manifest JSON,
tracked-symlink, shell-syntax, and live QML text-sink checks. It deliberately
does not label itself `make check`: the authoritative plugin validator,
`qmllint`, and the `qs.Ui` import tree are supplied by Omarchy and do not exist
on a generic Ubuntu runner. A release still requires `make check` on Omarchy
and validation of a fresh clone.

### The detector runs only while the panel is open

`Process.running` requires the panel to be open, state hydration to be complete,
and `detectorArmed` to be true. The detector's own child is bound to the
detector: `pitch-detect.py` sets `PR_SET_PDEATHSIG` on `pw-cat` so the kernel
kills the capture process if the detector dies without cleaning up — Quickshell
may `SIGKILL` it, in which case no `finally` of ours runs. An orphaned `pw-cat`
would be an open capture stream with no UI attached, which is exactly the thing
this plugin must never leave behind.

Three mechanisms cover the three ways it can end: an orderly exit calls
`terminate()`, a `SIGKILL` is caught by `PR_SET_PDEATHSIG`, and anything else
leaves `pw-cat` writing to a closed pipe. Conversely, `pw-cat` has no successful
EOF while the panel remains open: even a zero-status exit is reported instead
of leaving the panel silently idle.

An unexpected detector exit does not itself change any of those bindings, so
Quickshell does not automatically restart it. The panel keeps the detector's
error and presents closing and reopening as the retry. Explicitly selecting a
different input also toggles `detectorArmed` and intentionally restarts capture.

## Dependencies

Everything here is checked against a stock Omarchy 4.0 system. `make doctor`
checks the complete local development toolchain and rejects a Python that is
too old or lacks `math.sumprod`.

| Dependency | Scope | Used for |
| ---------- | ----- | -------- |
| Omarchy Quattro and Quickshell | Runtime host | Loading the plugin, `qs.Ui`, panel IPC, and the existing PipeWire node model. |
| `python3` ≥ 3.12 with `math.sumprod` | Runtime; present on stock Omarchy | The pitch detector. |
| `pw-cat` from PipeWire | Runtime; present on stock Omarchy | Capturing raw PCM from the selected input. |
| `mkdir` from GNU coreutils | Runtime; present on stock Omarchy | Creating the parent directory for the single settings file. |
| Linux libc `prctl` | Runtime platform API | Arming `PR_SET_PDEATHSIG` so capture cannot outlive the panel. |
| `pactl` from `pipewire-pulse` | Optional diagnostics | `pitch-detect.py --list-inputs` only; the panel and detector do not require it. |
| `node` | Development only | Parsing `Tunings.js` and running its stdlib-only tests. |
| `qmllint`, `qmlformat` | Development only | QML validation and formatting. |
| `make`, `jq`, `rsync`, `inotifywait` | Development only | Validation, development sync, and watch mode. |
| `omarchy`, `omarchy-shell`, `qs` | Development and host administration | Plugin validation, discovery, IPC, and shell diagnostics. |
| GitHub-hosted Actions with pinned official checkout/setup actions | CI only | Checking out the source and provisioning Python 3.12 and Node 24; this uses the runner's GitHub/tool-download network access. |

The 3.12 floor is `math.sumprod`, which is what makes a stdlib-only detector
viable: the difference function is expanded into two energy terms and a dot
product, so the only per-sample work happens inside a C loop. A Python-level
inner loop here is what forces tuners like this one into numpy.

No third-party Python or Node package is required, and adding one should be a
deliberate decision rather than a convenience:

- **`aubio`, `numpy`, and `sox` are all absent** from a stock system, and none
  of them are needed.
- There is no bundled or compiled binary, plugin-owned installer, or systemd
  unit, and the plugin performs no privileged action.
- Runtime has no network dependency and initiates no network connection.
  Installation and updates use Omarchy's normal Git clone/fetch from GitHub;
  no plugin code downloads anything.
- Pitchfork consumes the already-running Omarchy shell and PipeWire services;
  it installs, starts, stops, and reconfigures no service.

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
scripts/pitch-detect.py --list-inputs                   # pactl diagnostics, including monitors
pactl set-source-volume @DEFAULT_SOURCE@ 100%           # the array is often low
```

### Microphone access

The plugin opens an audio input while its panel is open, and only then. It
captures to memory, analyses each window, and discards it; nothing is written
to disk and nothing leaves the machine.

# Pitchfork design notes

Why the plugin is built the way it is. The front page covers installing and
using it; this covers the parts that would otherwise be rediscovered by
reading the source.

## Tuning model

`Tunings.js` holds the preset list and every pitch calculation the panel makes.
Targets are stored as note names — guitar standard is
`["E2", "A2", "D3", "G3", "B3", "E4"]` — rather than as frequencies. A table of
frequencies would be magic numbers no reader can check against a fretboard, and
it would hide the octave, which is the single likeliest thing to get wrong here
and the thing the tests assert hardest. Frequencies are derived from the names
against the `CONCERT_A_HZ` constant.

Resolution is to the nearest target rather than to the nearest semitone, which
is the reason to choose a tuning at all. A string a whole tone flat still
reports the string the player meant, so the direction to turn the peg is never
ambiguous. Chromatic would call the same pitch a D2 and say nothing about the E
being tuned.

"Chromatic" is an entry in the tuning list rather than a separate mode. It is
the first preset and its target list is empty, so it falls out of the same code
path everything else uses: a nearest-target search over no targets is the
nearest semitone, and the target strip has nothing to draw. One dropdown
therefore covers the whole feature. A mode toggle would be a second control
competing for the width of a bar popup, and the panel does not have the room to
spend on it.

The state file was `input.json` and is now `settings.json`, because it carries
the tuning and the reference alongside the input. **Nothing migrates the old
name, and that does lose something**: remembering a *non-default* input was the
whole purpose of `input.json`, so anyone who had picked an interface is silently
returned to the PipeWire default. That failure is quiet in the worst way —
`pw-cat` does not complain about the substitution, so it presents as a tuner
that simply stopped finding notes. Pick the input again after upgrading, and
delete the stale `input.json`.

No migration code exists because this plugin has one install, whose stored value
was the default. Code that can never run is worse than a documented step; if the
plugin is ever published with users on the old name, the migration goes in
before the rename ships.

A missing `settings.json` is read as first-run defaults — the PipeWire default
input, and chromatic.

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


The panel's Input dropdown is the shared `qs.Ui` `Dropdown`, so it matches every
other select in the shell and keeps the panel short when it is closed. While its
popup owns the keyboard, `PanelKeyCatcher.blocked` stops the panel's own cursor
model from double-driving on j/k. The tuning dropdown blocks it the same way, so
any control added to the panel that takes the keyboard has to join that
condition. Its options are built from `Pipewire.nodes`,
filtered to real capture sources. It deliberately never reads `PwNode.properties`: that is invalid until
a node is bound, and the built-in audio panel documents that reading it while
capture streams appear can destabilise Quickshell's Pipewire service — and this
plugin creates a capture stream every time its panel opens.

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

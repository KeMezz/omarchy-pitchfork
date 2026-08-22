# Tuner

An instrument tuner for the Omarchy Quattro bar. Shows the note, the deviation
in cents, and the detected frequency for a guitar or bass on a PipeWire input.

Plugin id: `dev.hyeongjin.tuner`

## Status

Working. Audio capture and pitch detection are implemented; the panel shows the
note, the cents offset, the frequency, and the input level.

Not done yet: there is no input picker in the panel. The panel launches the
detector with no arguments, so it captures from the system default source. The
`--target` flag below only applies to standalone runs; the panel's only lever is
the `TUNER_TARGET` environment variable, which has to be set in the environment
the Omarchy shell itself was started in.

Note that `pw-cat` does not fail on an unknown `--target`: it falls back to the
default source silently, so a typo in a node name looks like a working tuner
listening to the wrong input.

## Development

```
make doctor       # check the local toolchain
make check        # validate the manifest and lint QML
make install-dev  # copy, discover, and enable the plugin
make sync         # validate and copy a change into Omarchy
make watch        # sync automatically whenever source changes
make summon       # open the tuner panel
make logs         # tail recent Omarchy shell logs
```

The detector runs standalone, which is the fastest way to work on it:

```
scripts/pitch-detect.py --selftest        # synthetic tones, no audio device
scripts/pitch-detect.py --meter           # live level and pitch in the terminal
scripts/pitch-detect.py --list-inputs     # PipeWire sources --target accepts
scripts/pitch-detect.py --stdin < raw.pcm # raw s16 mono PCM, pw-cat bypassed
scripts/pitch-detect.py --target <node>   # a specific PipeWire source
```

`--meter` is the first thing to reach for when the panel shows no note. It
separates the two failures that look identical from the panel:

```
  [###############   ] 0.0724   --                aper 0.49 > 0.20, rejected
  [################  ] 0.2265   E2  +0.1c  82.41 Hz   aper 0.01
```

A moving level bar means capture works. Aperiodicity is what the rejection
threshold actually tests, so a note that will not register shows up as a number
over the limit rather than as silence.

`Makefile` and `scripts/*.sh` are a copy of the shared playground toolchain
rather than a shared dependency, so a fix in one repository has to be ported to
the other by hand.

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

There is no picker in the panel yet, so the detector captures from the PipeWire
default source. On a laptop that is usually the internal microphone array,
which is a poor tuner input: its broadband noise floor sits high enough that a
quietly played instrument never becomes the most periodic thing in the window.
An unplugged electric instrument is not audible to it at all — that needs an
audio interface, and no software setting substitutes for one.

```
scripts/pitch-detect.py --list-inputs                   # see what exists
pactl set-source-volume @DEFAULT_SOURCE@ 100%           # the array is often low
pactl set-default-source <node>                         # point the panel at it
```

### Microphone access

The plugin opens an audio input while its panel is open, and only then. It
captures to memory, analyses each window, and discards it; nothing is written
to disk and nothing leaves the machine.

## License

MIT. See `LICENSE`.

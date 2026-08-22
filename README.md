# Tuner

An instrument tuner for the Omarchy Quattro bar. Shows the note, the deviation
in cents, and the detected frequency for a guitar or bass plugged into a
PipeWire input.

Plugin id: `dev.hyeongjin.tuner`

## Status

Scaffold. The UI, the bar widget, and the detector plumbing are in place, but
`scripts/pitch-detect.py` currently emits **synthetic** readings and does not
open an audio device. The panel labels itself as such while that is true.

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
  │  pw-cat -r --raw --rate 8000 --channels 1 --format s16 -
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
| `hz`         | Detected fundamental in Hz, or `0.0` when nothing is playing.   |
| `confidence` | `0.0`–`1.0`. The panel may ignore low-confidence readings.      |
| `source`     | Detector identity, so the panel can label placeholder data.     |
| `error`      | Optional human-readable problem. `hz` should be `0.0` with it.  |

stderr is diagnostic only and is not part of the protocol.

### The detector runs only while the panel is open

`Process.running` is bound to the panel's `opened` state. A tuner that keeps a
capture stream alive in the background is a microphone nobody asked for, and it
would burn CPU for a panel nobody is looking at.

## Dependencies

Everything here is checked against a stock Omarchy 4.0 system.

| Dependency | Status on a stock system | Used for |
| ---------- | ------------------------ | -------- |
| `python3`  | Present (3.14)           | The pitch detector. |
| `pw-cat` / `pw-record` | Present, shipped by PipeWire | Capturing raw PCM from the selected input. |

No external package is required today, and adding one should be a deliberate
decision rather than a convenience:

- **`aubio`, `numpy`, and `sox` are all absent** from a stock system. The
  detector is Python-stdlib-only for that reason.
- A bundled or compiled binary, an installer, a systemd unit, `sudo`, or
  `pkexec` would all put the plugin into the marketplace's manual security
  review queue. None of them are used.
- No network access.
- No privileged actions.

### Known implementation risk

Autocorrelation or YIN in pure Python has not been benchmarked here. A 4-string
bass low E is 41.2 Hz, which needs a window of roughly 500 samples at an 8 kHz
capture rate, and the lag search over that window has to finish inside the
frame interval. If pure Python cannot hold a usable refresh rate, the options
are, in order of preference: a coarse-to-fine lag search, a lower capture rate,
a documented `python-numpy` dependency, and only then a compiled helper.

## License

MIT. See `LICENSE`.

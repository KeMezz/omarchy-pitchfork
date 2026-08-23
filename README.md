# Pitchfork

An instrument tuner for the Omarchy Quattro bar. Shows the note, the deviation
in cents, and the detected frequency for a guitar or bass on a PipeWire input.

## Install

```
omarchy plugin add https://github.com/KeMezz/omarchy-pitchfork.git --enable
```

Plugin id: `dev.hyeongjin.pitchfork`

## What it does to your machine

Plugins run as unsandboxed code inside the long-lived Omarchy shell process, so
this belongs above everything else rather than in a footnote.

- **It opens an audio input, and only while its panel is open.** Closing the
  panel ends the capture; there is no background listening. Audio is analysed a
  window at a time in memory and discarded — nothing is written to disk and
  nothing leaves the machine.
- **It spawns one child process**, `pw-cat`, to read that input, and reads pitch
  readings back from a Python script over a pipe. Both are bound to the panel's
  lifetime, including if the shell kills the plugin outright.
- **No network access. No privileged actions** — no `sudo`, no `pkexec`, no
  systemd units, no installer, no bundled binaries.
- **Requirements**, both present on a stock Omarchy system: `pw-cat` (ships with
  PipeWire) and `python3` 3.12 or newer.

## Using it

Click the tuning fork in the bar. Pick an input, pick a tuning, play a note.

The panel shows the note, the deviation in cents, the frequency, and the input
level. The bar widget's fork turns the accent colour while the note is in tune,
so it reads at a glance without the panel open.

A laptop's internal microphone is a poor input for this: its noise floor is high
enough that a quietly played instrument never becomes the most periodic thing in
the window, and an unplugged electric instrument is not audible to it at all.
An audio interface is the difference between a tuner that works and one that
never finds a pitch.

A tuning is chosen from a dropdown, and the strings of that tuning sit under the
meter as a strip. A string lights up once it has been played in tune for half a
second, which is a stop the player made rather than a value a peg swept through
on the way somewhere else. The strip starts empty again whenever the panel opens
or the tuning changes, because either one begins a fresh pass over the strings.
Chromatic has no strings and so shows no strip.

Concert pitch is fixed at A4 = 440. The panel briefly offered an adjustable
reference and it was removed: outside ensemble work nobody reaches for it, and
no measurement can distinguish the two readings it would produce anyway — a
string 8 cents sharp at A4 = 440 and a string in tune at A4 = 442 are the same
frequency, so which one it is lives in the player's intent rather than in the
signal.

The tuning never reaches the detector. It is interpretation of a frequency that
was already measured in hertz, so changing it leaves capture running.

A reading outlives the note that produced it by 1.5 seconds, dimmed for as long
as it is held. A plucked string dies while the player is still looking at the
fretboard, and a readout that blanks the moment the note decays is one they
never get to read. A live reading always wins, so the hold can only extend a
stale value and never delays a fresh one. The bar widget's fork is deliberately
left out of it: the fork has no dimmed state, and an accent colour held after
the note died would claim a string is in tune with nothing sounding.

The panel offers the available PipeWire inputs in a collapsed dropdown and
remembers the input, the tuning, and the reference in
`~/.config/omarchy-pitchfork/settings.json`. "System default" is the default input
and stays first in the list, so an unplugged interface is never a dead end.

Note that `pw-cat` does not fail on an unknown `--target`: it falls back to the
default source silently, so a stale node name looks like a working tuner
listening to the wrong input. The picker says so when the stored choice is not
among the connected sources.

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

## Development

```
make doctor       # check the local toolchain
make check        # validate the manifest and lint QML
make install-dev  # copy, discover, and enable the plugin
make sync         # validate and copy a change into Omarchy
make watch        # sync automatically whenever source changes
make summon       # open the Pitchfork panel
make logs         # tail recent Omarchy shell logs
```

The pitch arithmetic in `Tunings.js` has its own tests, which run under plain
node — the plugin has no package manifest and must not gain one, so nothing
that needs installing can be a test dependency:

```
node tests/tunings.test.mjs
```

`make check` does not run them; it validates the manifest and lints QML. A
change to `Tunings.js` needs both.

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

The note column in that output is chromatic and stays that way. The detector is
a signal diagnostic rather than a tuner: it reports `hz`, and the naming it does
for the terminal is there to make a reading legible, not to
agree with the panel. With a tuning chosen, the two name
the same pitch differently, and that is expected.

`Makefile` and `scripts/*.sh` are a copy of the shared playground toolchain
rather than a shared dependency, so a fix in one repository has to be ported to
the other by hand.

### QML changes need a shell restart

`make sync` is enough for `scripts/pitch-detect.py`, because the detector is a
subprocess the shell spawns fresh from disk every time the panel opens. It is
**not** enough for the QML. This Omarchy build has no hot reload for local
plugin components: `PluginRegistry` emits `localPluginChanged` and nothing in
the shell listens to it, so a synced `.qml` sits on disk while the shell keeps
serving the copy it loaded at startup.

```
make sync && omarchy-restart-shell
```

Do not reach for `omarchy refresh shell` instead — that resets `shell.json` to
defaults and takes every plugin out of the bar with it.

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

## License

MIT. See `LICENSE`.

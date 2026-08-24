#!/usr/bin/env python3
"""Pitch detector for the Omarchy tuner plugin.

Captures mono audio from a PipeWire input through `pw-cat` and writes one
pitch reading per line to stdout. Standard library only; see docs/design.md for the
line protocol and why there is no numpy dependency.

Detection is YIN: a cumulative-mean-normalized difference function picks the
period, which is then refined at the full sample rate and interpolated to
sub-sample precision. The work is done in two stages because a tuner has to
resolve a cent or two while a bass low B sits near 31 Hz, and those two pull
the window length in opposite directions.

Usage:
    pitch-detect.py [--target NODE] [--rate HZ] [--gate LEVEL]
    pitch-detect.py --stdin      read raw s16 mono PCM from stdin
    pitch-detect.py --selftest   verify the detector against synthetic tones
"""

from __future__ import annotations

import argparse
import array
import ctypes
import json
import math
import os
import signal
import subprocess
import sys

# Capture format. 16 kHz keeps the refine stage cheap while leaving one
# full-rate sample worth about 8 cents at a bass low E, which parabolic
# interpolation then brings inside a cent.
RATE = 16000
WINDOW = 2048
HOP = 1024
# Decimation for the coarse stage. A box filter of this length is a crude
# anti-alias, but its first null sits at the decimated sample rate and pitch
# only needs the fundamental to survive.
DECIM = 8

# Search range. The low end covers a 5-string bass low B (30.9 Hz); the high
# end clears a guitar's open high E (329.6 Hz) with room for a capo.
FMIN = 28.0
FMAX = 500.0

# YIN's aperiodicity threshold: the first period whose normalized difference
# drops below this wins, which is what keeps the detector off octave multiples.
YIN_THRESHOLD = 0.12
# Above this, the frame is not one steady pitch. Measured: a tone buried in
# wideband noise still scores under 0.08, while a window straddling two
# different notes -- what a window sees for one hop after a new string is
# plucked -- lands between 0.23 and 0.33.
REJECT_ABOVE = 0.20
# Default RMS gate, as a fraction of full scale.
DEFAULT_GATE = 0.004

PR_SET_PDEATHSIG = 1
# What the forked child exits with when it finds its parent already dead. Only
# the kernel sees it -- the parent that would have read it is gone.
EXIT_ORPHANED = 3


class Detector:
    """Turns windows of PCM into pitch readings."""

    def __init__(self, rate: int = RATE, window: int = WINDOW, decim: int = DECIM,
                 gate: float = DEFAULT_GATE) -> None:
        self.rate = rate
        self.window = window
        self.decim = decim
        self.gate = gate
        self.coarse_len = window // decim
        coarse_rate = rate / decim
        # Lag bounds follow from the frequency range, clamped so the coarse
        # difference function always has samples left to compare.
        self.coarse_min = max(2, int(coarse_rate / FMAX))
        self.coarse_max = min(self.coarse_len - 2, int(math.ceil(coarse_rate / FMIN)))

    # -- difference function -------------------------------------------------

    @staticmethod
    def _prefix_energy(x: array.array) -> list[float]:
        prefix = [0.0] * (len(x) + 1)
        total = 0.0
        for i, value in enumerate(x):
            total += value * value
            prefix[i + 1] = total
        return prefix

    @staticmethod
    def _difference(x: array.array, prefix: list[float], lag: int) -> float:
        """Squared difference at one lag.

        Expanded from sum((x[j] - x[j+lag])**2) into two energy terms and a dot
        product, so the only per-sample work left is math.sumprod -- a C loop.
        A Python-level loop here is what forces tuners like this into numpy.
        """
        n = len(x)
        head = memoryview(x)[0:n - lag]
        tail = memoryview(x)[lag:n]
        return prefix[n - lag] + (prefix[n] - prefix[lag]) - 2.0 * math.sumprod(head, tail)

    # -- stages -------------------------------------------------------------

    def _coarse_lag(self, x: array.array) -> tuple[int, float]:
        """Pick a period at the decimated rate. Returns (lag, aperiodicity)."""
        step = self.decim
        decimated = array.array('d', [
            math.fsum(memoryview(x)[i * step:(i + 1) * step]) for i in range(self.coarse_len)
        ])
        prefix = self._prefix_energy(decimated)

        # CMNDF needs every shorter lag to normalize by, so the whole range is
        # computed even though only coarse_min upward can be chosen.
        normalized = [math.inf] * (self.coarse_max + 2)
        running = 0.0
        for lag in range(1, self.coarse_max + 1):
            value = self._difference(decimated, prefix, lag)
            running += value
            normalized[lag] = value * lag / running if running > 0 else 1.0

        best = self.coarse_min
        for lag in range(self.coarse_min, self.coarse_max + 1):
            if normalized[lag] < YIN_THRESHOLD:
                # Descend to the bottom of this dip rather than taking its edge.
                while lag + 1 <= self.coarse_max and normalized[lag + 1] < normalized[lag]:
                    lag += 1
                return lag, normalized[lag]
            if normalized[lag] < normalized[best]:
                best = lag
        return best, normalized[best]

    def _refine_lag(self, x: array.array, coarse_lag: int) -> float:
        """Re-search at the full rate around the coarse estimate."""
        prefix = self._prefix_energy(x)
        centre = coarse_lag * self.decim
        # Decimation leaves the full-rate period uncertain by up to one
        # decimated sample in either direction.
        low = max(1, centre - self.decim)
        high = min(len(x) - 2, centre + self.decim)
        if low >= high:
            return float(centre)

        values = {lag: self._difference(x, prefix, lag) for lag in range(low, high + 1)}
        best = min(values, key=values.get)

        # Parabolic interpolation, skipped at the edges of the searched range
        # where one of the two neighbours is missing.
        if best <= low or best >= high:
            return float(best)
        before, here, after = values[best - 1], values[best], values[best + 1]
        denominator = before - 2.0 * here + after
        if denominator <= 0:
            return float(best)
        shift = 0.5 * (before - after) / denominator
        return float(best) + max(-1.0, min(1.0, shift))

    # -- entry point --------------------------------------------------------

    def analyze(self, frame: array.array) -> dict:
        n = len(frame)
        mean = math.fsum(frame) / n
        centred = array.array('d', [value - mean for value in frame])
        level = math.sqrt(math.sumprod(centred, centred) / n) / 32768.0
        reading = {"hz": 0.0, "confidence": 0.0, "level": round(level, 5), "source": "pw-cat"}
        if level < self.gate:
            return reading

        coarse_lag, aperiodicity = self._coarse_lag(centred)
        # Reported even when the frame is rejected: how far over the limit a
        # near miss was is the one number that explains a tuner showing
        # nothing while the level meter is clearly moving.
        reading["aperiodicity"] = round(aperiodicity, 3)
        if aperiodicity > REJECT_ABOVE:
            return reading

        lag = self._refine_lag(centred, coarse_lag)
        if lag <= 0:
            return reading
        hz = self.rate / lag
        if hz < FMIN or hz > FMAX:
            return reading

        reading["hz"] = round(hz, 3)
        reading["confidence"] = round(max(0.0, min(1.0, 1.0 - aperiodicity)), 3)
        return reading


# -- plumbing ---------------------------------------------------------------


class Smoother:
    """Median filter over the last few readings.

    Octave errors and half-period errors arrive as isolated frames, so a
    median removes them where an average would only smear them across
    neighbours. The cost is that a newly plucked string takes an extra hop or
    two to settle, which is what every hardware tuner does anyway.
    """

    def __init__(self, depth: int = 3) -> None:
        self.depth = depth
        self.history: list[dict] = []

    def push(self, reading: dict) -> dict:
        self.history.append(reading)
        if len(self.history) > self.depth:
            self.history.pop(0)
        # Report the frame holding the median pitch rather than a synthesised
        # average, so hz and confidence always describe the same window.
        chosen = sorted(self.history, key=lambda item: item["hz"])[len(self.history) // 2]
        # The level meter is the one thing that should not lag: it tells the
        # player whether the instrument is even reaching the input.
        return {**chosen, "level": reading["level"]}


def emit(reading: dict) -> None:
    try:
        sys.stdout.write(json.dumps(reading) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        raise SystemExit(0)


def read_exact(stream, count: int) -> bytes | None:
    """Read exactly count bytes, or None at end of stream."""
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_of(hz: float) -> tuple[str, float]:
    """Nearest note name and the deviation from it in cents."""
    midi = 69 + 12 * math.log(hz / 440.0, 2)
    nearest = round(midi)
    name = NOTE_NAMES[nearest % 12] + str(nearest // 12 - 1)
    return name, (midi - nearest) * 100.0


def run_stream(stream, detector: Detector, window: int = WINDOW, hop: int = HOP, sink=None) -> int:
    frame = array.array('d', [0.0] * window)
    samples = array.array('h')
    smoother = Smoother()
    write = sink if sink is not None else emit
    primed = False
    while True:
        block = read_exact(stream, hop * 2)
        if block is None:
            return 0 if primed else 1
        del samples[:]
        samples.frombytes(block)
        # Slide the window by one hop and append the new samples.
        frame = frame[hop:]
        frame.extend(array.array('d', samples))
        primed = True
        write(smoother.push(detector.analyze(frame)))


def die_with_parent(expected_parent: int) -> None:
    """Ask the kernel to kill this process when its parent dies.

    Runs in the forked child, before exec. Quickshell may SIGKILL the detector
    when the panel closes, in which case no cleanup code of ours runs, and
    without this pw-cat would survive as an open capture stream with no UI
    attached. So this is the mechanism that decides whether a microphone can
    outlive the panel, and neither of its two failure modes may be swallowed.

    If prctl fails there is no protection at all. Raising aborts the exec and
    Popen reports it to the parent, which then reports it to the panel: no
    capture at all is the right answer, because a capture stream we cannot
    guarantee to close is worse than a tuner that says it could not start.

    The second failure mode is a race, and it is the reason the parent is
    re-checked below. PR_SET_PDEATHSIG can only be armed here, after the fork,
    and it fires on the death of the parent *at the time it fires* -- so if the
    detector died in the window between the fork and this call, the signal that
    was just armed can never be delivered. The child would be reparented to
    init and keep the input open forever. Comparing the current parent against
    the pid the caller recorded before forking closes that window: either the
    parent is still the process we armed against, or it is already gone and
    this child must not exec at all.
    """
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")

    if os.getppid() != expected_parent:
        # Nothing will ever signal this process, so leave before exec rather
        # than opening a capture stream that cannot be closed. os._exit avoids
        # running the parent's atexit handlers in this forked copy.
        os._exit(EXIT_ORPHANED)


def capture(target: str, rate: int) -> subprocess.Popen:
    command = [
        "pw-cat", "--record", "-",
        "--raw",
        "--rate", str(rate),
        "--channels", "1",
        "--format", "s16",
        "--latency", "50ms",
    ]
    if target:
        command += ["--target", target]
    # Read in the parent: inside the child, getpid() is the child's own.
    parent = os.getpid()
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        preexec_fn=lambda: die_with_parent(parent),
    )


def print_meter(reading: dict) -> None:
    level = reading["level"]
    filled = int(min(1.0, math.sqrt(level * 4)) * 28)
    bar = "#" * filled + " " * (28 - filled)
    if reading["hz"] > 0:
        name, offset = note_of(reading["hz"])
        pitch = f"{name:<4} {offset:+6.1f}c  {reading['hz']:8.2f} Hz"
    else:
        pitch = f"{'--':<4} {'':>7}   {'':>8}   "
    # Aperiodicity is what the rejection threshold actually tests, so show it:
    # a note that will not register is usually a number just over the limit.
    if "aperiodicity" in reading:
        judgement = f"aper {reading['aperiodicity']:.2f}"
        if reading["hz"] <= 0:
            judgement += f" > {REJECT_ABOVE:.2f}, rejected"
    else:
        judgement = "below the level gate"
    sys.stdout.write(f"\r  [{bar}] {level:.4f}   {pitch}   {judgement:<28}")
    sys.stdout.flush()


def run_meter(target: str, rate: int, gate: float) -> int:
    print(f"Listening on: {target or 'the PipeWire default source'}")
    print("Play a note. Ctrl-C to stop.\n")
    try:
        recorder = capture(target, rate)
    except FileNotFoundError:
        print("pw-cat not found; install pipewire-audio", file=sys.stderr)
        return 1
    try:
        return run_stream(recorder.stdout, Detector(rate=rate, gate=gate), sink=print_meter)
    finally:
        print()
        if recorder.poll() is None:
            recorder.terminate()


def list_inputs() -> int:
    import shutil
    if shutil.which("pactl") is None:
        print("pactl not found; it ships with pipewire-pulse", file=sys.stderr)
        return 1
    listing = subprocess.run(["pactl", "list", "short", "sources"],
                             capture_output=True, text=True)
    default = subprocess.run(["pactl", "get-default-source"],
                             capture_output=True, text=True).stdout.strip()
    print("Pass one of these to --target, or make it the system default with")
    print("  pactl set-default-source <name>\n")
    for line in listing.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        name = fields[1]
        # A .monitor source records what a sink is playing, not an instrument.
        kind = "monitor" if name.endswith(".monitor") else "input"
        marker = "  <- current default" if name == default else ""
        print(f"  [{kind}] {name}{marker}")
    return 0


def run_capture(target: str, rate: int, gate: float) -> int:
    try:
        recorder = capture(target, rate)
    except FileNotFoundError:
        emit({"hz": 0.0, "confidence": 0.0, "level": 0.0, "source": "pw-cat",
              "error": "pw-cat not found; install pipewire-audio"})
        return 1
    except (OSError, subprocess.SubprocessError):
        # die_with_parent refused to arm, so capture never started. Reported
        # rather than retried: silently recording without the guarantee that
        # the stream closes with the panel is the one outcome to avoid.
        emit({"hz": 0.0, "confidence": 0.0, "level": 0.0, "source": "pw-cat",
              "error": "could not guarantee pw-cat exits with the panel; not recording"})
        return 1
    try:
        status = run_stream(recorder.stdout, Detector(rate=rate, gate=gate))
        if status != 0:
            emit({"hz": 0.0, "confidence": 0.0, "level": 0.0, "source": "pw-cat",
                  "error": "no audio from pw-cat; check the input device"})
        return status
    finally:
        # Belt and braces: this covers an orderly exit, PR_SET_PDEATHSIG covers
        # a SIGKILL, and a SIGPIPE on pw-cat's next write covers the rest.
        if recorder.poll() is None:
            recorder.terminate()
            try:
                recorder.wait(timeout=1)
            except subprocess.TimeoutExpired:
                recorder.kill()


# -- self test --------------------------------------------------------------


def tone(hz: float, rate: int, count: int, harmonics: int = 3) -> array.array:
    """A plucked-string-ish tone: fundamental plus decaying harmonics."""
    samples = array.array('d', [0.0] * count)
    for index in range(count):
        value = 0.0
        for harmonic in range(1, harmonics + 1):
            value += (0.7 ** (harmonic - 1)) * math.sin(2 * math.pi * hz * harmonic * index / rate)
        samples[index] = value * 8000.0
    return samples


def cents(measured: float, expected: float) -> float:
    return 1200.0 * math.log(measured / expected) / math.log(2.0)


def noise_into(samples: array.array, amplitude: float, seed: int = 999) -> array.array:
    """Add deterministic wideband noise to a tone."""
    state = seed
    for index in range(len(samples)):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        samples[index] += (state / 0x3FFFFFFF - 1.0) * amplitude
    return samples


def selftest() -> int:
    import time
    detector = Detector()
    # Open strings that matter: 5-string bass low B, 4-string bass E, guitar
    # low E and A, guitar open high E.
    cases = [30.87, 41.20, 82.41, 110.00, 146.83, 196.00, 246.94, 329.63]
    failures = 0
    print(f"{'target Hz':>10}  {'measured':>10}  {'cents':>7}  {'conf':>5}")
    for expected in cases:
        reading = detector.analyze(tone(expected, RATE, WINDOW))
        if reading["hz"] <= 0:
            print(f"{expected:>10.2f}  {'no pitch':>10}  {'--':>7}  {'--':>5}  FAIL")
            failures += 1
            continue
        error = cents(reading["hz"], expected)
        verdict = "ok" if abs(error) <= 2.0 else "FAIL"
        if verdict == "FAIL":
            failures += 1
        print(f"{expected:>10.2f}  {reading['hz']:>10.3f}  {error:>+7.2f}  "
              f"{reading['confidence']:>5.2f}  {verdict}")

    # A clean synthetic tone is an easy case. This guards the harder one: a
    # note buried in wideband noise still has to land within a few cents.
    for expected in (41.20, 82.41, 196.00):
        reading = detector.analyze(noise_into(tone(expected, RATE, WINDOW), 2000.0))
        if reading["hz"] <= 0:
            print(f"{expected:>10.2f}  {'no pitch':>10}  {'--':>7}  {'--':>5}  FAIL (noisy)")
            failures += 1
            continue
        error = cents(reading["hz"], expected)
        verdict = "ok" if abs(error) <= 5.0 else "FAIL"
        if verdict == "FAIL":
            failures += 1
        print(f"{expected:>10.2f}  {reading['hz']:>10.3f}  {error:>+7.2f}  "
              f"{reading['confidence']:>5.2f}  {verdict} (noisy)")

    silence = detector.analyze(array.array('d', [0.0] * WINDOW))
    if silence["hz"] != 0.0:
        print(f"silence: expected no pitch, got {silence['hz']}  FAIL")
        failures += 1
    else:
        print("   silence    no pitch       --     --  ok")

    # Wideband noise must not read as a pitch, or the panel will show a note
    # for an empty room.
    state = 12345
    noise = array.array('d', [0.0] * WINDOW)
    for index in range(WINDOW):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        noise[index] = (state / 0x3FFFFFFF - 1.0) * 6000.0
    noisy = detector.analyze(noise)
    if noisy["hz"] != 0.0:
        print(f"noise: expected no pitch, got {noisy['hz']:.2f} Hz  FAIL")
        failures += 1
    else:
        print("     noise    no pitch       --     --  ok")

    frame = tone(82.41, RATE, WINDOW)
    started = time.perf_counter()
    rounds = 100
    for _ in range(rounds):
        detector.analyze(frame)
    per_frame = (time.perf_counter() - started) / rounds * 1000.0
    budget = HOP / RATE * 1000.0
    print(f"\n{per_frame:.2f} ms per frame, {budget:.1f} ms budget "
          f"({per_frame / budget * 100:.1f}% of one core)")
    if per_frame > budget:
        print("FAIL: detection is slower than real time")
        failures += 1

    print("\nall checks passed" if failures == 0 else f"\n{failures} check(s) failed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pitch detector for the Omarchy tuner plugin.")
    parser.add_argument("--target", default=os.environ.get("TUNER_TARGET", ""),
                        help="PipeWire node name or serial to record from (default: system default)")
    parser.add_argument("--rate", type=int, default=RATE, help="capture sample rate")
    parser.add_argument("--gate", type=float, default=DEFAULT_GATE,
                        help="RMS gate as a fraction of full scale")
    parser.add_argument("--stdin", action="store_true",
                        help="read raw s16 mono PCM from stdin instead of pw-cat")
    parser.add_argument("--selftest", action="store_true",
                        help="check the detector against synthetic tones and exit")
    parser.add_argument("--meter", action="store_true",
                        help="show a live level and pitch readout in the terminal")
    parser.add_argument("--list-inputs", action="store_true",
                        help="list PipeWire sources that --target accepts")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    if args.selftest:
        return selftest()
    if args.list_inputs:
        return list_inputs()
    if args.meter:
        return run_meter(args.target, args.rate, args.gate)
    if args.stdin:
        return run_stream(sys.stdin.buffer, Detector(rate=args.rate, gate=args.gate))
    return run_capture(args.target, args.rate, args.gate)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)

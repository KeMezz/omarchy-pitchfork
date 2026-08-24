"""Regression tests for the stdlib-only pitch detector.

Run with:
    python3 -m unittest discover -s tests -p '*_test.py'
"""

from __future__ import annotations

import array
import errno
import importlib.util
import io
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
DETECTOR_PATH = REPOSITORY / "scripts" / "pitch-detect.py"
SPEC = importlib.util.spec_from_file_location("pitch_detect", DETECTOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {DETECTOR_PATH}")
pitch_detect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pitch_detect)


# The unique notes produced by every currently shipped instrument/reference
# combination in Tunings.js. Keeping the names explicit makes additions to the
# product's tuning range an intentional addition to the detector contract too.
SHIPPED_NOTES = (
    "A0", "A#0", "B0", "D1", "D#1", "E1", "G1", "G#1", "A1", "A#1",
    "B1", "C2", "C#2", "D2", "D#2", "E2", "F2", "F#2", "G2", "G#2",
    "A2", "A#2", "B2", "C3", "C#3", "D3", "F3", "F#3", "G3", "A3",
    "A#3", "B3", "D4", "D#4", "E4",
)
PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def frequency_of(note: str) -> float:
    pitch_class = note[:-1]
    octave = int(note[-1])
    midi = (octave + 1) * 12 + PITCH_CLASSES.index(pitch_class)
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def frequency_of_midi(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def name_of_midi(midi: int) -> str:
    return PITCH_CLASSES[midi % 12] + str(midi // 12 - 1)


def cents_between(measured: float, expected: float) -> float:
    return 1200.0 * math.log2(measured / expected)


def samples_for(hz: float, count: int, *, phase: float = 0.37,
                harmonics: int = 3) -> array.array:
    """Return one continuous, plucked-string-like waveform."""
    samples = array.array("d")
    for index in range(count):
        angle = 2.0 * math.pi * hz * index / pitch_detect.RATE + phase
        value = math.fsum(
            0.7 ** (harmonic - 1) * math.sin(angle * harmonic)
            for harmonic in range(1, harmonics + 1)
        )
        samples.append(value * 7000.0)
    return samples


def pcm_for(hz: float, count: int, *, phase: float = 0.37,
            harmonics: int = 3) -> bytes:
    floating = samples_for(hz, count, phase=phase, harmonics=harmonics)
    pcm = array.array("h", (round(value) for value in floating))
    return pcm.tobytes()


class DetectorRegressionTests(unittest.TestCase):
    def assert_pitch(self, reading: dict, expected: float, *, cents: float = 2.0) -> None:
        self.assertGreater(reading["hz"], 0.0, reading)
        error = cents_between(reading["hz"], expected)
        self.assertLessEqual(abs(error), cents, f"{reading} is {error:+.2f} cents from {expected}")

    def test_entire_chromatic_semitone_grid_survives_continuous_pcm_hops(self) -> None:
        detector = pitch_detect.Detector()
        sample_count = pitch_detect.HOP * 4
        chromatic_midis = tuple(
            midi for midi in range(128)
            if pitch_detect.FMIN <= frequency_of_midi(midi) <= pitch_detect.FMAX
        )
        chromatic_notes = {name_of_midi(midi) for midi in chromatic_midis}
        self.assertLessEqual(set(SHIPPED_NOTES), chromatic_notes)

        # Chromatic mode serves the detector's full range, not only the open
        # strings in Tunings.js. Sweep every semitone through real sliding PCM
        # windows at multiple phases and harmonic densities; DECIM=4 used to
        # pass every shipped string yet report A#4 as A#3 in this exact sweep.
        for midi in chromatic_midis:
            expected = frequency_of_midi(midi)
            note = name_of_midi(midi)
            for harmonics in (1, 3, 6):
                for phase in (0.13, 1.17):
                    with self.subTest(note=note, harmonics=harmonics, phase=phase):
                        readings: list[dict] = []
                        status = pitch_detect.run_stream(
                            io.BytesIO(pcm_for(
                                expected,
                                sample_count,
                                phase=phase,
                                harmonics=harmonics,
                            )),
                            detector,
                            sink=readings.append,
                        )
                        self.assertEqual(status, 0)
                        self.assertEqual(len(readings), sample_count // pitch_detect.HOP)
                        # This is deliberately the last sliding window, not a
                        # frame regenerated at phase zero. It catches
                        # phase-dependent coarse errors and exercises the
                        # three-reading smoother as deployed.
                        self.assert_pitch(readings[-1], expected)

    def test_coarse_stage_does_not_choose_octaves_for_half_down_guitar(self) -> None:
        detector = pitch_detect.Detector()
        for note in ("A#3", "D#4"):
            expected = frequency_of(note)
            for phase in (0.0, 0.19, 0.73, 1.41, 2.63):
                with self.subTest(note=note, phase=phase):
                    reading = detector.analyze(samples_for(
                        expected,
                        pitch_detect.WINDOW,
                        phase=phase,
                        harmonics=6,
                    ))
                    self.assert_pitch(reading, expected)

    def test_range_leaves_a_whole_tone_around_outer_shipped_targets(self) -> None:
        low_margin = frequency_of("A0") * 2.0 ** (-2.0 / 12.0)
        high_margin = frequency_of("E4") * 2.0 ** (2.0 / 12.0)
        self.assertLess(pitch_detect.FMIN, low_margin)
        self.assertGreater(pitch_detect.FMAX, high_margin)

        detector = pitch_detect.Detector()
        self.assert_pitch(detector.analyze(samples_for(low_margin, pitch_detect.WINDOW)),
                          low_margin)
        self.assert_pitch(detector.analyze(samples_for(high_margin, pitch_detect.WINDOW)),
                          high_margin)

    def test_nearby_tones_outside_search_range_are_not_reported(self) -> None:
        detector = pitch_detect.Detector()
        below = detector.analyze(samples_for(pitch_detect.FMIN - 0.25,
                                             pitch_detect.WINDOW))
        above = detector.analyze(samples_for(pitch_detect.FMAX + 1.0,
                                             pitch_detect.WINDOW,
                                             harmonics=1))
        self.assertEqual(below["hz"], 0.0, below)
        self.assertEqual(above["hz"], 0.0, above)

    def test_meter_only_claims_threshold_rejection_when_threshold_was_crossed(self) -> None:
        base = {"hz": 0.0, "confidence": 0.0, "level": 0.1, "source": "pw-cat"}
        output = io.StringIO()
        with mock.patch.object(pitch_detect.sys, "stdout", output):
            pitch_detect.print_meter({**base, "aperiodicity": 0.05})
        self.assertIn("no in-range pitch", output.getvalue())
        self.assertNotIn(f"> {pitch_detect.REJECT_ABOVE:.2f}", output.getvalue())

        output = io.StringIO()
        with mock.patch.object(pitch_detect.sys, "stdout", output):
            pitch_detect.print_meter({**base, "aperiodicity": pitch_detect.REJECT_ABOVE + 0.01})
        self.assertIn(f"> {pitch_detect.REJECT_ABOVE:.2f}, rejected", output.getvalue())


class CompletedRecorder:
    """Small Popen stand-in whose stdout closes after one valid hop."""

    def __init__(self, status: int, trailing: bytes = b"") -> None:
        self.stdout = io.BytesIO(bytes(pitch_detect.HOP * 2) + trailing)
        self.status = status
        self.returncode: int | None = None
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = self.status
        return self.status

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -signal.SIGTERM

    def kill(self) -> None:
        self.returncode = -signal.SIGKILL


class CaptureExitTests(unittest.TestCase):
    def test_nonzero_pw_cat_exit_after_audio_is_not_reported_as_success(self) -> None:
        recorder = CompletedRecorder(7)
        emitted: list[dict] = []
        with mock.patch.object(pitch_detect, "capture", return_value=recorder), \
                mock.patch.object(pitch_detect, "emit", side_effect=emitted.append):
            status = pitch_detect.run_capture("test-input", pitch_detect.RATE,
                                              pitch_detect.DEFAULT_GATE)

        self.assertEqual(status, 1)
        self.assertFalse(recorder.terminated)
        self.assertTrue(any("status 7" in item.get("error", "") for item in emitted), emitted)

    def test_zero_pw_cat_exit_is_still_an_error_while_panel_is_open(self) -> None:
        # A complete final hop and a partial one are both unexpected EOF. The
        # recorder is supposed to remain alive until the detector is stopped.
        for trailing in (b"", b"\x00\x00"):
            with self.subTest(partial=bool(trailing)):
                recorder = CompletedRecorder(0, trailing)
                emitted: list[dict] = []
                with mock.patch.object(pitch_detect, "capture", return_value=recorder), \
                        mock.patch.object(pitch_detect, "emit", side_effect=emitted.append):
                    status = pitch_detect.run_capture("test-input", pitch_detect.RATE,
                                                      pitch_detect.DEFAULT_GATE)

                self.assertEqual(status, 1)
                self.assertTrue(any("audio stream ended" in item.get("error", "")
                                    for item in emitted), emitted)


class ParentDeathGuardTests(unittest.TestCase):
    """Pins the two failures reported in marketplace issue #1887."""

    class FakeLibc:
        def __init__(self, result: int) -> None:
            self.result = result
            self.calls: list[tuple[int, signal.Signals]] = []

        def prctl(self, option: int, death_signal: signal.Signals) -> int:
            self.calls.append((option, death_signal))
            return self.result

    def test_prctl_failure_is_raised_before_parent_check(self) -> None:
        libc = self.FakeLibc(-1)
        with mock.patch.object(pitch_detect.ctypes, "CDLL", return_value=libc), \
                mock.patch.object(pitch_detect.ctypes, "get_errno", return_value=errno.EPERM), \
                mock.patch.object(pitch_detect.os, "getppid") as getppid:
            with self.assertRaises(OSError) as raised:
                pitch_detect.die_with_parent(os.getpid())

        self.assertEqual(raised.exception.errno, errno.EPERM)
        self.assertEqual(libc.calls,
                         [(pitch_detect.PR_SET_PDEATHSIG, signal.SIGTERM)])
        getppid.assert_not_called()

    def test_preexec_failure_propagates_through_popen(self) -> None:
        failure = OSError(errno.EPERM, "forced PR_SET_PDEATHSIG failure")
        with mock.patch.object(pitch_detect, "die_with_parent", side_effect=failure):
            with self.assertRaises(subprocess.SubprocessError):
                pitch_detect.capture("", pitch_detect.RATE)

    def test_changed_parent_exits_before_exec(self) -> None:
        libc = self.FakeLibc(0)
        expected_parent = os.getpid()

        class ExitCalled(Exception):
            pass

        def refuse_exec(status: int) -> None:
            raise ExitCalled(status)

        with mock.patch.object(pitch_detect.ctypes, "CDLL", return_value=libc), \
                mock.patch.object(pitch_detect.os, "getppid", return_value=expected_parent + 1), \
                mock.patch.object(pitch_detect.os, "_exit", side_effect=refuse_exec):
            with self.assertRaises(ExitCalled) as raised:
                pitch_detect.die_with_parent(expected_parent)

        self.assertEqual(raised.exception.args, (pitch_detect.EXIT_ORPHANED,))

    @unittest.skipUnless(sys.platform.startswith("linux"), "PR_SET_PDEATHSIG is Linux-specific")
    def test_changed_parent_prevents_guarded_program_from_execing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "exec-ran"
            child = subprocess.Popen(
                [sys.executable, "-c",
                 f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"],
                preexec_fn=lambda: pitch_detect.die_with_parent(-1),
            )
            self.assertEqual(child.wait(timeout=2), pitch_detect.EXIT_ORPHANED)
            self.assertFalse(marker.exists())

    @staticmethod
    def _process_is_active(pid: int) -> bool:
        try:
            state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
        except FileNotFoundError:
            return False
        # A zombie has already stopped executing and cannot hold an audio
        # stream; PID 1 may reap it a moment later in a test container.
        return state not in {"X", "Z"}

    @unittest.skipUnless(sys.platform.startswith("linux"), "PR_SET_PDEATHSIG is Linux-specific")
    def test_guarded_child_dies_when_its_parent_is_sigkilled(self) -> None:
        helper_source = textwrap.dedent("""
            import importlib.util
            import os
            import signal
            import subprocess
            import sys

            spec = importlib.util.spec_from_file_location("pitch_detect_guard", sys.argv[1])
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            parent = os.getpid()
            child = subprocess.Popen(
                [sys.executable, "-c", "import signal; signal.pause()"],
                preexec_fn=lambda: module.die_with_parent(parent),
            )
            print(child.pid, flush=True)
            signal.pause()
        """)
        helper = subprocess.Popen(
            [sys.executable, "-c", helper_source, str(DETECTOR_PATH)],
            stdout=subprocess.PIPE,
            text=True,
        )
        child_pid: int | None = None
        try:
            assert helper.stdout is not None
            announced = helper.stdout.readline().strip()
            self.assertTrue(announced, "guard helper exited before announcing its child")
            child_pid = int(announced)
            self.assertTrue(self._process_is_active(child_pid))

            helper.kill()
            helper.wait(timeout=2)
            deadline = time.monotonic() + 2.0
            while self._process_is_active(child_pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(self._process_is_active(child_pid),
                             "guarded child survived its parent's SIGKILL")
        finally:
            if helper.poll() is None:
                helper.kill()
                helper.wait(timeout=2)
            if child_pid is not None and self._process_is_active(child_pid):
                os.kill(child_pid, signal.SIGKILL)
            if helper.stdout is not None:
                helper.stdout.close()


if __name__ == "__main__":
    unittest.main()

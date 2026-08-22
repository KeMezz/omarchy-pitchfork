#!/usr/bin/env python3
"""Pitch detector for the Omarchy tuner plugin.

PLACEHOLDER. This emits synthetic readings so the plugin's process plumbing
can be exercised end to end. It does not open an audio device, and it never
touches the microphone. Replacing the body of `readings()` with real detection
is the next task; the line protocol below is the part that should stay stable.

Protocol: one JSON object per line on stdout, flushed immediately so the
shell's SplitParser sees each reading as it happens.

    {"hz": 82.41, "confidence": 0.93, "source": "stub"}

    hz          detected fundamental in Hz, or 0.0 when nothing is playing
    confidence  0.0-1.0; the UI may ignore low-confidence readings
    source      detector identity, so the panel can label placeholder data
    error       optional human-readable problem; hz should be 0.0 alongside it

Anything written to stderr is diagnostic only and is not part of the protocol.
"""

from __future__ import annotations

import json
import math
import signal
import sys
import time

# Open E on a 4-string bass. A tuner that starts at a plausible pitch is
# easier to eyeball than one that starts at silence.
BASE_HZ = 82.4069
# Full sweep width in cents. Wide enough to leave the in-tune band in both
# directions so the needle and the colour change are both visible.
SWEEP_CENTS = 35.0
SWEEP_PERIOD_S = 6.0
INTERVAL_S = 0.1


def emit(reading: dict) -> None:
    sys.stdout.write(json.dumps(reading) + "\n")
    sys.stdout.flush()


def readings() -> None:
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        cents = SWEEP_CENTS * math.sin(2 * math.pi * elapsed / SWEEP_PERIOD_S)
        emit({
            "hz": BASE_HZ * (2 ** (cents / 1200.0)),
            "confidence": 0.9,
            "source": "stub",
        })
        time.sleep(INTERVAL_S)


def main() -> int:
    # The shell terminates the detector by killing the process when the panel
    # closes, and stops reading stdout at the same moment. Neither is an error.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        readings()
    except (KeyboardInterrupt, BrokenPipeError):
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

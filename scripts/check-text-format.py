#!/usr/bin/env python3
"""Fail if a Text element does not pin its textFormat.

QML's Text defaults to Text.AutoText, which sniffs its content and renders
anything that looks like markup as rich text -- and rich text loads the
resources it references, from inside the long-lived shell process. This panel
renders strings it does not author: PipeWire device names and descriptions, the
input id restored from disk, and the detector's own error output. Any of those
reaching an AutoText sink is a remote fetch triggered by whatever named the
device.

Text.PlainText is the fix, and it is worth enforcing on *every* Text rather
than only the ones that currently carry outside data: which strings are
external changes with each edit, and a rule a reviewer can check by grep does
not.
"""
from __future__ import annotations

import pathlib
import re
import sys

OPENING = re.compile(r"^(\s*)Text \{\s*$")


def offenders(path: pathlib.Path) -> list[int]:
    lines = path.read_text().splitlines()
    missing = []
    for index, line in enumerate(lines):
        match = OPENING.match(line)
        if not match:
            continue

        # The element's own properties are the lines indented past its brace,
        # up to the first line that returns to the brace's indent or less.
        indent = len(match.group(1))
        body = []
        for following in lines[index + 1:]:
            if following.strip() and (len(following) - len(following.lstrip())) <= indent:
                break

            body.append(following)
        if not any(re.match(r"\s*textFormat\s*:", entry) for entry in body):
            missing.append(index + 1)
    return missing


def main(argv: list[str]) -> int:
    failed = False
    for name in argv:
        path = pathlib.Path(name)
        for line in offenders(path):
            print(f"{path}:{line}: Text without an explicit textFormat "
                  f"(use Text.PlainText; AutoText renders markup and fetches "
                  f"what it references)", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Fail if a QML Text element does not pin ``Text.PlainText``.

QML's Text defaults to Text.AutoText, which sniffs its content and renders
anything that looks like markup as rich text -- and rich text loads the
resources it references, from inside the long-lived shell process. This panel
renders strings it does not author: PipeWire device names and descriptions, the
input id restored from disk, and the detector's own error output. Any of those
reaching an AutoText sink could cause a network request chosen by the string's
author.

The check deliberately enforces a canonical header instead of trying to parse
JavaScript embedded in QML: apart from QML's special ``id`` member,
``textFormat`` must be the first member of every ``Text {`` or
``Text on property {`` declaration and its value must be exactly
``Text.PlainText``. Searching decoded QML identifiers independently means a
regex, template literal, comment, or nested brace can at worst create an extra
fail-closed candidate; it can never hide a real Text sink or lend it a binding
from somewhere else. This keeps the portable CI check independent of a
QML/JavaScript parser.
"""
from __future__ import annotations

import pathlib
import sys

LINE_TERMINATORS = {"\r", "\n", "\u2028", "\u2029"}
WORD_CONTINUATIONS = {"as", "in", "instanceof"}
DECLARATIVE_MEMBERS = {
    "readonly", "required", "default", "property", "signal", "function",
    "enum", "component",
}


def is_layout(char: str) -> bool:
    """QML/JavaScript whitespace, including BOM and Unicode separators."""
    return char.isspace() or char == "\ufeff"


def skip_layout(source: str, index: int) -> tuple[int, bool]:
    """Skip whitespace/comments and report whether a line boundary occurred."""
    saw_newline = False
    while index < len(source):
        if is_layout(source[index]):
            saw_newline = saw_newline or source[index] in LINE_TERMINATORS
            index += 1
            continue
        if source.startswith("//", index):
            newline = index + 2
            while newline < len(source) and source[newline] not in LINE_TERMINATORS:
                newline += 1
            if newline >= len(source):
                return len(source), saw_newline
            saw_newline = True
            index = newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                return len(source), saw_newline
            saw_newline = saw_newline or any(
                char in LINE_TERMINATORS for char in source[index:end + 2]
            )
            index = end + 2
            continue
        break
    return index, saw_newline


def unicode_escape(source: str, index: int) -> tuple[int, str] | None:
    if not source.startswith("\\u", index):
        return None
    cursor = index + 2
    if cursor < len(source) and source[cursor] == "{":
        end = source.find("}", cursor + 1)
        digits = source[cursor + 1:end] if end >= 0 else ""
        if not (1 <= len(digits) <= 6):
            return None
        cursor = end + 1
    else:
        digits = source[cursor:cursor + 4]
        if len(digits) != 4:
            return None
        cursor += 4
    if not all(char in "0123456789abcdefABCDEF" for char in digits):
        return None
    value = int(digits, 16)
    if value > 0x10FFFF:
        return None
    return cursor, chr(value)


def identifier_at(source: str, index: int) -> tuple[int, str] | None:
    """Decode one complete QML identifier, including Unicode escapes."""
    decoded: list[str] = []
    cursor = index
    first = True
    while cursor < len(source):
        escaped = unicode_escape(source, cursor)
        if escaped is not None:
            end, char = escaped
        else:
            char = source[cursor]
            end = cursor + 1

        if first:
            valid = char in "_$" or char.isidentifier()
        else:
            valid = (
                char in "_$\u200c\u200d"
                or char.isidentifier()
                or ("A" + char).isidentifier()
            )
        if not valid:
            break
        decoded.append(char)
        cursor = end
        first = False

    return (cursor, "".join(decoded)) if decoded else None


def identifiers(source: str):
    """Yield non-overlapping raw spans and decoded complete identifiers."""
    index = 0
    while index < len(source):
        identifier = identifier_at(source, index)
        if identifier is None:
            index += 1
            continue
        end, value = identifier
        yield index, end, value
        index = end


def opening_after_text(source: str, text_end: int) -> int | None:
    """Return the brace end for `Text {` and QML's `Text on target {`."""
    cursor, _ = skip_layout(source, text_end)
    if cursor < len(source) and source[cursor] == "{":
        return cursor + 1

    # Object-on-property syntax is used by QML value-source/interceptor types.
    # It is still an object declaration and must not bypass the Text policy.
    if cursor == text_end:
        return None
    on_identifier = identifier_at(source, cursor)
    if on_identifier is None or on_identifier[1] != "on":
        return None
    after_on = on_identifier[0]
    target, _ = skip_layout(source, after_on)
    if target == after_on:
        return None
    identifier = identifier_at(source, target)
    if identifier is None:
        return None
    cursor = identifier[0]
    while True:
        dot, _ = skip_layout(source, cursor)
        if dot >= len(source) or source[dot] != ".":
            cursor = dot
            break
        name, _ = skip_layout(source, dot + 1)
        identifier = identifier_at(source, name)
        if identifier is None:
            return None
        cursor = identifier[0]
    return cursor + 1 if cursor < len(source) and source[cursor] == "{" else None


def member_start(source: str, index: int) -> bool:
    """Recognise the start of the QML member following the policy binding."""
    if index < len(source) and source[index] == "}":
        return True
    identifier = identifier_at(source, index)
    if identifier is None or identifier[1] in WORD_CONTINUATIONS:
        return False
    cursor, value = identifier
    if value in DECLARATIVE_MEMBERS:
        return True

    while True:
        cursor, _ = skip_layout(source, cursor)
        if cursor < len(source) and source[cursor] in ":{":
            return True
        if cursor < len(source) and source[cursor] == ".":
            name, _ = skip_layout(source, cursor + 1)
            identifier = identifier_at(source, name)
            if identifier is None:
                return False
            cursor = identifier[0]
            continue

        on_identifier = identifier_at(source, cursor)
        if on_identifier is None or on_identifier[1] != "on":
            return False
        target, _ = skip_layout(source, on_identifier[0])
        if target == on_identifier[0]:
            return False
        identifier = identifier_at(source, target)
        if identifier is None:
            return False
        cursor = identifier[0]
        while True:
            dot, _ = skip_layout(source, cursor)
            if dot >= len(source) or source[dot] != ".":
                cursor = dot
                break
            name, _ = skip_layout(source, dot + 1)
            identifier = identifier_at(source, name)
            if identifier is None:
                return False
            cursor = identifier[0]
        return cursor < len(source) and source[cursor] == "{"


def exact_header(source: str, opening_end: int) -> set[int] | None:
    """Return allowed identifier positions after proving the exact header."""
    allowed: set[int] = set()
    cursor, _ = skip_layout(source, opening_end)
    member_start_index = cursor
    member = identifier_at(source, cursor)
    if member is None:
        return None

    if member[1] == "id":
        cursor, _ = skip_layout(source, member[0])
        if cursor >= len(source) or source[cursor] != ":":
            return None
        id_start, _ = skip_layout(source, cursor + 1)
        id_value = identifier_at(source, id_start)
        if id_value is None:
            return None
        if id_value[1] == "textFormat":
            allowed.add(id_start)
        cursor, saw_newline = skip_layout(source, id_value[0])
        if cursor < len(source) and source[cursor] == ";":
            cursor, _ = skip_layout(source, cursor + 1)
        elif not saw_newline:
            return None
        member_start_index = cursor
        member = identifier_at(source, cursor)
        if member is None:
            return None

    if member[1] != "textFormat":
        return None
    allowed.add(member_start_index)
    cursor, _ = skip_layout(source, member[0])
    if cursor >= len(source) or source[cursor] != ":":
        return None

    text_start, _ = skip_layout(source, cursor + 1)
    text_type = identifier_at(source, text_start)
    if text_type is None or text_type[1] != "Text":
        return None
    cursor, _ = skip_layout(source, text_type[0])
    if cursor >= len(source) or source[cursor] != ".":
        return None
    plain_start, _ = skip_layout(source, cursor + 1)
    plain = identifier_at(source, plain_start)
    if plain is None or plain[1] != "PlainText":
        return None

    cursor, saw_newline = skip_layout(source, plain[0])
    if cursor < len(source) and source[cursor] in ";}":
        return allowed
    if not saw_newline or not member_start(source, cursor):
        return None
    return allowed


def line_number(source: str, index: int) -> int:
    line = 1
    cursor = 0
    while cursor < index:
        char = source[cursor]
        if char == "\r":
            line += 1
            cursor += 2 if cursor + 1 < index and source[cursor + 1] == "\n" else 1
            continue
        if char in {"\n", "\u2028", "\u2029"}:
            line += 1
        cursor += 1
    return line


def offender_lines(source: str) -> list[int]:
    """Return every noncanonical Text declaration or policy mutation line."""
    violations: set[int] = set()
    allowed_occurrences: set[int] = set()
    words = list(identifiers(source))

    for start, end, value in words:
        if value != "Text":
            continue
        opening_end = opening_after_text(source, end)
        if opening_end is None:
            continue
        header = exact_header(source, opening_end)
        if header is None:
            violations.add(line_number(source, start))
            continue
        allowed_occurrences.update(header)

    # A safe initial binding is not enough if Component.onCompleted,
    # PropertyChanges, Binding, or direct assignment later restores AutoText.
    # Reject every direct textFormat occurrence outside a canonical Text header
    # (including quoted Binding property names). This is an accidental-
    # regression guard, not an interpreter for deliberately computed names.
    for start, _end, value in words:
        if value == "textFormat" and start not in allowed_occurrences:
            violations.add(line_number(source, start))

    return sorted(violations)


def offenders(path: pathlib.Path) -> list[int]:
    return offender_lines(path.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    failed = False
    for name in argv:
        path = pathlib.Path(name)
        for line in offenders(path):
            print(
                f"{path}:{line}: every Text must use the canonical exact "
                f"textFormat: Text.PlainText header with no direct override "
                f"(AutoText renders markup and fetches referenced resources)",
                file=sys.stderr,
            )
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

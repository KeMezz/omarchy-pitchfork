"""Regression tests for the QML sink reported in marketplace issue #1887."""
from __future__ import annotations

import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_text_format", ROOT / "scripts" / "check-text-format.py"
)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class TextFormatLintTests(unittest.TestCase):
    def assert_offenders(self, source: str, expected: list[int]) -> None:
        self.assertEqual(CHECK.offender_lines(source), expected)

    def assert_contains_offenders(self, source: str, expected: list[int]) -> None:
        actual = CHECK.offender_lines(source)
        for line in expected:
            self.assertIn(line, actual, actual)

    def test_accepts_multiline_and_inline_plain_text(self) -> None:
        self.assert_offenders(
            """Text {
    textFormat: Text.PlainText
    text: externalName
}
Text { textFormat: Text.PlainText; text: detectorError }
""",
            [],
        )

    def test_rejects_multiline_and_inline_text_without_binding(self) -> None:
        self.assert_offenders(
            """Text {
    text: externalName
}
Item { Text { text: detectorError } }
""",
            [1, 4],
        )

    def test_rejects_auto_text_and_rich_text(self) -> None:
        self.assert_offenders(
            """Text { textFormat: Text.AutoText }
Text { textFormat: Text.RichText }
""",
            [1, 2],
        )

    def test_plain_text_must_be_the_first_non_id_member(self) -> None:
        self.assert_offenders(
            """Text { text: externalName; textFormat: Text.PlainText }
Text {
    property string unsafeOrder: "before the policy"
    textFormat: Text.PlainText
}
Text {
    id: qmlCanonicalId

    textFormat: Text.PlainText
}
Text { textFormat: Text.PlainText; text: externalName }
""",
            [1, 2, 4],
        )

    def test_rejects_expression_that_only_starts_with_plain_text(self) -> None:
        self.assert_contains_offenders(
            """Text { textFormat: Text.PlainText || Text.AutoText }
Text {
    textFormat: Text.PlainText
        || Text.RichText
}
""",
            [1, 2],
        )

        self.assert_contains_offenders(
            """Text {
    textFormat: Text.PlainText
        in [Text.AutoText] ? Text.RichText : Text.PlainText
}
Text {
    textFormat: Text.PlainText
        instanceof Number ? Text.RichText : Text.AutoText
}
""",
            [1, 5],
        )

    def test_regex_literal_cannot_supply_policy_tokens_or_braces(self) -> None:
        self.assert_contains_offenders(
            r"""Text {
    property var example: /textFormat: Text.PlainText|Text [{}]/
    text: externalName
}
""",
            [1],
        )

    def test_statement_regex_cannot_escape_the_parent_text(self) -> None:
        fake_policy = r"/}textFormat: Text.PlainText;/"
        self.assert_contains_offenders(
            f"""Text {{
    text: externalName
    Component.onCompleted: {{
        if (okay) work(); else {fake_policy}.test("x")
    }}
}}
""",
            [1],
        )

    def test_regex_after_optional_catch_and_operators_cannot_hide_policy(self) -> None:
        fake_policy = r"/}textFormat: Text.PlainText;/"
        self.assert_contains_offenders(
            f"""Text {{
    text: externalName
    Component.onCompleted: {{
        try {{ work(); }} catch {{ }} {fake_policy}.test("catch")
        false && x instanceof {fake_policy}
        for (x of {fake_policy}) {{ work(x); }}
        new {fake_policy}
        false && (x++ / {fake_policy}.source.length)
        false && (x-- / {fake_policy}.source.length)
        false && (x / {fake_policy}.source.length)
        false && (function() {{}} / {fake_policy}.source.length)
        false && (class {{}} / {fake_policy}.source.length)
        false && (class extends mixin({{}}) {{}} / {fake_policy}.source.length)
        false && (class extends (class {{}}) {{}} / {fake_policy}.source.length)
        false && (() => {{}} / {fake_policy}.source.length)
    }}
}}
""",
            [1],
        )
        self.assert_contains_offenders(
            f"""Text {{
    text: externalName
    Component.onCompleted: {{
        if (okay) {fake_policy}.test("x")
        if (other) {{ work(); }} {fake_policy}.test("y")
    }}
}}
""",
            [1],
        )

    def test_nested_child_binding_does_not_satisfy_parent(self) -> None:
        self.assert_contains_offenders(
            """Text {
    text: externalName
    Item {
        Text { textFormat: Text.PlainText }
    }
}
""",
            [1],
        )

    def test_comments_and_strings_cannot_create_or_satisfy_elements(self) -> None:
        self.assert_contains_offenders(
            '''// Text { textFormat: Text.PlainText }
Item {
    property string example: "Text { textFormat: Text.PlainText }"
    /* Text { textFormat: Text.PlainText } */
    Text { // textFormat: Text.PlainText
        text: "a } brace and a // comment marker"
    }
}
''',
            [5],
        )

    def test_overlapping_bait_cannot_consume_a_real_text(self) -> None:
        self.assert_contains_offenders(
            '''Item {
    property string bait: "Text /*"
    Text { text: "unsafe" }
    Text /* closes raw bait */ { textFormat: Text.PlainText; text: "safe" }
}
''',
            [3],
        )

    def test_word_operators_do_not_terminate_the_plain_binding(self) -> None:
        self.assert_contains_offenders(
            """Text {
    textFormat: Text.PlainText
        in { 0: true }
}
Text {
    textFormat: Text.PlainText
        instanceof {}
}
""",
            [1, 5],
        )

    def test_text_on_property_is_still_a_text_declaration(self) -> None:
        self.assert_offenders(
            """Item {
    property Item cibleÉ
    Text on cibleÉ { text: externalName }
    Text on cibleÉ { textFormat: Text.PlainText; text: "safe" }
}
""",
            [3],
        )

    def test_escaped_type_names_and_unicode_layout_are_checked(self) -> None:
        for source in (
            r"T\u0065xt { text: externalName }",
            r"\u{54}ext { text: externalName }",
            r"QtQuick.\u0054ext { text: externalName }",
            "Text\u00a0{ text: externalName }",
            "Text// comment\u2028{ text: externalName }",
        ):
            with self.subTest(source=source):
                self.assert_offenders(source, [1])

    def test_unicode_identifier_boundaries_and_canonical_ids_are_safe(self) -> None:
        self.assert_offenders(
            """Item {
    component ÉText: Item {}
    ÉText {}
}
Text {
    id: cibleÉ // formatter preserves this comment
    textFormat: Text.PlainText
}
Text {
    id: textFormat
    textFormat: Text.PlainText
}
""",
            [],
        )
        self.assert_offenders(
            r"""Item {
    property Item cible\u00c9
    Text on cible\u00c9 { text: externalName }
}
""",
            [3],
        )

    def test_direct_runtime_text_format_mutation_is_rejected(self) -> None:
        self.assert_offenders(
            """Text {
    id: root
    textFormat: Text.PlainText
    Component.onCompleted: root.textFormat = Text.AutoText
}
""",
            [4],
        )
        self.assert_offenders(
            r"""Text {
    id: root
    textFormat: Text.PlainText
    Component.onCompleted: root.text\u0046ormat = Text.AutoText
}
""",
            [4],
        )
        self.assert_contains_offenders(
            '''Text {
    id: root
    textFormat: Text.PlainText
    Binding { target: root; property: "textFormat"; value: Text.AutoText }
}
''',
            [4],
        )

    def test_javascript_context_cannot_hide_a_sibling_text(self) -> None:
        self.assert_contains_offenders(
            '''Item {
    property var ratio: condition ? {} : {} / denominator
    property string nested: `outer ${`textFormat: Text.PlainText;`}`
    property var keyword: obj.new / denominator
    Text { text: externalName }
}
''',
            [5],
        )

    def test_qualified_and_comment_separated_declarations_are_checked(self) -> None:
        self.assert_offenders(
            """QtQuick.Text /* why */ {
    id: qualified
    textFormat: Text.PlainText
}
Text /* inline */ { text: externalName }
""",
            [5],
        )


if __name__ == "__main__":
    unittest.main()

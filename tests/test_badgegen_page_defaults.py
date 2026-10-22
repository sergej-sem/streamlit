import ast
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


PAGE = Path(__file__).resolve().parents[1] / "pages" / "Badge-Generator.py"


def _prefix_widget_app() -> AppTest:
    source = PAGE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node
    # Exercise the actual dropdown without authentication or live CRM requests.
    code = "\n".join([
        "import streamlit as st",
        "from badgegen.category import EVENT_TAGS",
        ast.get_source_segment(source, assignments["_BG_DEFAULT_EVENT_TAG"]),
        ast.get_source_segment(source, assignments["event_tag"]),
    ])
    return AppTest.from_string(code, default_timeout=10)


class BadgePageDefaultTests(unittest.TestCase):
    def test_historie_prefix_defaults_to_munich(self):
        app = _prefix_widget_app().run()
        self.assertEqual(0, len(app.exception))
        self.assertEqual("26MUC", app.selectbox[0].value)
        self.assertEqual(["26DOR", "26BER", "26MUC"], app.selectbox[0].options)

    def test_other_historie_prefix_remains_selectable(self):
        app = _prefix_widget_app().run()
        app.selectbox[0].select("26BER").run()
        self.assertEqual(0, len(app.exception))
        self.assertEqual("26BER", app.selectbox[0].value)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest


class SerienmailingPagePreviewTests(unittest.TestCase):

    def _run(self, app: AppTest) -> None:
        with patch(
            "teilnehmerliste_generator.hubspot_client.get_contact_lists",
            return_value=[],
        ):
            app.run()

    def test_quill_widget_value_updates_canonical_body_and_preview(self):
        app = AppTest.from_file("pages/Serienmailing.py", default_timeout=20)
        app.session_state["sm_contacts"] = pd.DataFrame(
            [
                {
                    "vorname": "Anna",
                    "firma": "ACME",
                    "email": "anna@example.com",
                    "cc_email": "copy@example.com",
                }
            ]
        )
        app.session_state["sm_contacts_source"] = "test"
        app.session_state["sm_sender_email"] = "sender@example.com"
        app.session_state["sm_subject_tpl"] = "A descriptive preview subject"
        app.session_state["sm_mail_body_html"] = "<p>Alt {vorname}</p>"
        app.session_state["sm_mail_editor_instance"] = 0

        self._run(app)
        password = next(widget for widget in app.text_input if widget.label == "Passwort")
        password.input("secret")
        self._run(app)

        old_preview = "\n".join(element.proto.body for element in app.get("html"))
        self.assertIn("Alt Anna", old_preview)

        app.session_state["sm_mail_body_html__widget__0"] = "<p>Neu {vorname}</p>"
        self._run(app)

        new_preview = "\n".join(element.proto.body for element in app.get("html"))
        self.assertEqual("<p>Neu {vorname}</p>", app.session_state["sm_mail_body_html"])
        self.assertIn("Neu Anna", new_preview)
        self.assertNotIn("Alt Anna", new_preview)
        self.assertEqual(0, len(app.exception))


if __name__ == "__main__":
    unittest.main()

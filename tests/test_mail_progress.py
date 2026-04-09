import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mail_progress import (
    describe_smtp_progress,
    format_estimated_seconds,
    smtp_progress_percent,
)
from shared.smtp_sender import SmtpSendProgress


class MailProgressFormattingTests(unittest.TestCase):
    def test_format_estimated_seconds_rounds_up(self):
        self.assertEqual(5, format_estimated_seconds(4.2))
        self.assertEqual(0, format_estimated_seconds(0))

    def test_sending_message_contains_recipient_remaining_and_eta(self):
        progress = SmtpSendProgress(
            phase="sending",
            current_index=1,
            total_messages=3,
            current_recipient="alice@example.com",
            remaining_messages=2,
            completed_messages=0,
            estimated_remaining_seconds=9.1,
            current_delay_seconds=None,
        )
        message = describe_smtp_progress(progress)
        self.assertIn("alice@example.com", message)
        self.assertIn("Noch 2 Mails", message)
        self.assertIn("10 Sekunden", message)

    def test_waiting_message_contains_delay_and_overall_eta(self):
        progress = SmtpSendProgress(
            phase="waiting",
            current_index=1,
            total_messages=2,
            current_recipient="alice@example.com",
            remaining_messages=1,
            completed_messages=1,
            estimated_remaining_seconds=5.2,
            current_delay_seconds=3.1,
        )
        message = describe_smtp_progress(progress)
        self.assertIn("wurde verarbeitet", message)
        self.assertIn("Noch 1 Mail", message)
        self.assertIn("4 Sekunden", message)
        self.assertIn("6 Sekunden", message)

    def test_finished_message_is_simple(self):
        progress = SmtpSendProgress(
            phase="finished",
            current_index=2,
            total_messages=2,
            current_recipient="",
            remaining_messages=0,
            completed_messages=2,
            estimated_remaining_seconds=0.0,
            current_delay_seconds=None,
        )
        self.assertEqual("Versand abgeschlossen.", describe_smtp_progress(progress))

    def test_progress_percent_advances_by_phase(self):
        sending = SmtpSendProgress(
            phase="sending",
            current_index=1,
            total_messages=2,
            current_recipient="alice@example.com",
            remaining_messages=1,
            completed_messages=0,
            estimated_remaining_seconds=6.0,
            current_delay_seconds=None,
        )
        waiting = SmtpSendProgress(
            phase="waiting",
            current_index=1,
            total_messages=2,
            current_recipient="alice@example.com",
            remaining_messages=1,
            completed_messages=1,
            estimated_remaining_seconds=5.0,
            current_delay_seconds=4.0,
        )
        finished = SmtpSendProgress(
            phase="finished",
            current_index=2,
            total_messages=2,
            current_recipient="",
            remaining_messages=0,
            completed_messages=2,
            estimated_remaining_seconds=0.0,
            current_delay_seconds=None,
        )
        self.assertEqual(25, smtp_progress_percent(sending))
        self.assertEqual(50, smtp_progress_percent(waiting))
        self.assertEqual(100, smtp_progress_percent(finished))


if __name__ == "__main__":
    unittest.main()

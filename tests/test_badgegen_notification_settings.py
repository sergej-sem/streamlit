import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from badgegen.notification_settings import (  # noqa: E402
    BadgeNotificationSettings,
    DEFAULT_BADGE_NOTIFICATION_RECIPIENT,
    load_badge_notification_settings,
    save_badge_notification_settings,
)


class BadgeNotificationSettingsTests(unittest.TestCase):

    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.json"
            settings = load_badge_notification_settings(path)
            self.assertFalse(settings.email_enabled)
            self.assertEqual("", settings.sender_email)
            self.assertEqual(DEFAULT_BADGE_NOTIFICATION_RECIPIENT, settings.recipient_email)

    def test_roundtrip_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            expected = BadgeNotificationSettings(
                email_enabled=True,
                sender_email="alerts@example.com",
                recipient_email="badge-owner@example.com",
            )
            save_badge_notification_settings(path, expected)

            loaded = load_badge_notification_settings(path)
            self.assertEqual(expected, loaded)

    def test_overwrite_existing_file_updates_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            save_badge_notification_settings(
                path,
                BadgeNotificationSettings(
                    email_enabled=True,
                    sender_email="first@example.com",
                    recipient_email="first-recipient@example.com",
                ),
            )
            save_badge_notification_settings(
                path,
                BadgeNotificationSettings(
                    email_enabled=False,
                    sender_email="second@example.com",
                    recipient_email="second-recipient@example.com",
                ),
            )

            loaded = load_badge_notification_settings(path)
            self.assertFalse(loaded.email_enabled)
            self.assertEqual("second@example.com", loaded.sender_email)
            self.assertEqual("second-recipient@example.com", loaded.recipient_email)

    def test_invalid_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.json"
            path.write_text("{not valid json", encoding="utf-8")

            settings = load_badge_notification_settings(path)
            self.assertFalse(settings.email_enabled)
            self.assertEqual("", settings.sender_email)
            self.assertEqual(DEFAULT_BADGE_NOTIFICATION_RECIPIENT, settings.recipient_email)

    def test_missing_recipient_in_existing_file_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text('{"email_enabled": true, "sender_email": "alerts@example.com"}', encoding="utf-8")

            settings = load_badge_notification_settings(path)
            self.assertEqual(DEFAULT_BADGE_NOTIFICATION_RECIPIENT, settings.recipient_email)

    def test_transient_permission_error_retries_and_succeeds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            save_badge_notification_settings(
                path,
                BadgeNotificationSettings(sender_email="first@example.com"),
            )
            original_replace = os.replace
            state = {"calls": 0}

            def flaky_replace(src, dst):
                state["calls"] += 1
                if state["calls"] == 1:
                    raise PermissionError(5, "Access is denied")
                return original_replace(src, dst)

            with patch("badgegen.notification_settings.os.replace", side_effect=flaky_replace), \
                 patch("badgegen.notification_settings.time.sleep", return_value=None) as sleep_mock:
                save_badge_notification_settings(
                    path,
                    BadgeNotificationSettings(
                        email_enabled=True,
                        sender_email="retry@example.com",
                        recipient_email="notify@example.com",
                    ),
                )

            loaded = load_badge_notification_settings(path)
            self.assertEqual("retry@example.com", loaded.sender_email)
            self.assertEqual("notify@example.com", loaded.recipient_email)
            self.assertEqual(2, state["calls"])
            sleep_mock.assert_called_once()

    def test_permanent_permission_error_cleans_up_temp_file_and_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text("{}", encoding="utf-8")

            with patch("badgegen.notification_settings.os.replace", side_effect=PermissionError(5, "Access is denied")), \
                 patch("badgegen.notification_settings.time.sleep", return_value=None):
                with self.assertRaises(PermissionError):
                    save_badge_notification_settings(
                        path,
                        BadgeNotificationSettings(sender_email="blocked@example.com"),
                    )

            self.assertEqual([path.name], sorted(p.name for p in Path(tmpdir).iterdir()))


if __name__ == "__main__":
    unittest.main()

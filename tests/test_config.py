import unittest

from shared.config import (
    ConfigError,
    get_hubspot_token,
    is_live_user_creation_enabled,
    load_graph_bulk_user_settings,
    load_imap_draft_settings,
    load_smtp_send_settings,
    parse_bool,
)


class MappingLike:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data

    def __getitem__(self, key):
        return self._data[key]


class ParseBoolTests(unittest.TestCase):
    def test_parse_bool_known_values(self):
        self.assertTrue(parse_bool(True))
        self.assertFalse(parse_bool(False))
        self.assertTrue(parse_bool("true"))
        self.assertFalse(parse_bool("false"))
        self.assertTrue(parse_bool("1"))
        self.assertFalse(parse_bool("0"))
        self.assertTrue(parse_bool("yes"))
        self.assertFalse(parse_bool("no"))

    def test_parse_bool_safe_defaults(self):
        self.assertFalse(parse_bool(None, default=False))
        self.assertTrue(parse_bool(None, default=True))
        self.assertFalse(parse_bool("unexpected", default=False))
        self.assertTrue(parse_bool("unexpected", default=True))


class HubSpotConfigTests(unittest.TestCase):
    def test_prefers_hubspot_token_from_secrets(self):
        secrets = {"HUBSPOT_TOKEN": "secret-token"}
        self.assertEqual(get_hubspot_token(secrets=secrets), "secret-token")

    def test_falls_back_to_access_token_in_secrets(self):
        secrets = {"HUBSPOT_ACCESS_TOKEN": "access-token"}
        self.assertEqual(get_hubspot_token(secrets=secrets), "access-token")

    def test_falls_back_to_environment(self):
        token = get_hubspot_token(secrets={}, environ={"HUBSPOT_TOKEN": "env-token"})
        self.assertEqual(token, "env-token")

    def test_supports_mapping_like_inputs(self):
        secrets = MappingLike({"HUBSPOT_ACCESS_TOKEN": "mapping-token"})
        self.assertEqual(get_hubspot_token(secrets=secrets), "mapping-token")

    def test_raises_when_missing(self):
        with self.assertRaisesRegex(ConfigError, "HUBSPOT_TOKEN"):
            get_hubspot_token(secrets={}, environ={})


class GraphBulkUserConfigTests(unittest.TestCase):
    def test_loads_valid_settings(self):
        secrets = {
            "mse_graph_bulk_user": {
                "tenant_id": "tenant",
                "client_id": "client",
                "client_secret": "secret",
                "enable_live_user_creation": "true",
            }
        }
        settings = load_graph_bulk_user_settings(secrets)
        self.assertEqual(settings.tenant_id, "tenant")
        self.assertEqual(settings.client_id, "client")
        self.assertEqual(settings.client_secret, "secret")
        self.assertTrue(settings.enable_live_user_creation)

    def test_loads_mapping_like_sections(self):
        secrets = MappingLike(
            {
                "mse_graph_bulk_user": MappingLike(
                    {
                        "tenant_id": "tenant",
                        "client_id": "client",
                        "client_secret": "secret",
                    }
                )
            }
        )
        settings = load_graph_bulk_user_settings(secrets)
        self.assertFalse(settings.enable_live_user_creation)

    def test_missing_section_raises(self):
        with self.assertRaisesRegex(ConfigError, "mse_graph_bulk_user"):
            load_graph_bulk_user_settings({})

    def test_missing_required_key_raises(self):
        secrets = {"mse_graph_bulk_user": {"tenant_id": "tenant", "client_id": "client"}}
        with self.assertRaisesRegex(ConfigError, "mse_graph_bulk_user.client_secret"):
            load_graph_bulk_user_settings(secrets)

    def test_live_user_creation_enabled_defaults_false(self):
        secrets = {
            "mse_graph_bulk_user": {
                "tenant_id": "tenant",
                "client_id": "client",
                "client_secret": "secret",
            }
        }
        settings = load_graph_bulk_user_settings(secrets)
        self.assertFalse(settings.enable_live_user_creation)

    def test_is_live_user_creation_enabled_safe_defaults(self):
        self.assertFalse(is_live_user_creation_enabled({}))
        self.assertFalse(is_live_user_creation_enabled({"mse_graph_bulk_user": {}}))
        self.assertTrue(
            is_live_user_creation_enabled(
                {"mse_graph_bulk_user": {"enable_live_user_creation": "yes"}}
            )
        )
        self.assertFalse(
            is_live_user_creation_enabled(
                {"mse_graph_bulk_user": {"enable_live_user_creation": "unexpected"}}
            )
        )


class ImapDraftConfigTests(unittest.TestCase):
    def test_loads_valid_settings(self):
        secrets = {
            "mse_imap_mail_drafts": {
                "host": "imap.example.org",
                "port": "993",
                "drafts_folder": "Entwuerfe",
                "use_ssl": "false",
            }
        }
        settings = load_imap_draft_settings(secrets)
        self.assertEqual(settings.host, "imap.example.org")
        self.assertEqual(settings.port, 993)
        self.assertEqual(settings.drafts_folder, "Entwuerfe")
        self.assertFalse(settings.use_ssl)

    def test_applies_defaults(self):
        settings = load_imap_draft_settings(
            {"mse_imap_mail_drafts": {"host": "imap.example.org", "port": 993}}
        )
        self.assertEqual(settings.drafts_folder, "Drafts")
        self.assertTrue(settings.use_ssl)

    def test_missing_section_raises(self):
        with self.assertRaisesRegex(ConfigError, "mse_imap_mail_drafts"):
            load_imap_draft_settings({})

    def test_missing_required_value_raises(self):
        secrets = {"mse_imap_mail_drafts": {"host": "imap.example.org"}}
        with self.assertRaisesRegex(ConfigError, "mse_imap_mail_drafts.port"):
            load_imap_draft_settings(secrets)

    def test_invalid_port_raises(self):
        secrets = {"mse_imap_mail_drafts": {"host": "imap.example.org", "port": "abc"}}
        with self.assertRaisesRegex(ConfigError, "mse_imap_mail_drafts.port"):
            load_imap_draft_settings(secrets)


class SmtpSendConfigTests(unittest.TestCase):
    def test_loads_valid_settings(self):
        secrets = {
            "mse_smtp_mail_send": {
                "host": "smtp.example.org",
                "port": "587",
                "use_ssl": "false",
                "use_starttls": "true",
                "timeout_seconds": "45",
            }
        }
        settings = load_smtp_send_settings(secrets)
        self.assertEqual(settings.host, "smtp.example.org")
        self.assertEqual(settings.port, 587)
        self.assertFalse(settings.use_ssl)
        self.assertTrue(settings.use_starttls)
        self.assertEqual(settings.timeout_seconds, 45)

    def test_applies_defaults(self):
        settings = load_smtp_send_settings({"mse_smtp_mail_send": {"host": "smtp.example.org"}})
        self.assertEqual(settings.port, 465)
        self.assertTrue(settings.use_ssl)
        self.assertFalse(settings.use_starttls)
        self.assertEqual(settings.timeout_seconds, 30)

    def test_missing_section_raises(self):
        with self.assertRaisesRegex(ConfigError, "mse_smtp_mail_send"):
            load_smtp_send_settings({})

    def test_invalid_port_raises(self):
        secrets = {"mse_smtp_mail_send": {"host": "smtp.example.org", "port": "abc"}}
        with self.assertRaisesRegex(ConfigError, "mse_smtp_mail_send.port"):
            load_smtp_send_settings(secrets)

    def test_invalid_timeout_raises(self):
        secrets = {
            "mse_smtp_mail_send": {"host": "smtp.example.org", "timeout_seconds": "0"}
        }
        with self.assertRaisesRegex(ConfigError, "mse_smtp_mail_send.timeout_seconds"):
            load_smtp_send_settings(secrets)

    def test_ssl_and_starttls_cannot_both_be_true(self):
        secrets = {
            "mse_smtp_mail_send": {
                "host": "smtp.example.org",
                "use_ssl": True,
                "use_starttls": True,
            }
        }
        with self.assertRaisesRegex(ConfigError, "use_ssl.*use_starttls"):
            load_smtp_send_settings(secrets)


if __name__ == "__main__":
    unittest.main()

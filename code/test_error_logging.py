import imaplib
import unittest
from unittest.mock import patch

from connector import ConnectorError, IMAPClient
from error_logging import log_tool_errors


class ErrorLoggingTests(unittest.TestCase):
    def test_tool_error_is_logged_without_sensitive_data_and_propagated(self):
        @log_tool_errors
        def buscar_correos(asunto):
            raise ValueError(asunto)

        with self.assertLogs("imap_mcp", level="ERROR") as logs:
            with self.assertRaisesRegex(ValueError, "secreto"):
                buscar_correos("secreto")
        self.assertIn("buscar_correos", logs.output[0])
        self.assertIn("ValueError", logs.output[0])
        self.assertNotIn("secreto", logs.output[0])

    def test_success_is_not_changed(self):
        @log_tool_errors
        def tool():
            return {"resultados": []}
        self.assertEqual(tool(), {"resultados": []})
        self.assertEqual(tool.__name__, "tool")

    def test_imap_authentication_error_logs_stage_without_server_message(self):
        client = IMAPClient("IMAP_FINANCIAL")
        client.host, client.username, client.password = "host", "user", "secret"
        with patch("connector.imaplib.IMAP4_SSL") as imap:
            imap.return_value.login.side_effect = imaplib.IMAP4.error("secret")
            with self.assertLogs("imap_mcp", level="ERROR") as logs:
                with self.assertRaises(ConnectorError):
                    with client.connection("INBOX"):
                        pass
        self.assertIn("cuenta=financiera", logs.output[0])
        self.assertIn("etapa=autenticacion", logs.output[0])
        self.assertNotIn("secret", logs.output[0])

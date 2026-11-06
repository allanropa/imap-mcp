import json
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from connector import ConnectorError, IMAPClient, load_rules


class FakeIMAP:
    def __init__(self):
        self.calls = []

    def response(self, name):
        return name, [b"42"]

    def uid(self, command, *args):
        self.calls.append((command, args))
        if command == "search":
            return "OK", [b"1 2"]
        uid, section = args
        if section == "(BODY.PEEK[])":
            return "OK", [(b"1", b"From: banco@example.com\r\nSubject: Factura\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHola")]
        subject = b"Factura" if uid == "2" else b"Otro"
        return "OK", [(b"2 (FLAGS (\\Seen))", b"From: banco@example.com\r\nSubject: " + subject + b"\r\n\r\n")]


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = IMAPClient()
        self.fake = FakeIMAP()

        @contextmanager
        def connection(folder):
            yield self.fake
        self.client.connection = connection

    def test_search_financial_and_dates(self):
        self.client.rules = [{"sender": "BANCO", "subject_regex": "factura"}]
        result = self.client.search(desde="2026-01-01", hasta="2026-01-31", financial=True)
        self.assertEqual([x["uid"] for x in result["resultados"]], ["2"])
        self.assertTrue(result["resultados"][0]["leido"])
        self.assertIn("01-Feb-2026", self.fake.calls[0][1])
        self.assertIn("BODY.PEEK", self.fake.calls[1][1][1])

    def test_pagination_and_filter(self):
        result = self.client.search(asunto="otro", limite=1)
        self.assertEqual(result["resultados"][0]["uid"], "1")
        self.assertIsNone(result["siguiente_offset"])
        first = self.client.search(limite=1)
        self.assertEqual(first["siguiente_offset"], 1)

    def test_read_uidvalidity_and_peek(self):
        with self.assertRaises(ConnectorError):
            self.client.read("2", "41")
        result = self.client.read("2", "42")
        self.assertEqual(result["cuerpos"][0]["contenido"], "Hola")
        self.assertEqual(self.fake.calls[-1][1][1], "(BODY.PEEK[])")

    def test_invalid_uid(self):
        with self.assertRaises(ValueError):
            self.client.read("2:*", "42")

    def test_rules_file_validation(self):
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as file:
            json.dump([{"sender": "banco", "subject_regex": "factura"}], file)
            file.flush()
            self.assertEqual(load_rules(file.name)[0]["sender"], "banco")
            file.seek(0)
            file.truncate()
            json.dump([{"subject_regex": "["}], file)
            file.flush()
            with self.assertRaises(ValueError):
                load_rules(file.name)

    def test_separate_account_configuration(self):
        env = {"IMAP_HOST": "normal.example", "IMAP_USER": "normal", "IMAP_PASSWORD": "one", "IMAP_PORT": "993", "IMAP_FINANCIAL_HOST": "finance.example", "IMAP_FINANCIAL_USER": "finance", "IMAP_FINANCIAL_PASSWORD": "two", "IMAP_FINANCIAL_PORT": "1993"}
        with patch.dict("os.environ", env, clear=True):
            normal = IMAPClient()
            financial = IMAPClient("IMAP_FINANCIAL")
        self.assertEqual((normal.host, normal.port, normal.username, normal.password), ("normal.example", 993, "normal", "one"))
        self.assertEqual((financial.host, financial.port, financial.username, financial.password), ("finance.example", 1993, "finance", "two"))

    def test_financial_account_never_falls_back_to_normal(self):
        with patch.dict("os.environ", {"IMAP_HOST": "normal.example", "IMAP_USER": "normal", "IMAP_PASSWORD": "one"}, clear=True):
            financial = IMAPClient("IMAP_FINANCIAL")
            with self.assertRaisesRegex(ConnectorError, "IMAP_FINANCIAL_HOST"):
                with financial.connection("INBOX"):
                    pass


if __name__ == "__main__":
    unittest.main()

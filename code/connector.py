"""Cliente IMAP de solo lectura; nunca almacena credenciales ni mensajes."""
import imaplib
import json
import os
import re
import ssl
from contextlib import contextmanager
from datetime import date, timedelta
from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header
from pathlib import Path


class ConnectorError(Exception):
    pass


def decoded(value):
    try:
        return str(make_header(decode_header(value or "")))
    except (ValueError, LookupError):
        return str(value or "")


def ok(response):
    status, data = response
    if status != "OK":
        raise ConnectorError("El servidor IMAP rechazó la operación")
    return data


def imap_date(value):
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{value.day:02d}-{months[value.month - 1]}-{value.year:04d}"


def load_rules(path):
    try:
        with open(path, encoding="utf-8") as file:
            rules = json.load(file)
        if not isinstance(rules, list):
            raise ValueError("Las reglas deben ser una lista")
        for rule in rules:
            if not isinstance(rule, dict) or not rule or set(rule) - {"sender", "subject_regex"} or any(not isinstance(v, str) or not v for v in rule.values()):
                raise ValueError("Regla financiera inválida")
            if "subject_regex" in rule:
                re.compile(rule["subject_regex"])
        return rules
    except (OSError, ValueError, re.error) as exc:
        raise ValueError(f"Configuración de reglas financieras inválida: {path}: {exc}") from exc


class IMAPClient:
    def __init__(self):
        self.host = os.getenv("IMAP_HOST", "")
        self.port = int(os.getenv("IMAP_PORT", "993"))
        self.username = os.getenv("IMAP_USER", "")
        self.password = os.getenv("IMAP_PASSWORD", "")
        self.rules_path = os.getenv("IMAP_FINANCIAL_RULES", str(Path(__file__).resolve().parent.parent / "financial_rules.json"))
        self.rules = load_rules(self.rules_path)

    @contextmanager
    def connection(self, folder):
        if not all((self.host, self.username, self.password)):
            raise ConnectorError("Configura IMAP_HOST, IMAP_USER e IMAP_PASSWORD")
        if not folder or any(c in folder for c in '\r\n\x00'):
            raise ValueError("Carpeta inválida")
        conn = None
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=ssl.create_default_context(), timeout=30)
            conn.login(self.username, self.password)
            # Quote mailbox names to preserve spaces and prevent IMAP argument injection.
            mailbox = '"' + folder.replace('\\', '\\\\').replace('"', '\\"') + '"'
            ok(conn.select(mailbox, readonly=True))
            yield conn
        except (imaplib.IMAP4.error, OSError, EOFError) as exc:
            raise ConnectorError("Error de conexión o autenticación IMAP") from exc
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except (imaplib.IMAP4.error, OSError, EOFError):
                    pass

    @staticmethod
    def uidvalidity(conn):
        _, values = conn.response("UIDVALIDITY")
        if not values or not values[0]:
            raise ConnectorError("El servidor no proporcionó UIDVALIDITY")
        return values[0].decode("ascii")

    @staticmethod
    def fetch(conn, uid, part):
        data = ok(conn.uid("fetch", str(uid), part))
        for item in data:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes):
                return item[0], item[1]
        raise ConnectorError("Mensaje inexistente o no disponible")

    def search(self, desde=None, hasta=None, remitente=None, asunto=None, estado="todos", carpeta="INBOX", limite=20, offset=0, financial=False):
        if estado not in ("todos", "leidos", "no_leidos"):
            raise ValueError("Estado inválido")
        if not 1 <= limite <= 100 or offset < 0:
            raise ValueError("Límite u offset inválido")
        start = date.fromisoformat(desde) if desde else None
        end = date.fromisoformat(hasta) if hasta else None
        if start and end and start > end:
            raise ValueError("La fecha inicial es posterior a la final")
        criteria = []
        if start:
            criteria.extend(["SINCE", imap_date(start)])
        if end:
            criteria.extend(["BEFORE", imap_date(end + timedelta(days=1))])
        if estado != "todos":
            criteria.append("SEEN" if estado == "leidos" else "UNSEEN")
        with self.connection(carpeta) as conn:
            validity = self.uidvalidity(conn)
            data = ok(conn.uid("search", None, *(criteria or ["ALL"])))
            ids = list(reversed((data[0] or b"").split()))
            # Offset is a cursor into candidates, not matches, to bound work per call.
            candidates = ids[offset:offset + 200]
            results = []
            consumed = 0
            for uid in candidates:
                consumed += 1
                meta, raw = self.fetch(conn, uid.decode("ascii"), "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
                msg = BytesParser(policy=policy.default).parsebytes(raw)
                sender, subject = decoded(msg.get("From")), decoded(msg.get("Subject"))
                if remitente and remitente.casefold() not in sender.casefold():
                    continue
                if asunto and asunto.casefold() not in subject.casefold():
                    continue
                if financial and not any((not r.get("sender") or r["sender"].casefold() in sender.casefold()) and (not r.get("subject_regex") or re.search(r["subject_regex"], subject, re.I)) for r in self.rules):
                    continue
                results.append({"uid": uid.decode("ascii"), "uidvalidity": validity, "carpeta": carpeta, "remitente": sender, "asunto": subject, "fecha": str(msg.get("Date", "")), "message_id": str(msg.get("Message-ID", "")), "leido": bool(re.search(rb"\\Seen\b", meta, re.I))})
                if len(results) == limite:
                    break
            next_offset = offset + consumed
            return {"resultados": results, "siguiente_offset": next_offset if next_offset < len(ids) else None, "candidatos_examinados": consumed, "uidvalidity": validity}

    def read(self, uid, uidvalidity, carpeta="INBOX"):
        if not str(uid).isascii() or not str(uid).isdigit() or int(uid) < 1:
            raise ValueError("UID inválido")
        with self.connection(carpeta) as conn:
            if self.uidvalidity(conn) != str(uidvalidity):
                raise ConnectorError("UIDVALIDITY cambió; busca el mensaje de nuevo")
            _, raw = self.fetch(conn, uid, "(BODY.PEEK[])")
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        bodies, attachments = [], []
        for part in msg.walk():
            if part.is_multipart():
                continue
            filename = part.get_filename()
            if part.get_content_disposition() == "attachment" or filename:
                attachments.append({"nombre": decoded(filename), "tipo": part.get_content_type()})
            elif part.get_content_type() in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True) or b""
                try:
                    text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                except LookupError:
                    text = payload.decode("utf-8", errors="replace")
                bodies.append({"tipo": part.get_content_type(), "contenido": text[:100000], "truncado": len(text) > 100000})
        return {"uid": str(uid), "uidvalidity": str(uidvalidity), "carpeta": carpeta, "remitente": decoded(msg.get("From")), "asunto": decoded(msg.get("Subject")), "fecha": str(msg.get("Date", "")), "cuerpos": bodies, "adjuntos": attachments}

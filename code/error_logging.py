"""Registro de errores sin argumentos ni contenido de correos."""
import logging
from functools import wraps


logger = logging.getLogger("imap_mcp")


def log_tool_errors(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            cause = exc.__cause__
            logger.error("Error en herramienta %s: tipo=%s causa=%s", fn.__name__, type(exc).__name__, type(cause).__name__ if cause else "ninguna")
            raise
    return wrapper

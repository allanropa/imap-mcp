"""Servidor MCP IMAP de solo lectura."""
import os
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from connector import IMAPClient

mcp = FastMCP("Correo IMAP", host=os.getenv("MCP_BIND_HOST", "127.0.0.1"), port=int(os.getenv("MCP_PORT", "8000")), stateless_http=True)
client = IMAPClient()


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def read_tool(fn):
    return mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})(fn)


@read_tool
def buscar_correos(desde: str | None = None, hasta: str | None = None, remitente: str | None = None, asunto: str | None = None, estado: Literal["todos", "leidos", "no_leidos"] = "todos", carpeta: str = "INBOX", limite: Annotated[int, Field(ge=1, le=100)] = 20, offset: Annotated[int, Field(ge=0)] = 0) -> dict:
    """Busca por fecha IMAP inclusiva (YYYY-MM-DD), remitente, asunto y estado; usa siguiente_offset para continuar."""
    return client.search(desde, hasta, remitente, asunto, estado, carpeta, limite, offset)


@read_tool
def leer_correo(uid: str, uidvalidity: str, carpeta: str = "INBOX") -> dict:
    """Lee el mensaje identificado por UID, UIDVALIDITY y carpeta devueltos por la búsqueda, sin marcarlo como leído."""
    return client.read(uid, uidvalidity, carpeta)


@read_tool
def buscar_correos_financieros(desde: str | None = None, hasta: str | None = None, estado: Literal["todos", "leidos", "no_leidos"] = "todos", carpeta: str = "INBOX", limite: Annotated[int, Field(ge=1, le=100)] = 20, offset: Annotated[int, Field(ge=0)] = 0) -> dict:
    """Busca facturas y movimientos usando las reglas locales; usa siguiente_offset para continuar."""
    return client.search(desde=desde, hasta=hasta, estado=estado, carpeta=carpeta, limite=limite, offset=offset, financial=True)


if __name__ == "__main__":
    mcp.run(transport=os.getenv("MCP_TRANSPORT", "streamable-http"))

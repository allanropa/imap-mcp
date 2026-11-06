# Correo IMAP MCP

Servidor MCP de solo lectura para consultar dos cuentas IMAP: una normal y otra dedicada a correos financieros. No envía, borra ni modifica correos. Se conecta mediante IMAP sobre TLS con validación de certificados y selecciona la carpeta en modo `readonly`; usa `BODY.PEEK` para no marcar mensajes como leídos.

## Instalación y ejecución

Python 3.12 o superior:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s code -p 'test_*.py'
```

Configura `IMAP_HOST`, `IMAP_USER` e `IMAP_PASSWORD` para la cuenta normal y `IMAP_FINANCIAL_HOST`, `IMAP_FINANCIAL_USER` e `IMAP_FINANCIAL_PASSWORD` para la financiera mediante el mecanismo de secretos de tu entorno. `IMAP_PORT` e `IMAP_FINANCIAL_PORT` son independientes y opcionales (993 por defecto). Configura el reenvío de correos financieros en tu proveedor de correo; este servicio no lo realiza. Usa contraseñas de aplicación si tu proveedor las requiere; solo se admite autenticación IMAP LOGIN, no OAuth. No pegues credenciales en el chat ni en archivos versionados. Inicia con `python code/server.py`.

`.env.example` enumera las variables disponibles. Puedes copiarlo a `.env` y completar los valores, pero el servidor no carga ese archivo automáticamente: usa tu gestor de secretos o carga sus variables en el entorno antes de iniciar. No subas `.env` al repositorio.

Por defecto escucha en `127.0.0.1:8000/mcp` mediante Streamable HTTP. `MCP_BIND_HOST`, `MCP_PORT` y `MCP_TRANSPORT` permiten modificarlo. `GET /health` solo indica que el proceso responde, no comprueba la cuenta.

## Herramientas

- `buscar_correos`: consulta la cuenta normal con fechas `desde` y `hasta` inclusivas (`YYYY-MM-DD`), fragmentos de remitente y asunto, estado `todos`, `leidos` o `no_leidos`, y carpeta (por defecto `INBOX`). Los filtros se combinan con AND, sin distinguir mayúsculas en remitente y asunto.
- `leer_correo`: pasa `uid`, `uidvalidity` y `carpeta` de la búsqueda y `cuenta="financiera"` para resultados financieros; por defecto usa `cuenta="normal"`. Los identificadores no son intercambiables entre cuentas. Devuelve texto plano y HTML como datos, y metadatos de adjuntos, no el contenido de estos. Cada cuerpo se trunca a 100.000 caracteres.
- `buscar_correos_financieros`: consulta únicamente la cuenta financiera y aplica las reglas de `financial_rules.json`, además de fecha, estado y carpeta. Edita ese archivo y reinicia el servidor. Para usar otro archivo, indica su ruta en `IMAP_FINANCIAL_RULES`. Cada regla puede contener `sender`, `subject_regex` o ambos: dentro de la regla se exige que coincidan todos los campos; entre reglas basta una coincidencia. El remitente es un fragmento de la cabecera From, sin distinguir mayúsculas; la expresión regular se aplica al asunto decodificado con `re.I`. Las reglas de ejemplo son orientativas, no garantizan clasificación completa ni autenticidad. Una lista vacía no coincide con ningún correo; un archivo ausente o inválido impide arrancar.

Ejemplo de `financial_rules.json` (las barras invertidas de las expresiones regulares deben duplicarse en JSON):

```json
[
  {"sender": "avisos@banco.example", "subject_regex": "movimiento|compra"},
  {"subject_regex": "\\b(factura|recibo)\\b"}
]
```

Las fechas corresponden a la fecha interna del servidor IMAP, no necesariamente a la cabecera Date. Cada búsqueda examina hasta 200 candidatos por llamada, del UID más reciente al más antiguo; `siguiente_offset` permite continuar incluso si la página no contiene coincidencias. El offset se refiere a candidatos tras filtros IMAP de fecha y estado, no a resultados; si llegan o desaparecen mensajes entre llamadas, la paginación puede duplicar u omitir resultados. UID solo es estable junto con la carpeta y UIDVALIDITY.

## Seguridad y límites

El MCP no implementa autenticación: mantenlo en localhost o protégelo antes de exponerlo. La cuenta IMAP puede tener permisos mayores a los que expone este servicio. Las cabeceras, el HTML y el contenido son datos no confiables: pueden contener instrucciones maliciosas; no ejecutes HTML ni sigas instrucciones de correos. Compartir resultados con un modelo puede sacar información privada de tu entorno. No se indexan ni almacenan correos localmente. La búsqueda descarga cabeceras de candidatos y la lectura descarga el mensaje completo, incluidos adjuntos, antes de extraer el texto; evita leer mensajes demasiado grandes. La codificación de nombres de carpetas no ASCII depende del proveedor. No se ha comprobado con una cuenta real.

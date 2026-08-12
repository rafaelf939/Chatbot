# Analítica del chatbot AAFP

MVP para recibir selecciones de Kommo Salesbot, conservar el webhook original y persistir eventos en SQL Server para su consumo posterior desde Power BI.

## Arquitectura

`Kommo Salesbot -> FastAPI -> SQL Server -> Power BI`

La API se divide en rutas, servicios, repositorios, modelos y configuración. Con `DATABASE_ENABLED=false` usa un repositorio en memoria, por lo que puede arrancar y probarse sin SQL Server.

## Inicio local

Requiere Python 3.13 y, solamente para conexión real, Microsoft ODBC Driver 18 for SQL Server.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export WEBHOOK_SECRET='un-secreto-local'
uvicorn app.main:app --reload
```

La aplicación no carga `.env` automáticamente: expórtelo en el shell o use el mecanismo de variables de entorno del despliegue. Esto evita añadir otra dependencia y mantiene explícita la gestión de secretos.

## API

Salud:

```bash
curl http://localhost:8000/health
```

Evento JSON:

```bash
curl -X POST http://localhost:8000/api/v1/kommo/events/bot-faq-aafp/estado-de-cuenta \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: un-secreto-local' \
  -d '{"lead_id":123,"contact_id":456,"conversation_id":"abc","callback_data":"uuid"}'
```

El secreto es obligatorio para recibir eventos y se compara de manera segura; si no está configurado, el endpoint devuelve `503`. El cuerpo JSON completo se guarda en `payload_original`. Mientras se confirma el payload real de Kommo, la API busca de forma recursiva las claves `lead_id`, `contact_id`, `conversation_id` y `callback_data`; si el webhook no es JSON también conserva su contenido como texto y su `Content-Type`.

Respuesta exitosa: HTTP `202` con el UUID del evento. Un secreto ausente o incorrecto devuelve `401`.

## SQL Server

Ejecute [sql/001_create_tables.sql](sql/001_create_tables.sql) en la base elegida. Después configure:

```bash
export DATABASE_ENABLED=true
export SQLSERVER_CONNECTION_STRING='DRIVER={ODBC Driver 18 for SQL Server};SERVER=...'
```

`CHATBOT_OPCION` mantiene el catálogo y asegura unicidad por bot. `CHATBOT_EVENTO` mantiene hechos de interacción, el callback observado y el JSON original. Sus índices soportan conteos por fecha, bot, opción, contacto y conversación. Los identificadores se guardan como texto para tolerar el formato que finalmente entregue Kommo.

Antes de recibir eventos debe cargarse el catálogo correspondiente, porque la tabla de eventos tiene una clave foránea `(bot_codigo, opcion_codigo)`.

## Extraer el catálogo de Kommo

Los tres archivos originales están en `docs/bots`. Para producir un catálogo derivado:

```bash
python scripts/parse_kommo_bots.py docs/bots --output catalogo_chatbot.json
```

El extractor usa `model.text`, identifica mensajes de lista, sus secciones, filas y callbacks, y enlaza cada callback con el `goto` del mismo paso. Genera códigos legibles y deterministas a partir del nombre del bot y de la opción. También informa callbacks compartidos entre bots.

### Resultado y limitaciones observadas

- Se detectaron 3 bots y 25 opciones: 18 en FAQ, 4 en protección por enfermedad y 3 en protección por fallecimiento.
- Tres callbacks están reutilizados entre los dos bots de protección. Por eso nunca se usan solos como clave.
- `menu` corresponde al título de la sección de la lista; es el rótulo más confiable disponible en la exportación.
- `paso_destino` se obtiene del `goto` asociado al callback. Si el formato cambia o no existe el enlace, queda `null`; no se inventa.
- Kommo no exporta en estos archivos un código estable de negocio para bot u opción. Los códigos generados son *slugs* deterministas, pero deben considerarse códigos internos de esta aplicación.
- Las relaciones de inicio hacia otros Salesbots incluyen IDs numéricos en la vista visual, pero las exportaciones no permiten asociar de forma inequívoca esos IDs con el identificador propio de cada archivo. Por eso no se materializan como relación confiable en este MVP.
- El catálogo describe el flujo actual; no contiene usuarios, eventos históricos ni garantiza que futuras exportaciones conserven exactamente el mismo esquema.

## Pruebas

```bash
python -m pytest -q
```

Cubren salud, autenticación, recepción/persistencia simulada, extracción de los tres JSON y detección de callbacks duplicados entre bots.

## Power BI

No forma parte del MVP. El modelo separa la dimensión de opciones del hecho de eventos para calcular selecciones totales y por bot/menú/opción, contactos únicos, conversaciones únicas y evolución diaria o mensual. Para producción conviene exponer vistas SQL de lectura y dar a Power BI un usuario de solo lectura.

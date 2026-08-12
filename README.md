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

### Inicio rápido del webhook en desarrollo

En GitHub Codespaces puede generar o reutilizar automáticamente el secreto temporal, configurar el modo en memoria e iniciar Uvicorn con un solo worker y sin access log:

```bash
python scripts/start_dev_webhook.py
```

El script comprueba que el puerto 8000 esté libre, detecta la URL pública mediante `CODESPACE_NAME` y `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`, inicia FastAPI, espera un health local correcto e intenta establecer el puerto como público mediante GitHub CLI. Después verifica el health público y mantiene el servidor ejecutándose hasta `Ctrl+C`. Si las variables de Codespaces no están disponibles, configure la URL explícitamente antes de iniciar:

```bash
export CODESPACE_PUBLIC_URL='https://nombre-del-codespace-8000.app.github.dev'
python scripts/start_dev_webhook.py
```

El token se crea sin salto de línea, con permisos restrictivos en `/tmp/kommo_secret`, y se reutiliza en ejecuciones posteriores. La terminal solo muestra la URL marcada como **URL para copiar en Kommo** después de obtener HTTP `200` tanto local como públicamente. Esa URL contiene el secreto: es exclusivamente para desarrollo y no debe copiarse al README, subirse a GitHub ni compartirse. Si GitHub CLI no está disponible o no puede cambiar la visibilidad, FastAPI permanece funcionando y el script indica cómo marcar manualmente el puerto como público.

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

El secreto es obligatorio para recibir eventos y se compara de manera segura; si no está configurado, el endpoint devuelve `503`. El cuerpo JSON completo se guarda en `payload_original`. La API busca de forma recursiva las claves `lead_id`, `contact_id`, `conversation_id` y `callback_data`; para otros tipos de contenido no reconocidos conserva el cuerpo como texto y su `Content-Type`.

Los webhooks reales de Kommo con `Content-Type: application/x-www-form-urlencoded` se convierten a un diccionario y extraen `lead_id_kommo`, `status_id_kommo`, `pipeline_id_kommo` y `account_id_kommo`. Para minimizar datos, en `payload_original` solo se conservan los campos form necesarios de lead y cuenta; nombres, teléfonos, correos y cualquier otro campo no permitido se descartan. `account[subdomain]` se conserva únicamente en ese payload sanitizado para diagnóstico, pero no se normaliza como dimensión analítica porque `account_id_kommo` ya identifica la cuenta de manera más estable.

Para la prueba temporal desde el bloque nativo **Enviar webhook** de Kommo Salesbot, que no permite configurar el header personalizado, también se acepta el mismo secreto mediante el query parameter `token`:

```text
/api/v1/kommo/events/bot-faq-aafp/estado-de-cuenta?token=un-secreto-local
```

La autenticación se acepta si coincide `X-Webhook-Secret` o `token`; el header continúa siendo el mecanismo principal. El parámetro `token` es una solución exclusiva para desarrollo/MVP y **no es el mecanismo recomendado para producción**, porque las URLs pueden quedar expuestas en historiales o sistemas intermediarios. La aplicación elimina este parámetro del query string antes de generar su respuesta para evitar incluir el secreto en el access log de Uvicorn, y nunca lo incorpora en `payload_original`.

Respuesta exitosa: HTTP `202` con el UUID del evento. Un secreto ausente o incorrecto devuelve `401`.

### Consulta temporal de eventos en desarrollo

Cuando `DATABASE_ENABLED=false`, la API habilita temporalmente dos endpoints de depuración para inspeccionar los eventos conservados por `InMemoryEventRepository`:

```bash
curl http://localhost:8000/api/v1/debug/events
curl http://localhost:8000/api/v1/debug/events/latest
```

El primero devuelve todos los eventos recibidos desde que arrancó el proceso y el segundo devuelve el más reciente. Si todavía no se recibió ninguno, el endpoint `latest` responde `404`. Como el almacenamiento es volátil, reiniciar la API o recargarla elimina los eventos.

Estos endpoints son exclusivamente para desarrollo y **no deben exponerse en producción**. Cuando `DATABASE_ENABLED=true`, las rutas no se registran y tampoco aparecen en el esquema OpenAPI. No devuelven secretos ni variables de entorno, pero sí el payload original recibido, que puede contener información sensible enviada por el cliente.

### Diagnóstico temporal de requests de Kommo

También con `DATABASE_ENABLED=false`, un middleware registra en memoria las últimas 50 solicitudes cuyo path comienza por `/api/v1/kommo/`, incluso si el método o la ruta no coinciden y la respuesta termina en error. Se pueden consultar mediante:

```bash
curl http://localhost:8000/api/v1/debug/requests
curl http://localhost:8000/api/v1/debug/requests/latest
```

El diagnóstico incluye método, path, status, metadatos HTTP permitidos, tamaño del body y cuerpos pequeños de formatos textuales conocidos. Los cuerpos mayores de 16 KiB no se conservan. El query parameter `token`, los headers de autenticación y cookies, los campos sensibles del body y el valor de `WEBHOOK_SECRET` se redactan o se excluyen. Este registro es volátil, existe exclusivamente para diagnosticar el MVP en desarrollo y **no debe habilitarse ni exponerse en producción**.

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

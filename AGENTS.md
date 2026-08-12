# Proyecto

Analítica del chatbot de WhatsApp de la Asociación de AFP.

- Python 3.13, FastAPI y SQL Server mediante pyodbc.
- Nunca almacenar secretos ni archivos `.env`.
- `callback_data` no es globalmente único; usar siempre bot + callback o bot + opción.
- Los JSON de `docs/bots` son definiciones, no datos históricos, y no deben modificarse.
- Mantener separadas API, servicios, repositorios y modelos; ejecutar pytest tras cambios.

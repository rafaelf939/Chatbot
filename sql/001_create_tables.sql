SET XACT_ABORT ON;
BEGIN TRANSACTION;

CREATE TABLE dbo.CHATBOT_OPCION (
    id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CHATBOT_OPCION PRIMARY KEY,
    bot_codigo NVARCHAR(100) NOT NULL,
    bot_nombre NVARCHAR(255) NOT NULL,
    menu NVARCHAR(255) NULL,
    opcion_codigo NVARCHAR(150) NOT NULL,
    opcion_nombre NVARCHAR(255) NOT NULL,
    callback_data NVARCHAR(255) NULL,
    paso_destino NVARCHAR(100) NULL,
    activo BIT NOT NULL CONSTRAINT DF_CHATBOT_OPCION_activo DEFAULT (1),
    CONSTRAINT UQ_CHATBOT_OPCION_codigo UNIQUE (bot_codigo, opcion_codigo)
);

CREATE UNIQUE INDEX UX_CHATBOT_OPCION_callback
ON dbo.CHATBOT_OPCION (bot_codigo, callback_data)
WHERE callback_data IS NOT NULL;

CREATE TABLE dbo.CHATBOT_EVENTO (
    id_evento UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_CHATBOT_EVENTO PRIMARY KEY,
    fecha_evento_utc DATETIME2(3) NOT NULL,
    bot_codigo NVARCHAR(100) NOT NULL,
    opcion_codigo NVARCHAR(150) NOT NULL,
    callback_data NVARCHAR(255) NULL,
    lead_id_kommo NVARCHAR(100) NULL,
    contact_id_kommo NVARCHAR(100) NULL,
    conversation_id NVARCHAR(150) NULL,
    payload_original NVARCHAR(MAX) NOT NULL,
    fecha_creacion DATETIME2(3) NOT NULL CONSTRAINT DF_CHATBOT_EVENTO_creacion DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_CHATBOT_EVENTO_payload_json CHECK (ISJSON(payload_original) = 1),
    CONSTRAINT FK_CHATBOT_EVENTO_opcion FOREIGN KEY (bot_codigo, opcion_codigo)
        REFERENCES dbo.CHATBOT_OPCION (bot_codigo, opcion_codigo)
);

CREATE INDEX IX_CHATBOT_EVENTO_fecha ON dbo.CHATBOT_EVENTO (fecha_evento_utc);
CREATE INDEX IX_CHATBOT_EVENTO_bot_opcion_fecha ON dbo.CHATBOT_EVENTO (bot_codigo, opcion_codigo, fecha_evento_utc);
CREATE INDEX IX_CHATBOT_EVENTO_contacto ON dbo.CHATBOT_EVENTO (contact_id_kommo) WHERE contact_id_kommo IS NOT NULL;
CREATE INDEX IX_CHATBOT_EVENTO_conversacion ON dbo.CHATBOT_EVENTO (conversation_id) WHERE conversation_id IS NOT NULL;

COMMIT TRANSACTION;


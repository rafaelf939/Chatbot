SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'dbo.ChatbotEvento', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.ChatbotEvento (
            IdEvento UNIQUEIDENTIFIER NOT NULL
                CONSTRAINT PK_ChatbotEvento PRIMARY KEY,
            FechaEventoUtc DATETIME2(3) NOT NULL,
            BotCodigo NVARCHAR(100) NOT NULL,
            OpcionCodigo NVARCHAR(100) NOT NULL,
            LeadIdKommo BIGINT NULL,
            StatusIdKommo BIGINT NULL,
            PipelineIdKommo BIGINT NULL,
            AccountIdKommo BIGINT NULL,
            PayloadOriginal NVARCHAR(MAX) NULL,
            FechaCreacionUtc DATETIME2(3) NOT NULL
                CONSTRAINT DF_ChatbotEvento_FechaCreacionUtc DEFAULT SYSUTCDATETIME(),
            CONSTRAINT CK_ChatbotEvento_PayloadOriginalJson
                CHECK (PayloadOriginal IS NULL OR ISJSON(PayloadOriginal) = 1)
        );

        CREATE INDEX IX_ChatbotEvento_FechaEventoUtc
            ON dbo.ChatbotEvento (FechaEventoUtc);

        CREATE INDEX IX_ChatbotEvento_BotOpcionFecha
            ON dbo.ChatbotEvento (BotCodigo, OpcionCodigo, FechaEventoUtc);

        CREATE INDEX IX_ChatbotEvento_LeadIdKommo
            ON dbo.ChatbotEvento (LeadIdKommo)
            WHERE LeadIdKommo IS NOT NULL;
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;

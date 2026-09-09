-- FASE 4A - ejecutar en la App DB con un usuario autorizado para crear tablas.
-- Las credenciales de esta base no deben reutilizarse en la BD analítica.

IF SCHEMA_ID(N'biAgent') IS NULL
    EXEC(N'CREATE SCHEMA [biAgent]');

CREATE TABLE [biAgent].[app_conversations] (
    conversation_id varchar(36) NOT NULL PRIMARY KEY,
    title nvarchar(200) NOT NULL,
    created_at datetimeoffset NOT NULL,
    updated_at datetimeoffset NOT NULL
);

CREATE TABLE [biAgent].[app_messages] (
    message_id bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
    conversation_id varchar(36) NOT NULL,
    role varchar(16) NOT NULL,
    content nvarchar(max) NOT NULL,
    data_json nvarchar(max) NULL,
    created_at datetimeoffset NOT NULL,
    CONSTRAINT CK_app_messages_role CHECK (role IN ('user', 'assistant')),
    CONSTRAINT FK_app_messages_conversation FOREIGN KEY (conversation_id)
        REFERENCES [biAgent].[app_conversations](conversation_id) ON DELETE CASCADE
);

CREATE INDEX ix_app_messages_conversation
    ON [biAgent].[app_messages](conversation_id, message_id);

CREATE TABLE [biAgent].[app_audit_turns] (
    audit_id bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
    conversation_id varchar(36) NOT NULL,
    [timestamp] datetimeoffset NOT NULL,
    duration_ms float NOT NULL,
    sql_attempt_count int NOT NULL,
    success bit NOT NULL,
    error nvarchar(200) NULL,
    CONSTRAINT FK_app_audit_turns_conversation FOREIGN KEY (conversation_id)
        REFERENCES [biAgent].[app_conversations](conversation_id) ON DELETE CASCADE
);

CREATE INDEX ix_app_audit_turns_conversation
    ON [biAgent].[app_audit_turns](conversation_id, [timestamp]);

CREATE TABLE [biAgent].[app_audit_sql_attempts] (
    attempt_id bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
    audit_id bigint NOT NULL,
    attempt_number int NOT NULL,
    sql_text nvarchar(max) NOT NULL,
    guard_passed bit NOT NULL,
    duration_ms float NOT NULL,
    row_count int NULL,
    truncated bit NULL,
    success bit NOT NULL,
    error nvarchar(1000) NULL,
    CONSTRAINT FK_app_audit_sql_attempts_turn FOREIGN KEY (audit_id)
        REFERENCES [biAgent].[app_audit_turns](audit_id) ON DELETE CASCADE
);

CREATE INDEX ix_app_audit_sql_attempts_audit
    ON [biAgent].[app_audit_sql_attempts](audit_id, attempt_number);

-- FASE 4B - autenticación local y aislamiento por usuario.
-- Ejecutar una sola vez en la App DB después de 001_phase4a_app_db.sql.

CREATE TABLE [biAgent].[app_users] (
    user_id bigint IDENTITY(1,1) NOT NULL,
    username nvarchar(100) NOT NULL,
    username_normalized nvarchar(100) NOT NULL,
    display_name nvarchar(200) NOT NULL,
    password_hash nvarchar(512) NOT NULL,
    is_admin bit NOT NULL CONSTRAINT DF_app_users_is_admin DEFAULT 0,
    is_active bit NOT NULL CONSTRAINT DF_app_users_is_active DEFAULT 1,
    must_change_password bit NOT NULL CONSTRAINT DF_app_users_must_change_password DEFAULT 1,
    failed_login_attempts int NOT NULL
        CONSTRAINT DF_app_users_failed_login_attempts DEFAULT 0,
    locked_until datetimeoffset NULL,
    created_at datetimeoffset NOT NULL CONSTRAINT DF_app_users_created_at DEFAULT SYSDATETIMEOFFSET(),
    updated_at datetimeoffset NOT NULL CONSTRAINT DF_app_users_updated_at DEFAULT SYSDATETIMEOFFSET(),
    last_login_at datetimeoffset NULL,
    CONSTRAINT PK_app_users PRIMARY KEY (user_id),
    CONSTRAINT CK_app_users_username_not_blank CHECK (LEN(LTRIM(RTRIM(username))) > 0),
    CONSTRAINT CK_app_users_username_normalized_not_blank
        CHECK (LEN(LTRIM(RTRIM(username_normalized))) > 0),
    CONSTRAINT CK_app_users_display_name_not_blank CHECK (LEN(LTRIM(RTRIM(display_name))) > 0),
    CONSTRAINT CK_app_users_failed_login_attempts CHECK (failed_login_attempts >= 0)
);

CREATE UNIQUE INDEX UX_app_users_username_normalized
    ON [biAgent].[app_users](username_normalized);

CREATE TABLE [biAgent].[app_user_sessions] (
    session_id bigint IDENTITY(1,1) NOT NULL,
    user_id bigint NOT NULL,
    session_token_hash char(64) NOT NULL,
    created_at datetimeoffset NOT NULL
        CONSTRAINT DF_app_user_sessions_created_at DEFAULT SYSDATETIMEOFFSET(),
    expires_at datetimeoffset NOT NULL,
    last_seen_at datetimeoffset NOT NULL
        CONSTRAINT DF_app_user_sessions_last_seen_at DEFAULT SYSDATETIMEOFFSET(),
    revoked_at datetimeoffset NULL,
    CONSTRAINT PK_app_user_sessions PRIMARY KEY (session_id),
    CONSTRAINT CK_app_user_sessions_expiration CHECK (expires_at > created_at),
    CONSTRAINT FK_app_user_sessions_user FOREIGN KEY (user_id)
        REFERENCES [biAgent].[app_users](user_id)
);

CREATE UNIQUE INDEX UX_app_user_sessions_token
    ON [biAgent].[app_user_sessions](session_token_hash);
CREATE INDEX IX_app_user_sessions_user
    ON [biAgent].[app_user_sessions](user_id, expires_at);
CREATE INDEX IX_app_user_sessions_expiration
    ON [biAgent].[app_user_sessions](expires_at);

ALTER TABLE [biAgent].[app_conversations] ADD user_id bigint NULL;
ALTER TABLE [biAgent].[app_audit_turns] ADD user_id bigint NULL;

CREATE INDEX IX_app_conversations_user_updated
    ON [biAgent].[app_conversations](user_id, updated_at);
CREATE INDEX IX_app_audit_turns_user_timestamp
    ON [biAgent].[app_audit_turns](user_id, [timestamp]);

ALTER TABLE [biAgent].[app_conversations] ADD CONSTRAINT FK_app_conversations_user
    FOREIGN KEY (user_id) REFERENCES [biAgent].[app_users](user_id);
ALTER TABLE [biAgent].[app_audit_turns] ADD CONSTRAINT FK_app_audit_turns_user
    FOREIGN KEY (user_id) REFERENCES [biAgent].[app_users](user_id);

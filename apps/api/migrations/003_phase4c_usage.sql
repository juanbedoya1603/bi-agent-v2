-- FASE 4C - telemetria de uso y costo por respuesta del agente.
-- Ejecutar una sola vez en la App DB despues de 002_phase4b_local_auth.sql.
-- user_id permanece nullable fisicamente; la aplicacion exige ownership.

IF EXISTS (
    SELECT 1 FROM [biAgent].[app_conversations] WHERE user_id IS NULL
) OR EXISTS (
    SELECT 1 FROM [biAgent].[app_audit_turns] WHERE user_id IS NULL
)
    THROW 51000, 'No se puede aplicar Fase 4C: existen owners NULL.', 1;

ALTER TABLE [biAgent].[app_audit_turns] ADD
    assistant_message_id bigint NULL,
    model_name nvarchar(100) NULL,
    llm_requests int NULL,
    input_tokens bigint NULL,
    cached_input_tokens bigint NULL,
    output_tokens bigint NULL,
    reasoning_tokens bigint NULL,
    total_tokens bigint NULL,
    estimated_cost_usd decimal(19,8) NULL;

ALTER TABLE [biAgent].[app_audit_turns]
    ADD CONSTRAINT FK_app_audit_turns_assistant_message
    FOREIGN KEY (assistant_message_id)
    REFERENCES [biAgent].[app_messages](message_id);

CREATE UNIQUE INDEX UX_app_audit_turns_assistant_message
    ON [biAgent].[app_audit_turns](assistant_message_id)
    WHERE assistant_message_id IS NOT NULL;

ALTER TABLE [biAgent].[app_audit_turns]
    ADD CONSTRAINT CK_app_audit_turns_usage_nonnegative CHECK (
        (llm_requests IS NULL OR llm_requests >= 0)
        AND (input_tokens IS NULL OR input_tokens >= 0)
        AND (cached_input_tokens IS NULL OR cached_input_tokens >= 0)
        AND (output_tokens IS NULL OR output_tokens >= 0)
        AND (reasoning_tokens IS NULL OR reasoning_tokens >= 0)
        AND (total_tokens IS NULL OR total_tokens >= 0)
        AND (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)
    );

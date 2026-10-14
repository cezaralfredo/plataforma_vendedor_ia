-- =============================================================================
-- Plataforma Atende Agenda - Script de Manutenção Periódica de Banco de Dados
-- =============================================================================
-- Ciclo Recomendado: A cada 30 DIAS (pode ser agendado via cron/vps_cleanup.sh)
--
-- Política de Retenção de Dados Estipulada:
--   1. Notificações entregues (notification_deliveries com status='sent'):
--      -> Retenção: 30 DIAS (mensagens entregues há mais de 30d são purgadas)
--   2. Notificações falhas (notification_deliveries com status='failed'):
--      -> Retenção: 90 DIAS (mantidas por 3 meses para auditoria)
--   3. Eventos de Webhook (webhook_events):
--      -> Retenção: 60 DIAS (tempo mais que suficiente para garantir idempotência)
--   4. Logs de notificações gerais (notification_log):
--      -> Retenção: 90 DIAS
--   5. Agendamentos cancelados ou pendentes abandonados (appointments com status IN ('cancelled', 'pending')):
--      -> Retenção: 60 DIAS (libera a grade e elimina reservas descartadas)
--   6. Agendamentos CONCLUÍDOS e pagamentos RECEBIDOS/CONFIRMADOS:
--      -> PRESERVADOS PERMANENTEMENTE (histórico fiscal, contábil e de faturamento)
--
-- Como executar na VPS:
--   docker exec -i <nome_container_postgres> psql -U agenda_user -d agenda_atende < scripts/maintenance_cleanup.sql
-- =============================================================================

BEGIN;

-- 1. Purgar outbox de notificações já entregues com mais de 30 dias
WITH deleted_sent_deliveries AS (
    DELETE FROM notification_deliveries
    WHERE status = 'sent'
      AND sent_at < NOW() - INTERVAL '30 days'
    RETURNING id
)
SELECT COUNT(*) AS total_sent_deliveries_purgadas FROM deleted_sent_deliveries;

-- 2. Purgar outbox de notificações com falha definitiva com mais de 90 dias
WITH deleted_failed_deliveries AS (
    DELETE FROM notification_deliveries
    WHERE status = 'failed'
      AND created_at < NOW() - INTERVAL '90 days'
    RETURNING id
)
SELECT COUNT(*) AS total_failed_deliveries_purgadas FROM deleted_failed_deliveries;

-- 3. Purgar logs de notificações com mais de 90 dias
WITH deleted_notification_logs AS (
    DELETE FROM notification_log
    WHERE sent_at < NOW() - INTERVAL '90 days'
    RETURNING id
)
SELECT COUNT(*) AS total_notification_logs_purgados FROM deleted_notification_logs;

-- 4. Purgar eventos de webhook Asaas antigos com mais de 60 dias (idempotência superada)
WITH deleted_webhooks AS (
    DELETE FROM webhook_events
    WHERE received_at < NOW() - INTERVAL '60 days'
    RETURNING id
)
SELECT COUNT(*) AS total_webhooks_purgados FROM deleted_webhooks;

-- 5. Purgar pagamentos não pagos vinculados a agendamentos cancelados/abandonados há mais de 60 dias
DELETE FROM payments
WHERE appointment_id IN (
    SELECT id FROM appointments
    WHERE status IN ('cancelled', 'pending')
      AND end_time < NOW() - INTERVAL '60 days'
)
AND status IN ('cancelled', 'overdue', 'pending');

-- 6. Purgar agendamentos cancelados ou abandonados há mais de 60 dias (que não possuem pagamentos recebidos)
WITH deleted_cancelled_appointments AS (
    DELETE FROM appointments
    WHERE status IN ('cancelled', 'pending')
      AND end_time < NOW() - INTERVAL '60 days'
      AND id NOT IN (
          SELECT appointment_id FROM payments WHERE status IN ('received', 'confirmed')
      )
    RETURNING id
)
SELECT COUNT(*) AS total_agendamentos_cancelados_purgados FROM deleted_cancelled_appointments;

COMMIT;

-- 7. Recuperar espaço em disco e atualizar planos de execução do PostgreSQL
VACUUM ANALYZE;

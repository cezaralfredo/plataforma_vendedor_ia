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

-- 4b. Purgar chaves de deduplicação de webhooks WhatsApp com mais de 30 dias
DELETE FROM processed_inbound_messages
WHERE created_at < NOW() - INTERVAL '30 days';

-- 5. Purgar registros dependentes e pagamentos não pagos de agendamentos cancelados/abandonados há mais de 60 dias
DELETE FROM notification_deliveries
WHERE appointment_id IN (
    SELECT id FROM appointments a
    WHERE a.status IN ('cancelled', 'pending')
      AND a.end_time < NOW() - INTERVAL '60 days'
      AND NOT EXISTS (
          SELECT 1 FROM payments p
          WHERE p.appointment_id = a.id
            AND p.status IN ('received', 'confirmed')
      )
);

DELETE FROM notification_log
WHERE appointment_id IN (
    SELECT id FROM appointments a
    WHERE a.status IN ('cancelled', 'pending')
      AND a.end_time < NOW() - INTERVAL '60 days'
      AND NOT EXISTS (
          SELECT 1 FROM payments p
          WHERE p.appointment_id = a.id
            AND p.status IN ('received', 'confirmed')
      )
);

DELETE FROM payments
WHERE appointment_id IN (
    SELECT id FROM appointments a
    WHERE a.status IN ('cancelled', 'pending')
      AND a.end_time < NOW() - INTERVAL '60 days'
      AND NOT EXISTS (
          SELECT 1 FROM payments p
          WHERE p.appointment_id = a.id
            AND p.status IN ('received', 'confirmed')
      )
)
AND status IN ('cancelled', 'overdue', 'pending');

-- 6. Purgar agendamentos cancelados ou abandonados há mais de 60 dias (usando NOT EXISTS imune a NULL)
WITH deleted_cancelled_appointments AS (
    DELETE FROM appointments a
    WHERE a.status IN ('cancelled', 'pending')
      AND a.end_time < NOW() - INTERVAL '60 days'
      AND NOT EXISTS (
          SELECT 1 FROM payments p
          WHERE p.appointment_id = a.id
            AND p.status IN ('received', 'confirmed')
      )
    RETURNING a.id
)
SELECT COUNT(*) AS total_agendamentos_cancelados_purgados FROM deleted_cancelled_appointments;

COMMIT;

-- 7. Recuperar espaço em disco e atualizar planos de execução do PostgreSQL
VACUUM ANALYZE;

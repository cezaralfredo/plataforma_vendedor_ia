-- =============================================================================
-- Plataforma Atende Agenda - Script de Reset / Limpeza Permanente da VPS
-- =============================================================================
-- Finalidade:
--   Apaga PERMANENTEMENTE os dados operacionais, transacionais e de clientes
--   (clientes, agendamentos, pagamentos, webhooks e notificações antigas),
--   deixando o banco limpo e alinhado com a conta do Asaas.
--
-- Preserva estritamente:
--   1. admin_accounts / admin_users (credenciais de acesso ao Painel Admin)
--   2. professionals (profissionais cadastrados)
--   3. services (catálogo de serviços da empresa)
--   4. professional_services (vínculo de serviços e preços por profissional)
--   5. availability (grades de horários e intervalos de atendimento)
--   6. alembic_version (controle de migrações estruturais do banco)
--
-- Como executar na VPS:
--   docker exec -i <nome_container_postgres> psql -U agenda_user -d agenda_atende < scripts/reset_vps_database.sql
-- =============================================================================

BEGIN;

-- 1. Exibir contagem de registros antes da limpeza
DO $$
DECLARE
    v_users INT;
    v_appointments INT;
    v_payments INT;
    v_deliveries INT;
    v_logs INT;
    v_webhooks INT;
BEGIN
    SELECT COUNT(*) INTO v_deliveries FROM notification_deliveries;
    SELECT COUNT(*) INTO v_logs FROM notification_log;
    SELECT COUNT(*) INTO v_payments FROM payments;
    SELECT COUNT(*) INTO v_appointments FROM appointments;
    SELECT COUNT(*) INTO v_webhooks FROM webhook_events;
    SELECT COUNT(*) INTO v_users FROM users;

    RAISE NOTICE '--- CONTAGEM ANTES DA LIMPEZA ---';
    RAISE NOTICE 'notification_deliveries: %', v_deliveries;
    RAISE NOTICE 'notification_log:        %', v_logs;
    RAISE NOTICE 'payments:                %', v_payments;
    RAISE NOTICE 'appointments:            %', v_appointments;
    RAISE NOTICE 'webhook_events:          %', v_webhooks;
    RAISE NOTICE 'users:                   %', v_users;
END $$;

-- 2. Remoção em cascata lógica (ordem de integridade referencial)
DELETE FROM notification_deliveries;
DELETE FROM notification_log;
DELETE FROM payments;
DELETE FROM appointments;
DELETE FROM webhook_events;
DELETE FROM users;

-- 3. Reiniciar as sequências de auto-incremento (ID voltará ao 1)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'notification_deliveries_id_seq') THEN
        ALTER SEQUENCE notification_deliveries_id_seq RESTART WITH 1;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'notification_log_id_seq') THEN
        ALTER SEQUENCE notification_log_id_seq RESTART WITH 1;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'payments_id_seq') THEN
        ALTER SEQUENCE payments_id_seq RESTART WITH 1;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'appointments_id_seq') THEN
        ALTER SEQUENCE appointments_id_seq RESTART WITH 1;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'webhook_events_id_seq') THEN
        ALTER SEQUENCE webhook_events_id_seq RESTART WITH 1;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'users_id_seq') THEN
        ALTER SEQUENCE users_id_seq RESTART WITH 1;
    END IF;
END $$;

-- 4. Exibir status de validação após limpeza
DO $$
DECLARE
    v_users INT;
    v_appointments INT;
    v_payments INT;
    v_admins INT;
    v_profs INT;
    v_services INT;
BEGIN
    SELECT COUNT(*) INTO v_users FROM users;
    SELECT COUNT(*) INTO v_appointments FROM appointments;
    SELECT COUNT(*) INTO v_payments FROM payments;
    SELECT COUNT(*) INTO v_profs FROM professionals;
    SELECT COUNT(*) INTO v_services FROM services;

    RAISE NOTICE '--- CONTAGEM APÓS A LIMPEZA ---';
    RAISE NOTICE 'users:                   % (deve ser 0)', v_users;
    RAISE NOTICE 'appointments:            % (deve ser 0)', v_appointments;
    RAISE NOTICE 'payments:                % (deve ser 0)', v_payments;
    RAISE NOTICE 'professionals:           % (PRESERVADOS)', v_profs;
    RAISE NOTICE 'services:                % (PRESERVADOS)', v_services;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'admin_accounts') THEN
        SELECT COUNT(*) INTO v_admins FROM admin_accounts;
        RAISE NOTICE 'admin_accounts:          % (PRESERVADOS)', v_admins;
    END IF;
END $$;

COMMIT;

-- Reorganizar índices e liberar espaço no disco
VACUUM ANALYZE;

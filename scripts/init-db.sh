#!/bin/bash
# Script de inicialização do banco de dados - roda na primeira criação do container PostgreSQL

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Criar extensões úteis
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "pg_trgm";
    
    -- Configurações de performance
    ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
    ALTER SYSTEM SET track_activity_query_size = 2048;
    ALTER SYSTEM SET log_min_duration_statement = 1000;
    
    -- Usuário da aplicação já existe (criado via POSTGRES_USER)
    -- Conceder permissões necessárias
    GRANT ALL PRIVILEGES ON DATABASE "$POSTGRES_DB" TO "$POSTGRES_USER";
    GRANT ALL ON SCHEMA public TO "$POSTGRES_USER";
    
    -- Configurar timezone
    ALTER DATABASE "$POSTGRES_DB" SET timezone = 'America/Sao_Paulo';
EOSQL

echo "✅ Banco de dados inicializado com sucesso"
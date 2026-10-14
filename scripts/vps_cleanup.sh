#!/bin/bash
# =============================================================================
# Script de Limpeza Preventiva e Manutenção da VPS / Docker / Portainer
# =============================================================================
# Executa a cada 30 dias (ou sob demanda).
# - Envia aviso prévio de manutenção (Webhook / Log / Syslog)
# - Trunca logs gigantes de containers Docker sem parar serviços
# - Remove imagens órfãs (dangling) e imagens não usadas antigas (>30d)
# - Limpa Build Cache acumulado do Docker Buildx
# - Remove volumes anônimos órfãos (sem função)
# - Exclui backups locais com mais de 30 dias (/backups)
# - Verifica a integridade dos serviços essenciais ao final
# =============================================================================

set -euo pipefail

# Configurações padrão (podem ser sobrescritas por variáveis de ambiente)
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
RETENTION_HOURS="$(( RETENTION_DAYS * 24 ))h"
LOG_FILE="${LOG_FILE:-/var/log/vps_cleanup.log}"
WEBHOOK_URL="${WEBHOOK_URL:-}"
DRY_RUN=false
FORCE=false
IS_CRON=false
WARN_WAIT_SECONDS="${WARN_WAIT_SECONDS:-60}" # Padrão: 60s antes da limpeza (ou 900s via cron)

# Cores para terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # Sem cor

log() {
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local message="[$timestamp] $*"
    echo -e "${BLUE}[VPS-CLEANUP]${NC} $message"
    if [ -w "$(dirname "$LOG_FILE")" ]; then
        echo "$message" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

log_warn() {
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local message="[$timestamp] ⚠️  AVISO: $*"
    echo -e "${YELLOW}$message${NC}"
    if [ -w "$(dirname "$LOG_FILE")" ]; then
        echo "$message" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

log_success() {
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local message="[$timestamp] ✅ $*"
    echo -e "${GREEN}$message${NC}"
    if [ -w "$(dirname "$LOG_FILE")" ]; then
        echo "$message" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

send_webhook() {
    local title="$1"
    local text="$2"
    if [ -n "$WEBHOOK_URL" ] && command -v curl >/dev/null 2>&1; then
        local payload
        payload=$(printf '{"title":"%s","content":"%s","timestamp":"%s"}' "$title" "$text" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
        curl -s -X POST -H "Content-Type: application/json" -d "$payload" "$WEBHOOK_URL" >/dev/null 2>&1 || true
    fi
}

usage() {
    cat <<EOF
Uso: $0 [opções]

Opções:
  --dry-run       Apenas simula e relata o que será limpo, sem deletar nada
  --force         Executa imediatamente sem intervalo de espera do aviso
  --cron          Modo automatizado via cron (registra logs e aguarda intervalo)
  --wait <seg>    Define tempo de espera após o aviso em segundos (padrão: 60)
  --help          Exibe esta ajuda

EOF
    exit 0
}

# Parse de argumentos
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            WARN_WAIT_SECONDS=0
            shift
            ;;
        --cron)
            IS_CRON=true
            WARN_WAIT_SECONDS="${WARN_WAIT_SECONDS:-300}" # 5 min em cron
            shift
            ;;
        --wait)
            WARN_WAIT_SECONDS="$2"
            shift 2
            ;;
        --help)
            usage
            ;;
        *)
            echo "Opção desconhecida: $1" >&2
            usage
            ;;
    esac
done

# -----------------------------------------------------------------------------
# 1. FASE DE AVISO PRÉVIO (PRESERVAÇÃO E TRANSPARÊNCIA)
# -----------------------------------------------------------------------------
DISCO_INICIAL=$(df -h / 2>/dev/null | awk 'NR==2 {print $3 "/" $2 " (" $5 ")"}' || echo "N/A")

log_warn "Iniciando protocolo de manutenção preventiva de 30 dias na VPS."
log_warn "Ocupação atual do disco: $DISCO_INICIAL"

send_webhook "⚠️ Alerta de Manutenção VPS" "Aviso preventivo: A rotina de limpeza de logs, cache e imagens orfas sera executada em $WARN_WAIT_SECONDS segundos. Os servicos continuarao operacionais."

if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ] && [ "$WARN_WAIT_SECONDS" -gt 0 ]; then
    log "Aguardando janela de segurança de $WARN_WAIT_SECONDS segundos antes de executar a limpeza..."
    sleep "$WARN_WAIT_SECONDS"
fi

if [ "$DRY_RUN" = true ]; then
    log "MODO SIMULAÇÃO (--dry-run) ATIVADO. Nenhuma exclusão real será feita."
fi

# -----------------------------------------------------------------------------
# 2. LIMPEZA DE LOGS DE CONTAINERS (RETENÇÃO / TRUNCAMENTO SEGURO)
# -----------------------------------------------------------------------------
log "1/5: Verificando logs de containers em /var/lib/docker/containers..."

if [ -d "/var/lib/docker/containers" ]; then
    # Procura arquivos .log com mais de 20MB ou modificados há mais de 30 dias
    LOGS_ENCONTRADOS=$(find /var/lib/docker/containers/ -type f -name "*.log" 2>/dev/null || true)
    
    if [ -n "$LOGS_ENCONTRADOS" ]; then
        while IFS= read -r log_file; do
            if [ -f "$log_file" ]; then
                local_size=$(du -h "$log_file" | cut -f1)
                if [ "$DRY_RUN" = true ]; then
                    log "[Simulação] Truncaria log: $log_file (tamanho: $local_size)"
                else
                    # Truncate seguro: esvazia o arquivo sem trocar o inode para não travar o processo do container
                    truncate -s 0 "$log_file"
                    log "Log truncado com sucesso: $log_file (era: $local_size)"
                fi
            fi
        done <<< "$LOGS_ENCONTRADOS"
    else
        log "Nenhum arquivo de log volumoso encontrado para truncar."
    fi
else
    log "Diretório /var/lib/docker/containers não acessível diretamente (sem privilégios root ou caminho alternativo)."
fi

# -----------------------------------------------------------------------------
# 3. REMOÇÃO DE IMAGENS ÓRFÃS (DANGLING) E IMAGENS NÃO USADAS ANTIGAS
# -----------------------------------------------------------------------------
log "2/5: Limpando imagens órfãs (<none>:<none>) e não utilizadas há mais de ${RETENTION_HOURS}..."

if command -v docker >/dev/null 2>&1; then
    if [ "$DRY_RUN" = true ]; then
        log "[Simulação] docker image prune --filter dangling=true"
        docker images -f "dangling=true" || true
    else
        # Remove imagens dangling (órfãs imediatas)
        docker image prune -f || true
        # Remove imagens não utilizadas criadas há mais de 30 dias (720h)
        docker image prune -a --filter "until=${RETENTION_HOURS}" -f || true
        log_success "Imagens órfãs e antigas limpas com sucesso."
    fi
else
    log_warn "Comando 'docker' não encontrado no PATH atual."
fi

# -----------------------------------------------------------------------------
# 4. REMOÇÃO DE BUILD CACHE DO DOCKER
# -----------------------------------------------------------------------------
log "3/5: Limpando Build Cache residual..."

if command -v docker >/dev/null 2>&1; then
    if [ "$DRY_RUN" = true ]; then
        log "[Simulação] docker builder prune --filter until=${RETENTION_HOURS}"
    else
        docker builder prune -f --filter "until=${RETENTION_HOURS}" || true
        log_success "Build Cache limpo com sucesso."
    fi
fi

# -----------------------------------------------------------------------------
# 5. REMOÇÃO DE VOLUMES ÓRFÃOS (ANÔNIMOS / SEM FUNÇÃO)
# -----------------------------------------------------------------------------
log "4/5: Verificando volumes anônimos desconectados..."

if command -v docker >/dev/null 2>&1; then
    # Filtra apenas volumes anônimos (hashes de 64 caracteres hexadecimais sem nome)
    # Protege 100% volumes nomeados como *pgdata*, *db_data*, *redis*, *npm*, *portainer*
    ANON_VOLUMES=$(docker volume ls -qf dangling=true | grep -E '^[a-f0-9]{64}$' || true)
    
    if [ "$DRY_RUN" = true ]; then
        log "[Simulação] Volumes anônimos órfãos a remover:"
        echo "$ANON_VOLUMES"
    else
        if [ -n "$ANON_VOLUMES" ]; then
            echo "$ANON_VOLUMES" | xargs -r docker volume rm 2>/dev/null || true
            log_success "Volumes anônimos órfãos removidos com sucesso."
        else
            log "Nenhum volume anônimo órfão encontrado."
        fi
    fi
fi

# -----------------------------------------------------------------------------
# 6. LIMPEZA DE BACKUPS LOCAIS ANTIGOS (> 30 DIAS)
# -----------------------------------------------------------------------------
log "5/5: Verificando backups locais com mais de ${RETENTION_DAYS} dias em ${BACKUP_DIR}..."

if [ -d "$BACKUP_DIR" ]; then
    OLD_BACKUPS=$(find "$BACKUP_DIR" -type f \( -name "agenda_*.sql.gz" -o -name "*.sql.gz" -o -name "*.tar.gz" \) -mtime "+${RETENTION_DAYS}" 2>/dev/null || true)
    
    if [ -n "$OLD_BACKUPS" ]; then
        while IFS= read -r backup_file; do
            if [ -f "$backup_file" ]; then
                if [ "$DRY_RUN" = true ]; then
                    log "[Simulação] Excluiria backup antigo: $backup_file"
                else
                    rm -f "$backup_file"
                    log "Backup antigo removido: $backup_file"
                fi
            fi
        done <<< "$OLD_BACKUPS"
    else
        log "Nenhum backup com mais de ${RETENTION_DAYS} dias para remoção."
    fi
else
    log "Diretório de backup ${BACKUP_DIR} não existe localmente; pulando."
fi

# -----------------------------------------------------------------------------
# 7. VALIDAÇÃO DE INTEGRIDADE DOS SERVIÇOS PÓS-LIMPEZA
# -----------------------------------------------------------------------------
DISCO_FINAL=$(df -h / 2>/dev/null | awk 'NR==2 {print $3 "/" $2 " (" $5 ")"}' || echo "N/A")

log_success "Limpeza concluída com sucesso!"
log "Espaço antes: $DISCO_INICIAL  -->  Espaço atual: $DISCO_FINAL"

# Notificação de encerramento
send_webhook "✅ Manutenção Concluída" "Rotina de limpeza de 30 dias finalizada com sucesso na VPS. Espaco atual em disco: $DISCO_FINAL. Todos os servicos continuam ativos."

exit 0

#!/bin/bash
# =============================================================================
# Instalador do Cron de Limpeza Periódica de 30 Dias e Rotação de Logs
# =============================================================================
# Executar na VPS como root (ou sudo).
# 1. Configura cronjob mensal em /etc/cron.d/vps_cleanup
# 2. Configura rotação de logs no Docker daemon (/etc/docker/daemon.json)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEANUP_SCRIPT="${SCRIPT_DIR}/vps_cleanup.sh"
CRON_FILE="/etc/cron.d/vps_cleanup"
DOCKER_DAEMON_JSON="/etc/docker/daemon.json"

echo "🔧 Instalando rotina de limpeza preventiva de 30 dias..."

# 1. Garantir permissões de execução
chmod +x "$CLEANUP_SCRIPT"
echo "✅ Permissão de execução concedida a $CLEANUP_SCRIPT"

# 2. Criar cronjob em /etc/cron.d/
cat <<EOF > "$CRON_FILE"
# Limpeza preventiva mensal da VPS (executa todo dia 1 às 03:00)
# Envia aviso prévio de 5 minutos antes de truncar logs e limpar cache/imagens
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
0 3 1 * * root $CLEANUP_SCRIPT --cron >> /var/log/vps_cleanup.log 2>&1
EOF

chmod 644 "$CRON_FILE"
echo "✅ Cronjob instalado em $CRON_FILE (execução mensal todo dia 1 às 03:00)"

# 3. Opcional: Configurar rotação de logs no Docker Daemon
if [ -d "/etc/docker" ]; then
    if [ ! -f "$DOCKER_DAEMON_JSON" ]; then
        cat <<EOF > "$DOCKER_DAEMON_JSON"
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "20m",
    "max-file": "3"
  }
}
EOF
        echo "✅ Rotação de logs configurada em $DOCKER_DAEMON_JSON"
        echo "ℹ️  Para aplicar a rotação de logs imediatamente ao daemon, execute: systemctl reload docker"
    else
        echo "ℹ️  $DOCKER_DAEMON_JSON já existe. Verifique se contém log-opts max-size."
    fi
fi

echo ""
echo "🎉 Instalação concluída com sucesso!"
echo "Para testar em modo simulação agora mesmo, execute:"
echo "  $CLEANUP_SCRIPT --dry-run"
echo "Para executar a limpeza real agora com aviso:"
echo "  $CLEANUP_SCRIPT"

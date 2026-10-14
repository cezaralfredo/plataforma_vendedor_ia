---
name: vps-cleanup
description: Rotina de manutenção preventiva e limpeza periódica a cada 30 dias na VPS (truncamento seguro de logs de containers, remoção de imagens órfãs, limpeza de build cache, volumes anônimos e backups antigos, com aviso prévio para preservação dos serviços).
---

# VPS Cleanup & Maintenance Skill

Esta skill define o protocolo de manutenção periódica (ciclo de 30 dias) para servidores e VPS rodando Docker, Portainer, Nginx Proxy Manager e banco de dados PostgreSQL/Redis.

## Princípios de Segurança e Preservação

Ao executar qualquer limpeza no host, as seguintes regras são estritamente observadas:
1. **Aviso Prévio Obrigatório:** Antes de qualquer ação destrutiva, é emitido aviso via log e/ou Webhook para garantir transparência e tempo de intervenção se necessário.
2. **Preservação de Volumes de Banco de Dados:** NUNCA apagar volumes nomeados de bancos de dados ativos (`agenda_db_data`, `agenda_pgdata`, dados do Redis, `npm_data`, `portainer_data`). Apenas volumes anônimos órfãos (`docker volume prune`) são removidos.
3. **Truncamento de Logs sem Parar Serviços:** Arquivos de log (`*-json.log`) de containers nunca são apagados bruscamente (`rm`), mas sim truncados (`truncate -s 0`), preservando os descritores de arquivo (file descriptors) dos processos em execução no container.
4. **Retenção de 30 Dias:** Backups locais e imagens em desuso são preservados se criados dentro da janela de 30 dias (720 horas).

---

## Estrutura de Arquivos

* [`scripts/vps_cleanup.sh`](file:///e:/Projetos/plataforma_atende_agenda/scripts/vps_cleanup.sh): Script principal de limpeza e auditoria com suporte a `--dry-run`, `--force` e `--cron`.
* [`scripts/install_cleanup_cron.sh`](file:///e:/Projetos/plataforma_atende_agenda/scripts/install_cleanup_cron.sh): Script instalador para configurar a execução mensal no Linux (`/etc/cron.d/vps_cleanup`) e rotação de logs no `/etc/docker/daemon.json`.
* [`scripts/reset_vps_database.sql`](file:///e:/Projetos/plataforma_atende_agenda/scripts/reset_vps_database.sql): Script de wipe permanente de clientes e agendamentos de teste para alinhamento com Asaas.
* [`scripts/maintenance_cleanup.sql`](file:///e:/Projetos/plataforma_atende_agenda/scripts/maintenance_cleanup.sql): Script SQL de manutenção periódica (purga de outbox entregue, webhooks antigos e cancelamentos a cada 30 dias).

---

## Como Executar

### 1. Testar em Modo Simulação (Dry-Run)
Para inspecionar o que seria limpo sem remover nenhum dado real:
```bash
bash scripts/vps_cleanup.sh --dry-run
```

### 2. Executar Limpeza Imediata com Aviso de 60s
```bash
bash scripts/vps_cleanup.sh
```

### 3. Executar Imediatamente sem Aguardar Janela de Aviso
```bash
bash scripts/vps_cleanup.sh --force
```

### 4. Instalar o Agendamento Automático de 30 em 30 Dias na VPS
Execute na VPS (com permissões de root/sudo):
```bash
sudo bash scripts/install_cleanup_cron.sh
```

---

## Checklist de Verificação Pós-Execução

Após a execução, confirme:
1. **Espaço em disco:** `df -h /` (confirmar aumento do espaço livre).
2. **Saúde dos containers:** `docker ps` (verificar se todas as Stacks permanecem ativas).
3. **Endpoint de saúde da aplicação:** `curl https://agenda.anauedesign.com.br/health` deve responder `{"status":"ok"}`.
4. **Conexão ao banco:** `curl https://agenda.anauedesign.com.br/ready` deve responder `{"status":"ready"}`.

# Deploy no Portainer - Guia Completo

> Operação endurecida: aplique migrações antes do tráfego, configure `APP_TIMEZONE`, valide `/ready` e implante também as imagens `-backup` e `-mcp-gateway` quando usar Hermes. API e métricas usam Bearer; o painel usa Basic.

> **Arquitetura**: Traefik (SSL auto) + PostgreSQL + API (FastAPI) + Backup + Watchtower
> **Registry**: GHCR (GitHub Container Registry) via GitHub Actions

---

## 📋 Pré-requisitos

| Item | Versão Mínima |
|------|---------------|
| Portainer | 2.20+ |
| Docker Engine | 24.0+ |
| Docker Compose | v2.20+ (plugin) |
| Domínio | `api.seudominio.com` com DNS A record → IP da VPS |
| GitHub | Repo com Actions habilitado + GHCR |

---

## 🔐 1. Criar Secrets no Portainer

**Portainer UI → Secrets → Add Secret** (criar estes 5):

| Secret Name | Valor | Gerar com |
|-------------|-------|-----------|
| `postgres_password` | Senha forte (32 chars) | `openssl rand -base64 24` |
| `api_key` | Chave da API (64 chars) | `openssl rand -base64 32` |
| `admin_api_key` | Chave do Admin Panel (64 chars) | `openssl rand -base64 32` |
| `asaas_api_key` | Key produção do Asaas | Painel Asaas → Minha Conta → API |
| `asaas_webhook_token` | Token do webhook (32 chars) | `openssl rand -base64 24` |

> ⚠️ **Não use `.env` no Portainer**. Use **Secrets** para tudo sensível.

---

## 🌐 2. Configurar DNS

```
Tipo: A
Nome: api
Valor: IP_DA_SUA_VPS
TTL: 300 (ou automático)

# Opcional - Dashboard Traefik
Tipo: A
Nome: traefik
Valor: IP_DA_SUA_VPS
```

> Aguarde propagação DNS (`dig api.seudominio.com` deve retornar o IP).

---

## 🐙 3. Configurar GitHub Actions + GHCR

### 3.1 Habilitar GitHub Container Registry
Repo → Settings → Actions → General → **Workflow permissions** → ✅ "Read and write permissions"

### 3.2 Adicionar Secrets no GitHub
Repo → Settings → Secrets → Actions → **New repository secret**:

| Secret | Valor |
|--------|-------|
| `PORTAINER_WEBHOOK_URL` | Webhook do Portainer (ver passo 5) |
| `VPS_HOST` | IP da VPS (fallback SSH) |
| `VPS_USER` | Usuário SSH (ex: `deploy`) |
| `VPS_SSH_KEY` | Chave privada SSH (fallback) |

### 3.3 Primeira build manual (opcional)
```bash
# Localmente, para testar a imagem
docker build -t ghcr.io/seu-user/plataforma_atende_agenda:test .
docker push ghcr.io/seu-user/plataforma_atende_agenda:test
```

---

## 📦 4. Criar Stack no Portainer

### 4.1 Portainer UI → Stacks → Add Stack
- **Name**: `agenda-atende`
- **Build method**: `Repository` (Git)
- **Repository URL**: `https://github.com/seu-user/plataforma_atende_agenda`
- **Reference**: `main` (branch)
- **Compose path**: `docker-compose.prod.yml`

### 4.2 Variáveis de Ambiente (Environment Variables)
Clique em **"Add from secret"** para cada uma:

| Variable | Value (from Secret) |
|----------|---------------------|
| `POSTGRES_PASSWORD_FILE` | `/run/secrets/postgres_password` |
| `API_KEY_FILE` | `/run/secrets/api_key` |
| `ADMIN_API_KEY_FILE` | `/run/secrets/admin_api_key` |
| `ASAAS_API_KEY_FILE` | `/run/secrets/asaas_api_key` |
| `ASAAS_WEBHOOK_TOKEN_FILE` | `/run/secrets/asaas_webhook_token` |

### 4.3 Variáveis de Ambiente Diretas (não-secretas)

| Variable | Value |
|----------|-------|
| `DOMAIN` | `api.seudominio.com` |
| `ACME_EMAIL` | `seu@email.com` |
| `TRAEFIK_DASHBOARD_AUTH` | `admin:$$apr1$$xxxx$$yyyy` (gerar abaixo) |
| `APP_NAME` | `Agenda Atende` |
| `DEBUG` | `false` |
| `ASAAS_BASE_URL` | `https://api.asaas.com/api/v3` |

### 4.4 Gerar `TRAEFIK_DASHBOARD_AUTH`
```bash
# Instalar apache2-utils se necessário
htpasswd -nb admin suasenhaforte
# Saída: admin:$apr1$xxx$yyy
# No Portainer, DOBRE os $: admin:$$apr1$$xxx$$yyy
```

### 4.5 Deploy
Clique em **"Deploy the stack"**. Aguarde ~3-5 min.

---

## ✅ 5. Verificar Deploy

### 5.1 Health Checks
```bash
# API
curl -H "X-Admin-Key: SUA_ADMIN_KEY" https://api.seudominio.com/health
# {"status":"ok"}

# Prontidão da API e do banco
curl https://api.seudominio.com/ready
# {"status":"ready"}

# Traefik Dashboard
# Acesse: https://traefik.seudominio.com/dashboard/
# Login: admin / suasenhaforte
```

Para a topologia Hermes, publique o gateway como imagem versionada, aponte o
subdomínio MCP para `mcp-gateway:8080` e valide `https://mcp.seudominio.com/ready`
antes de liberar agentes. Faça um teste de restauração de backup em ambiente
isolado periodicamente.

### 5.2 Verificar SSL
- Acesse `https://api.seudominio.com/docs` → Swagger UI deve carregar
- Ícone de cadeado verde no navegador

### 5.3 Testar Webhook Asaas
```bash
# No painel Asaas: Webhooks → Adicionar
# URL: https://api.seudominio.com/webhooks/asaas
# Eventos: PAYMENT_RECEIVED, PAYMENT_CONFIRMED, PAYMENT_OVERDUE, PAYMENT_REFUNDED, PAYMENT_CANCELLED
# Token: mesmo valor de ASAAS_WEBHOOK_TOKEN
```

### 5.4 Admin Panel
```bash
# Browser + ModHeader extension
# URL: https://api.seudominio.com/admin
# Header: X-Admin-Key: SUA_ADMIN_API_KEY
```

---

## 🔄 6. Atualizações Automáticas

### Opção A: Watchtower (já incluído no stack)
- Monitora GHCR a cada 5 min (`WATCHTOWER_POLL_INTERVAL=300`)
- Atualiza apenas containers com label `com.centurylinklabs.watchtower.enable=true`
- **Já configurado** no `docker-compose.prod.yml`

### Opção B: Portainer Webhook (recomendado para produção)
1. Portainer → Stacks → `agenda-atende` → **Webhooks** → Add webhook
2. Copie a URL gerada
3. GitHub → Settings → Secrets → `PORTAINER_WEBHOOK_URL` = URL copiada
4. Push na `main` → GitHub Actions builda → dispara webhook → Portainer faz pull + restart

---

## 💾 7. Backup e Restore

### 7.1 Backup Automático (já configurado)
- Roda diariamente às 03:00 (config `BACKUP_SCHEDULE=0 3 * * *`)
- Salva em `/backups` (volume local) + upload para S3/Wasabi/GDrive via rclone
- Retenção: 30 dias (`BACKUP_RETENTION_DAYS=30`)

### 7.2 Configurar rclone (Storage Remoto)
```bash
# 1. Na VPS, configure rclone interativamente
docker run -it --rm -v $(pwd)/rclone:/config/rclone rclone/rclone config

# 2. Copie rclone.conf para ./rclone/rclone.conf no repo
# 3. Git push → nova build → deploy automático
```

### 7.3 Restore Manual
```bash
# Listar backups
ls -la /backups/

# Restore (PARAR API ANTES!)
docker compose -f docker-compose.prod.yml stop api
gunzip -c /backups/agenda_agenda_atende_20260115_030000.sql.gz | \
  docker exec -i agenda_atende_pg psql -U agenda_user -d agenda_atende
docker compose -f docker-compose.prod.yml start api
```

---

## 🛡️ 8. Hardening de Segurança

| Camada | Configuração |
|--------|--------------|
| **Traefik** | Rate limit (100 req/s, burst 50), HTTPS only, HSTS |
| **API** | Admin key separada, CORS restrito, validação HMAC webhook |
| **PostgreSQL** | Senha via secret, apenas rede interna, sem porta exposta |
| **Secrets** | Portainer Secrets (não env), rotação trimestral |
| **Rede** | `agenda_network` isolada, sem exposição direta |
| **SSH VPS** | Key-only, fail2ban, porta não-padrão, usuário não-root |

---

## 📊 9. Monitoramento (Opcional)

### Adicionar ao stack (Prometheus + Grafana):
```yaml
  prometheus:
    image: prom/prometheus:v2.48
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    networks: [agenda_network]

  grafana:
    image: grafana/grafana:10.2
    environment:
      - GF_SECURITY_ADMIN_PASSWORD_FILE=/run/secrets/grafana_password
    volumes:
      - grafana_data:/var/lib/grafana
    networks: [agenda_network]
    secrets: [grafana_password]
```

- Scrape `api:8000/metrics` (já exposto pelo `prometheus-fastapi-instrumentator`)
- Dashboards: API latency, DB connections, HTTP errors, Asaas webhook success rate

---

## 🚨 10. Troubleshooting

| Problema | Solução |
|----------|---------|
| **SSL não emite** | Verifique DNS propagado, porta 80/443 abertas, ACME_EMAIL válido |
| **API não sobe** | `docker logs agenda_atende_api` → verifique migrações, secrets, DATABASE_URL |
| **Webhook Asaas falha** | Teste `curl -X POST https://api.seudominio.com/webhooks/asaas` |
| **Backup não roda** | `docker logs agenda_atende_backup` → verifique rclone.conf, credenciais S3 |
| **Traefik 404** | Labels do router devem bater com `Host(\`api.seudominio.com\`)` |

---

## 📝 11. Checklist Go-Live

- [ ] VPS provisionada + hardening SSH/firewall
- [ ] DNS `api.seudominio.com` → IP VPS propagado
- [ ] 5 Secrets criados no Portainer
- [ ] Stack deployada sem erros
- [ ] `https://api.seudominio.com/health` → `{"status":"ok"}`
- [ ] Swagger acessível em `/docs`
- [ ] Admin Panel acessível com `X-Admin-Key`
- [ ] Webhook Asaas configurado e testado (evento real)
- [ ] Pagamento PIX/boleto ponta a ponta validado
- [ ] Backup rodou e subiu para storage remoto
- [ ] Watchtower/Portainer webhook funcionando
- [ ] Documentação de runbook (rollback, incidentes) criada

---

## 🔗 Referências

- [Traefik v3 Docs](https://doc.traefik.io/traefik/)
- [Portainer Stacks](https://docs.portainer.io/start/stacks)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [rclone S3 Config](https://rclone.org/s3/)
- [Asaas Webhooks](https://docs.asaas.com/reference/webhooks)

---

*Última atualização: 2026-08-05*

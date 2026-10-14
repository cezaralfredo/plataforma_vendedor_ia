# Deploy em VPS com Docker Compose (Sem Portainer)

> Contrato atual: configure `APP_TIMEZONE`, use a URL Asaas `/v3`, publique as imagens principal e `-backup`, aplique a migração antes de iniciar e valide o serviço por `/ready`. O painel usa Basic; API e métricas usam Bearer.

> **Arquitetura**: Traefik (SSL auto) + PostgreSQL + API (FastAPI) + Backup + Watchtower
> **Registry**: GHCR (GitHub Container Registry) via GitHub Actions ou build local

---

## 📋 Pré-requisitos

| Item | Versão Mínima |
|------|---------------|
| Docker Engine | 24.0+ |
| Docker Compose | v2.20+ (plugin) |
| Domínio | `api.seudominio.com` com DNS A record → IP da VPS |
| GitHub | Repo com Actions habilitado + GHCR (opcional) |

---

## 🐳 1. Preparar a VPS

```bash
# Atualizar sistema
apt update && apt upgrade -y

# Instalar Docker + Compose plugin
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER
newgrp docker

# Instalar utilitários
apt install -y git curl htop ufw fail2ban

# Configurar firewall (UFW)
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (Let's Encrypt challenge)
ufw allow 443/tcp   # HTTPS
ufw enable
```

---

## 🌐 2. Configurar DNS

```
Tipo: A
Nome: api
Valor: IP_DA_SUA_VPS
TTL: 300

# Opcional - Dashboard Traefik
Tipo: A
Nome: traefik
Valor: IP_DA_SUA_VPS
```

> Aguarde propagação: `dig api.seudominio.com`

---

## 📁 3. Clonar Repositório e Configurar

```bash
# Clonar
git clone https://github.com/seu-user/plataforma_atende_agenda /opt/agenda-atende
cd /opt/agenda-atende

# Criar .env.prod a partir do exemplo
cp .env.prod.example .env.prod

# EDITAR .env.prod com valores REAIS
vim .env.prod
```

### 3.1 Gerar Secrets (execute na VPS)

```bash
# PostgreSQL
openssl rand -base64 24
# → POSTGRES_PASSWORD

# API Keys
openssl rand -base64 32
# → API_KEY
openssl rand -base64 32
# → ADMIN_API_KEY

# Traefik Dashboard Auth
htpasswd -nb admin suasenhaforte
# → TRAEFIK_DASHBOARD_AUTH (copie EXATO: admin:$apr1$xxx$yyy)

# Asaas (pegue no painel Asaas produção)
# → ASAAS_API_KEY, ASAAS_WEBHOOK_TOKEN
```

### 3.2 Configurar rclone (para backup remoto)

```bash
mkdir -p /opt/agenda-atende/rclone

# Opção A: Configurar interativamente
docker run -it --rm -v /opt/agenda-atende/rclone:/config/rclone rclone/rclone config

# Opção B: Copiar rclone.conf.example e editar
cp /opt/agenda-atende/rclone/rclone.conf.example /opt/agenda-atende/rclone/rclone.conf
vim /opt/agenda-atende/rclone/rclone.conf
```

---

## 🐙 4. Opções de Imagem Docker

### Opção A: Usar GHCR (GitHub Actions builda automaticamente)
- Push na `main` → GitHub Actions builda multi-arch → push para `ghcr.io/seu-user/plataforma_atende_agenda:latest`
- **Não precisa buildar na VPS**

### Opção B: Build Local na VPS
```bash
# Buildar imagem
docker build -t agenda-atende:local .

# Tag para registry local (opcional)
docker tag agenda-atende:local localhost:5000/agenda-atende:local
```

> No `docker-compose.vps.yml`, a imagem usa `${REGISTRY:-ghcr.io}/${{ github.repository }}:latest`.
> Para build local, sobrescreva: `image: agenda-atende:local`

---

## 🚀 5. Deploy

```bash
cd /opt/agenda-atende

# Subir stack
docker compose -f docker-compose.vps.yml --env-file .env.prod up -d

# Ver logs
docker compose -f docker-compose.vps.yml logs -f

# Ver status
docker compose -f docker-compose.vps.yml ps
```

---

## ✅ 6. Verificar Deploy

```bash
# Health check API
curl -H "X-Admin-Key: SUA_ADMIN_API_KEY" https://api.seudominio.com/health
# {"status":"ok"}

# Traefik Dashboard
# https://traefik.seudominio.com/dashboard/
# Login: admin / suasenhaforte

# Swagger UI
# https://api.seudominio.com/docs

# Admin Panel
# https://api.seudominio.com/admin
# Header: X-Admin-Key: SUA_ADMIN_API_KEY
```

---

## 🔄 7. Atualizações

### Via GitHub Actions + Watchtower (Automático)
- Watchtower já incluído no stack (`WATCHTOWER_POLL_INTERVAL=300`)
- Push na `main` → GHCR nova imagem → Watchtower detecta → restart automático

### Manual (Build Local)
```bash
cd /opt/agenda-atende
git pull origin main
docker compose -f docker-compose.vps.yml build api
docker compose -f docker-compose.vps.yml up -d --force-recreate api
docker compose -f docker-compose.vps.yml exec -T api alembic upgrade head
```

### Manual (Pull GHCR)
```bash
cd /opt/agenda-atende
docker compose -f docker-compose.vps.yml pull api
docker compose -f docker-compose.vps.yml up -d --force-recreate api
docker compose -f docker-compose.vps.yml exec -T api alembic upgrade head
```

---

## 💾 8. Backup e Restore

### Backup Automático (já configurado)
- Diário às 03:00 (`BACKUP_SCHEDULE=0 3 * * *`)
- Local: `/opt/agenda-atende/backups/`
- Remoto: S3/Wasabi/GDrive via rclone (se configurado)
- Retenção: 30 dias

### Backup Manual
```bash
docker compose -f docker-compose.vps.yml exec backup /backup.sh
```

### Restore
```bash
# PARAR API
docker compose -f docker-compose.vps.yml stop api

# Restore (exemplo)
gunzip -c /opt/agenda-atende/backups/agenda_agenda_atende_20260115_030000.sql.gz | \
  docker exec -i agenda_atende_pg psql -U agenda_user -d agenda_atende

# INICIAR API
docker compose -f docker-compose.vps.yml start api
```

---

## 🛡️ 9. Hardening Adicional

```bash
# Fail2ban para SSH
cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
# Editar jail.local: [sshd] enabled = true, maxretry = 3
systemctl restart fail2ban

# SSH hardening (/etc/ssh/sshd_config)
# PasswordAuthentication no
# PermitRootLogin no
# Port 2222 (não-padrão)
systemctl restart ssh

# Atualizações automáticas de segurança
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

---

## 📊 10. Monitoramento Básico

```bash
# Ver recursos
docker stats

# Logs da API
docker compose -f docker-compose.vps.yml logs -f api --tail=100

# Logs do Traefik
docker compose -f docker-compose.vps.yml logs -f traefik --tail=50

# Logs do Backup
docker compose -f docker-compose.vps.yml logs -f backup --tail=50
```

---

## 🚨 11. Troubleshooting

| Problema | Solução |
|----------|---------|
| **SSL não emite** | DNS propagado? Portas 80/443 abertas? `ACME_EMAIL` válido? `docker logs traefik` |
| **API não sobe** | `docker logs api` → migrações? secrets no `.env.prod`? `DATABASE_URL` correto? |
| **Webhook Asaas falha** | URL correta no painel Asaas? Token bate? `docker logs api` |
| **Backup não roda** | `docker logs backup` → rclone.conf existe? Credenciais S3 válidas? |
| **Traefik 404** | Labels batem com `Host(\`api.seudominio.com\`)`? DNS aponta pra VPS? |

---

## 📝 12. Checklist Go-Live

- [ ] VPS provisionada + hardening SSH/firewall/fail2ban
- [ ] DNS `api.seudominio.com` → IP VPS propagado
- [ ] `.env.prod` preenchido com TODOS valores reais
- [ ] rclone configurado (se backup remoto)
- [ ] Stack subida: `docker compose -f docker-compose.vps.yml --env-file .env.prod up -d`
- [ ] `https://api.seudominio.com/health` → `{"status":"ok"}`
- [ ] Swagger acessível em `/docs`
- [ ] Admin Panel acessível com `X-Admin-Key`
- [ ] Webhook Asaas configurado e testado
- [ ] Pagamento PIX/boleto ponta a ponta validado
- [ ] Backup rodou (verificar `/backups/` e storage remoto)
- [ ] Watchtower funcionando (ou deploy manual documentado)

---

## 🔗 Diferença para Portainer

| Aspecto | Portainer | VPS + Docker Compose |
|---------|-----------|---------------------|
| **Secrets** | UI Portainer (encrypted) | `.env.prod` arquivo local |
| **Deploy** | UI Stacks | CLI `docker compose up` |
| **Atualizações** | Webhook / Watchtower | Watchtower / Manual |
| **SSL** | Traefik (igual) | Traefik (igual) |
| **Backup** | Igual | Igual |
| **Segurança** | Secrets não tocam disco | `.env.prod` no disco (chmod 600) |

---

## 🔐 Dica de Segurança Extra (VPS)

```bash
# Proteger .env.prod
chmod 600 /opt/agenda-atende/.env.prod
chown root:root /opt/agenda-atende/.env.prod

# Proteger rclone.conf
chmod 600 /opt/agenda-atende/rclone/rclone.conf
```

---

*Para deploy com Portainer, veja `DEPLOY_PORTAINER.md`*

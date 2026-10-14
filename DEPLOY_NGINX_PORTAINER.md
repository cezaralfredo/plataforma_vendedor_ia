# Deploy com Nginx no Portainer

> Operação endurecida: aplique migrações antes do tráfego, configure `APP_TIMEZONE`, valide `/ready` e implante também a imagem `-backup`. API e métricas usam Bearer; o painel usa Basic.

Use `docker-compose.nginx.yml` como uma Stack independente no Portainer. Ela substitui o Traefik por Nginx e emite/renova certificados Let's Encrypt automaticamente.

## Antes de criar a Stack

1. Aponte o DNS do domínio para a VPS e libere as portas 80 e 443.
2. Publique a imagem da API no registry e informe `REGISTRY` e `GITHUB_REPOSITORY` nas variáveis da Stack.
3. Crie os secrets externos no ambiente Docker: `postgres_password`, `api_key`, `admin_api_key`, `asaas_api_key` e `asaas_webhook_token`.
4. Cadastre ao menos estas variáveis no Portainer:

```env
DOMAIN=api.seudominio.com
ACME_EMAIL=seu@email.com
APP_NAME=Agenda Atende
ASAAS_BASE_URL=https://api.asaas.com/api/v3
REGISTRY=ghcr.io
GITHUB_REPOSITORY=cezaralfredo/plataforma_atende_agenda
```

## Operação

Depois de subir, a API deve responder em `https://DOMAIN/health`. Os certificados são mantidos nos volumes `nginx_certs` e `acme_data`; não os remova em atualizações normais da Stack.

O Nginx encaminha `/api`, `/admin`, `/mcp`, `/webhooks`, `/docs` e os demais caminhos para a API. O painel administrativo continua exigindo o cabeçalho `X-Admin-Key`.

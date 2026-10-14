# Deploy no Portainer Community Edition com Nginx Proxy Manager e Neon

> Este procedimento altera somente a topologia com banco PostgreSQL externo. Não execute nenhuma ação no Portainer sem a janela de mudança aprovada.

Use exclusivamente `docker-compose.portainer-neon.yml` para a topologia externa Neon. A variante com PostgreSQL local permanece documentada em [DEPLOY_PORTAINER_NPM.md](DEPLOY_PORTAINER_NPM.md).

## Pré-requisitos de mudança

1. Obtenha `IMAGE_TAG` a partir do build de imagem bem-sucedido na branch `master`; não use `latest`.
2. Verifique que existe um backup ou ponto de restauração do Neon antes de mudar a Stack.
3. Crie primeiro uma credencial de substituição para o banco e mantenha a credencial anterior válida durante todo o rollout.
4. Não remova o volume PostgreSQL antigo durante este rollout.

## Variáveis da Stack

No Portainer, crie ou atualize as variáveis na tabela de ambiente da Stack. Informe `DATABASE_URL` somente nessa tabela, nunca embutida no editor do Compose. O valor de `DATABASE_URL` deve começar exatamente com `postgresql+psycopg://`, pois a aplicação usa Psycopg 3.

Cadastre os valores obrigatórios: `IMAGE_TAG`, `MCP_GATEWAY_IMAGE_TAG`, `DATABASE_URL`, `API_KEY`, `ADMIN_API_KEY`, `ASAAS_API_KEY` e `ASAAS_WEBHOOK_TOKEN`.

Quando necessário, ajuste os valores opcionais: `REGISTRY`, `GITHUB_REPOSITORY`, `APP_NAME`, `APP_TIMEZONE`, `ASAAS_BASE_URL` e `NPM_NETWORK`.

**MCP Gateway (para Hermes externo):**
- `MCP_GATEWAY_KEY=chave-forte-para-gateway-hermes`
- `MCP_GATEWAY_IMAGE_TAG=sha-da-mesma-publicacao-da-api`

O Docker Standalone não protege variáveis de ambiente como Docker secrets: seus valores permanecem visíveis para administradores do Portainer e por inspeção do container. Controle o acesso administrativo e faça a rotação de credenciais após a mudança.

## Deploy e validação

1. Crie ou atualize a Stack usando `docker-compose.portainer-neon.yml` e as variáveis já cadastradas.
2. Confirme a conclusão das migrações no log inicial do container.
3. No Nginx Proxy Manager, mantenha o Proxy Host apontando para `agenda-api` na porta `8000` pela rede externa `npm`.
4. **Adicione segundo Proxy Host para MCP Gateway:**
   - Domain Names: `mcp.seudominio.com`
   - Scheme: `http`
   - Forward Hostname / IP: `mcp-gateway`
   - Forward Port: `8080`
   - SSL: solicite certificado Let's Encrypt e force SSL.
5. Valide:
   - `https://api.seudominio.com/ready` — API principal
   - `https://mcp.seudominio.com/ready` — MCP Gateway e API interna
   - Uma chamada JSON-RPC `tools/list` no domínio MCP, usando `X-Gateway-Key`.
   - Autenticação da API, MCP, pagamentos e webhooks antes de encerrar a mudança.

## Hermes + MCP Gateway

1. Configure `~/.hermes/config.yaml` baseado em `hermes/config.yaml.example`:
   ```yaml
   gateway:
     base_url: "https://mcp.seudominio.com"
     headers:
       X-Gateway-Key: "mesmo-valor-do-MCP_GATEWAY_KEY"
   ```

2. Perfis Hermes em `hermes/profiles/` já usam toolset `gateway` (não `mcp_tools`).

3. Execute: `hermes run --profile orquestrador`

## Rollback

Se a validação falhar, restaure o `IMAGE_TAG` anterior e a configuração anterior da Stack. Mantenha o volume PostgreSQL antigo intacto; ele é proibido de ser removido durante este rollout.

Registre o resultado de um teste periódico de restauração do ponto de
recuperação do Neon em banco isolado; confirme dados, migrações e `/ready`
antes de considerá-lo recuperável.

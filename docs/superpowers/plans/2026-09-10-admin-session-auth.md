# Autenticação por Sessão do Painel Administrativo — Plano de Implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIO: use `superpowers:subagent-driven-development` (recomendado) ou `superpowers:executing-plans` para implementar este plano tarefa a tarefa. Os passos usam a sintaxe de checklist (`- [ ]`) para acompanhamento.

**Objetivo:** substituir a autenticação HTTP Basic do navegador por uma conta administrativa persistida, login por formulário, sessão segura, troca de senha e recuperação local dentro de cada instalação da empresa.

**Arquitetura:** uma conta singleton é criada no banco na primeira inicialização a partir de variáveis secretas. O painel usa cookie de sessão assinado, com versão de autenticação e token CSRF. A API técnica mantém `X-Admin-Key`, mas HTTP Basic deixa de ser aceito. Trocas ou recuperação de senha incrementam a versão da conta e invalidam todas as sessões existentes.

**Tecnologias:** FastAPI, Starlette `SessionMiddleware`, SQLAlchemy/Alembic, Jinja2, `hashlib.scrypt`, `hmac`, pytest/TestClient e Docker Compose/Portainer.

**Especificação:** `docs/superpowers/specs/2026-09-10-admin-session-auth-design.md`

## Restrições globais

- Manter o escopo de uma única conta administrativa por instalação; não criar cadastro público, papéis, múltiplos administradores, e-mail de recuperação ou provedor externo.
- Nunca registrar, exibir em resposta ou salvar em repositório senhas, chaves de sessão ou chave de recuperação.
- Manter `ADMIN_API_KEY` exclusivamente para automações técnicas com `X-Admin-Key`; ele não pode ser uma senha aceita pelo navegador.
- Preservar sem mudanças o contrato público da API e o MCP; somente as rotas `/admin` passam a aceitar sessão de navegador.
- Usar `Secure=True` para cookies quando `DEBUG=false`, `HttpOnly=True`, `SameSite=Lax` e expiração de oito horas.
- Toda operação mutante autenticada por sessão exige `X-CSRF-Token`; chamadas com `X-Admin-Key` continuam permitidas sem CSRF, pois são clientes não baseados em cookie.
- Executar a migração antes de iniciar o servidor. O bootstrap só pode criar a conta quando a tabela estiver vazia; nunca pode sobrescrever uma senha já definida. Depois que a conta existir, `ADMIN_BOOTSTRAP_PASSWORD` pode ficar ausente.

---

## Task 1: Configuração, modelo persistente e migração

**Arquivos:**
- Criar: `app/models/admin_account.py`
- Modificar: `app/models/__init__.py`
- Modificar: `app/config.py`
- Criar: `app/admin/auth_service.py`
- Criar: `alembic/versions/<revision>_add_admin_accounts.py`
- Criar: `tests/test_admin_auth_service.py`

- [ ] Escrever primeiro os testes de unidade para `hash_password`, `verify_password`, `bootstrap_admin_account` e `record_failed_login`: hash nunca contém a senha em texto, a verificação é positiva/negativa, bootstrap é idempotente e cinco falhas bloqueiam por quinze minutos.
- [ ] Rodar `pytest tests/test_admin_auth_service.py -q` e confirmar que falha porque o modelo e o serviço ainda não existem.
- [ ] Acrescentar a `Settings` os campos `admin_username`, `admin_bootstrap_password`, `admin_session_secret` e `admin_recovery_key`. Em produção, exigir usuário não vazio, senha de bootstrap com ao menos 12 caracteres quando fornecida, e segredo de sessão/chave de recuperação com pelo menos 32 caracteres, recusando valores de exemplo. Manter `admin_api_key` como segredo técnico separado.
- [ ] Implementar `AdminAccount` como tabela `admin_accounts`, com `id` inteiro fixado em 1, `username` único, `password_hash`, `auth_version`, `failed_login_count`, `locked_until`, `created_at` e `updated_at`. Exportá-lo em `app/models/__init__.py` para que Alembic o descubra.
- [ ] Implementar em `app/admin/auth_service.py` as interfaces abaixo, usando apenas biblioteca padrão para o hash versionado e salgado. Se não houver conta no banco, bootstrap sem senha configurada falha o startup com mensagem operacional que não revela segredo; se já houver conta, a ausência da senha de bootstrap é aceita.

  ```python
  def hash_password(password: str) -> str: ...
  def verify_password(password: str, encoded_hash: str) -> bool: ...
  def bootstrap_admin_account(db: Session, settings: Settings) -> AdminAccount: ...
  def authenticate_admin(db: Session, username: str, password: str, now: datetime) -> AdminAccount | None: ...
  def change_admin_password(db: Session, account: AdminAccount, new_password: str) -> None: ...
  ```

  O formato do hash deve carregar versão, parâmetros, salt aleatório e derivado; comparações usam `hmac.compare_digest`. `authenticate_admin` incrementa falhas e define bloqueio até `now + 15 minutos` na quinta falha; sucesso zera contador e bloqueio.
- [ ] Criar a revisão Alembic a partir de `7e1c3a9d4b6f`, incluindo valores padrão seguros para `auth_version` e `failed_login_count`, índices/constraints necessários e downgrade que remove somente `admin_accounts`.
- [ ] Registrar no ciclo de startup de `create_app` uma chamada curta que abre `SessionLocal`, executa `bootstrap_admin_account` e sempre fecha a sessão. A migração continua no entrypoint e deve acontecer antes desse ciclo.
- [ ] Rodar os testes desta tarefa e `python -m alembic upgrade head` contra o banco de testes configurado; confirmar criação, reexecução idempotente e startup sem senha de bootstrap após conta existente.
- [ ] Fazer commit: `feat(auth): persist single admin account`.

## Task 2: Middleware de sessão e dependências de autorização

**Arquivos:**
- Modificar: `app/main.py`
- Modificar: `app/security.py`
- Criar: `tests/test_admin_session_security.py`

- [ ] Escrever testes de integração para: `/admin` redireciona anonimamente para `/admin/login`; `X-Admin-Key` válido ainda acessa uma rota técnica; `Authorization: Basic ...` é rejeitado sem `WWW-Authenticate: Basic`; sessão com `auth_version` desatualizada é recusada; POST por cookie sem CSRF recebe 403.
- [ ] Rodar `pytest tests/test_admin_session_security.py -q` e confirmar as falhas esperadas antes da implementação.
- [ ] Adicionar `SessionMiddleware` em `create_app`, com `secret_key=app_settings.admin_session_secret`, `max_age=8 * 60 * 60`, `https_only=not app_settings.debug`, `same_site="lax"` e cookie de nome próprio do painel.
- [ ] Substituir `_decode_basic_credentials` por um resolvedor de contexto administrativo que, nesta ordem, valida a chave técnica ou lê `admin_account_id`, `auth_version` e `csrf_token` da sessão. Ele consulta a conta atual no banco para validar a versão.
- [ ] Separar as dependências em `require_admin` (aceita sessão ou chave técnica, redireciona GET HTML anônimo ao login e retorna 401 JSON em API) e `require_admin_mutation` (aplica CSRF apenas para sessão). Expor o contexto autenticado para as rotas sem repetir consultas.
- [ ] Implementar `require_csrf_token(request, context)` com comparação constante entre o header e a sessão; erros não revelam o token nem detalhes sobre a conta.
- [ ] Rodar `pytest tests/test_admin_session_security.py tests/test_authentication.py -q` e corrigir os testes antigos para usar cabeçalho técnico, nunca Basic.
- [ ] Fazer commit: `feat(auth): secure admin session authorization`.

## Task 3: Fluxo de login, logout e recuperação local

**Arquivos:**
- Modificar: `app/admin/router.py`
- Criar: `app/admin/templates/login.html`
- Criar: `app/admin/templates/recover.html`
- Criar: `tests/test_admin_login_flow.py`

- [ ] Escrever testes para GET `/admin/login`, login correto, login incorreto com mensagem genérica, bloqueio após cinco tentativas, logout, recuperação com `ADMIN_RECOVERY_KEY` válida e recusa da chave inválida.
- [ ] Rodar `pytest tests/test_admin_login_flow.py -q` e confirmar que as rotas/templates ainda não existem.
- [ ] Criar `GET /admin/login` e `POST /admin/login`; o POST usa `authenticate_admin`, cria sessão somente após sucesso e redireciona a `/admin`. Rotas de login não usam a dependência de administração.
- [ ] Criar `POST /admin/logout`, limpando a sessão e redirecionando a `/admin/login`.
- [ ] Criar `GET /admin/recover` e `POST /admin/recover`. O formulário recebe usuário, chave de recuperação, nova senha e confirmação. Respostas de erro permanecem genéricas; em sucesso chama `change_admin_password`, limpa a sessão e leva ao login.
- [ ] Em cada template novo, usar mensagens claras em português do Brasil, `autocomplete` apropriado, campos de senha sem preenchimento em valor e sem revelar qual credencial falhou.
- [ ] Rodar os testes da tarefa mais `pytest tests/test_admin_dashboard.py -q` e confirmar que login válido estabelece acesso ao painel.
- [ ] Fazer commit: `feat(auth): add admin login recovery and logout`.

## Task 4: Troca de senha no painel e revogação de sessões

**Arquivos:**
- Modificar: `app/admin/router.py`
- Modificar: `app/admin/templates/base.html`
- Criar: `app/admin/templates/password.html`
- Criar: `tests/test_admin_password_management.py`

- [ ] Escrever testes para formulário de troca: exige senha atual, nova senha de ao menos 12 caracteres, confirmação igual, CSRF válido; após sucesso a sessão anterior torna-se inválida e é criada uma sessão nova; outra sessão do mesmo administrador é revogada.
- [ ] Rodar `pytest tests/test_admin_password_management.py -q` e confirmar falhas iniciais.
- [ ] Criar `GET /admin/password` e `POST /admin/password`. No POST, verificar senha atual, política e confirmação, chamar `change_admin_password`, reinicializar a sessão com a nova `auth_version` e token CSRF e redirecionar com confirmação sem carregar dados sensíveis.
- [ ] Adicionar no rodapé do menu lateral links acessíveis para “Alterar senha” e “Sair”, sendo sair um formulário POST com token CSRF.
- [ ] Garantir que recuperação e troca incrementam `auth_version` exatamente uma vez, deixando qualquer cookie antigo incapaz de executar um GET ou POST protegido.
- [ ] Rodar os testes desta tarefa e os testes das tarefas 2 e 3.
- [ ] Fazer commit: `feat(auth): let admin change password in panel`.

## Task 5: CSRF nas telas existentes e compatibilidade da chave técnica

**Arquivos:**
- Modificar: `app/admin/router.py`
- Modificar: `app/admin/templates/base.html`
- Modificar: `app/admin/templates/appointments.html`
- Modificar: `app/admin/templates/appointment_detail.html`
- Modificar: `app/admin/templates/payments.html`
- Modificar: `app/admin/templates/professionals.html`
- Modificar: `app/admin/templates/professional_detail.html`
- Modificar: `app/admin/templates/services.html`
- Modificar: `tests/test_admin_csrf.py`
- Modificar: `tests/test_admin_appointments_management.py`
- Modificar: `tests/test_admin_payments.py`
- Modificar: `tests/test_admin_professional_management.py`
- Modificar: `tests/test_admin_services_page.py`

- [ ] Escrever testes que cubram ao menos um POST, PUT e DELETE de cada área administrativa: sessão sem token falha em 403; a mesma sessão com token válido funciona; `X-Admin-Key` continua funcionando sem token.
- [ ] Rodar os testes novos e confirmar falhas antes de alterar dependências das rotas mutantes.
- [ ] Aplicar `require_admin_mutation` a todas as rotas POST, PUT e DELETE de `/admin`; manter `require_admin` em GETs.
- [ ] Injetar `csrf_token` em um `<meta name="csrf-token">` no template base. Criar um wrapper JavaScript comum que acrescenta `X-CSRF-Token` somente às requisições mutantes; substituir chamadas `fetch` mutantes em cada tela por esse wrapper.
- [ ] Acrescentar `credentials: "same-origin"` nas chamadas administrativas, preservando os cabeçalhos de conteúdo e tratamento de resposta existentes.
- [ ] Atualizar os testes legados para autenticar por cabeçalho técnico quando não estiverem testando o navegador; adicionar o header CSRF aos testes de sessão.
- [ ] Rodar os testes das telas administrativas e verificar que ações de agendamento, pagamento, profissional e serviço continuam com os mesmos códigos e corpos de resposta.
- [ ] Fazer commit: `feat(auth): protect admin mutations with csrf`.

## Task 6: Documentação, stack Portainer e validação final

**Arquivos:**
- Modificar: `.env.example`
- Modificar: `.env.prod.example`
- Modificar: `docker-compose.portainer-npm.yml`
- Modificar: `docker-compose.portainer-neon.yml`
- Modificar: `docker-compose.prod.yml`
- Modificar: `docker-compose.vps.yml`
- Modificar: `README.md`
- Modificar: `tests/test_deployment_config.py`

- [ ] Escrever testes de configuração para exigir as quatro novas variáveis/segredos de autenticação de navegador nas stacks aplicáveis e confirmar que README não documenta HTTP Basic para `/admin`.
- [ ] Rodar `pytest tests/test_deployment_config.py -q` e confirmar que falha antes da documentação/configuração.
- [ ] Documentar `ADMIN_USERNAME`, `ADMIN_BOOTSTRAP_PASSWORD`, `ADMIN_SESSION_SECRET` e `ADMIN_RECOVERY_KEY`: geração segura, finalidade, quando retirar o bootstrap, e procedimento sem exposição pelo Portainer. A documentação deve enfatizar que `ADMIN_SESSION_SECRET` precisa permanecer estável em rollback.
- [ ] Incluir nas composições Portainer usadas em produção as variáveis obrigatórias, com placeholders que falham de modo explícito se ausentes. Nas composições que usam Docker Secrets, acrescentar os arquivos/segredos correspondentes e o carregamento via entrypoint/configuração, sem incluir seus valores no YAML.
- [ ] Remover qualquer instrução que diga que a senha do navegador é `ADMIN_API_KEY` ou que recomende HTTP Basic. Manter orientação separada apenas para automações técnicas com `X-Admin-Key`.
- [ ] Validar `docker compose -f docker-compose.portainer-npm.yml config` usando valores descartáveis exclusivamente no ambiente de teste, seguido de `pytest tests/test_deployment_config.py -q`.
- [ ] Rodar a suíte integral: `pytest -q`, `ruff check app tests`, `python -m alembic upgrade head` num banco PostgreSQL de teste e o teste manual com TestClient: bootstrap → login → CRUD protegido → troca de senha → cookie antigo rejeitado → recuperação → logout.
- [ ] Fazer commit: `docs(auth): document session-based admin access`.

## Validação de publicação

Após os commits e antes de abrir o Pull Request:

1. Revisar o diff garantindo que não há nenhum segredo, cookie ou valor de senha em arquivo versionado ou em logs de teste.
2. Abrir Pull Request contra `codex/admin-management`, associando esta especificação e o plano.
3. Após aprovação e merge, publicar a imagem rastreável e atualizar a stack no Portainer com os quatro valores secretos. Não alterar `ADMIN_SESSION_SECRET` em rollback.
4. No domínio da empresa, validar `/admin/login`, login, leitura de dashboard, operação mutante com CSRF, troca de senha, logout e login com a nova senha. Confirmar que `/mcp` continua respondendo normalmente ao Hermes.

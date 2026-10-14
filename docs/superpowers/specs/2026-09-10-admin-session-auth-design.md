# Acesso administrativo por sessão

## Objetivo

Substituir a autenticação HTTP Basic do navegador no painel `/admin` por uma
tela de login própria, destinada a uma única empresa e uma única conta
administrativa. A solução deve permitir trocar a senha dentro do painel sem
expor credenciais em URLs, logs, HTML ou JavaScript.

## Contexto atual

O painel protege todas as rotas administrativas com `require_admin`. Hoje ele
aceita `X-Admin-Key` ou HTTP Basic; neste último caso o nome de usuário não é
validado e a senha é comparada à chave administrativa. O desafio HTTP Basic
faz o navegador apresentar sua própria janela de credenciais, sem sessão,
logout ou troca de senha.

## Decisão

Será mantida uma única conta administrativa em uma tabela singleton no banco.
A senha será armazenada somente como hash `scrypt` com salt aleatório. O
acesso humano ocorrerá por sessão assinada e cookie seguro; o cabeçalho
`X-Admin-Key` continuará reservado para chamadas técnicas autenticadas, sem
restaurar HTTP Basic.

## Modelo de dados

Uma migration criará `admin_accounts`, com uma única linha permitida:

- `id`, fixo em `1`;
- `username`, único;
- `password_hash`, no formato versionado do hash scrypt;
- `auth_version`, inteiro usado para invalidar sessões;
- `failed_login_count` e `locked_until`, para limitar tentativas;
- `created_at` e `updated_at`.

O serviço de autenticação inicializa a conta apenas se ela ainda não existir.
Assim, a senha cadastrada pelo administrador nunca é sobrescrita em
reinicializações ou novas publicações da stack.

## Configuração e recuperação

O Portainer fornecerá quatro valores secretos:

- `ADMIN_USERNAME`: usuário inicial da única conta;
- `ADMIN_BOOTSTRAP_PASSWORD`: senha usada somente na primeira criação da
  conta; pode ser removida após o primeiro acesso;
- `ADMIN_SESSION_SECRET`: segredo longo e estável para assinar sessões;
- `ADMIN_RECOVERY_KEY`: segredo longo para recuperação emergencial.

Em produção, valores ausentes, curtos ou padrões impedem a inicialização.
`ADMIN_API_KEY` permanece para integrações técnicas já existentes, mas deixa
de ser uma senha do navegador.

Se a senha for perdida, a página de recuperação aceitará o usuário e a chave
de recuperação, exigirá uma nova senha e incrementará `auth_version`. A chave
de recuperação não será gravada no banco, nem retornada pela aplicação.

## Fluxo de acesso

1. A pessoa abre `/admin/login` e informa usuário e senha.
2. A aplicação verifica bloqueio temporário, compara o hash em tempo
   constante e registra a tentativa.
3. Em sucesso, cria uma sessão com `admin_account_id`, `auth_version` e um
   token CSRF aleatório; então redireciona para `/admin`.
4. As dependências das páginas e APIs administrativas aceitam a sessão válida
   ou, apenas para chamadas técnicas, `X-Admin-Key`.
5. Um logout limpa a sessão. A alteração ou recuperação de senha aumenta
   `auth_version`, revogando todas as sessões existentes.

O cookie será `HttpOnly`, `Secure` em produção, `SameSite=Lax`, com prazo de
oito horas e nome específico do painel. Requisições administrativas que mudam
dados enviarão `X-CSRF-Token`; chamadas autenticadas por `X-Admin-Key` não
precisam desse token.

## Telas e rotas

- `GET/POST /admin/login`: formulário, validação e criação da sessão;
- `POST /admin/logout`: encerramento da sessão;
- `GET/POST /admin/password`: visualização e alteração de senha autenticada;
- `GET/POST /admin/recover`: recuperação por chave do Portainer;
- `/admin` e suas APIs: passam a usar sessão ou chave técnica;
- HTTP Basic deixa de ser aceito e nenhuma resposta do painel envia
  `WWW-Authenticate: Basic`.

Falhas de login e recuperação retornam mensagens genéricas. Após cinco erros
consecutivos, a conta fica bloqueada por quinze minutos. As senhas novas devem
ter pelo menos doze caracteres; confirmação divergente é rejeitada.

## Implementação

- `app/security.py`: separa autenticação web, chave técnica, CSRF e hashes;
- `app/models/admin_account.py` e migration: conta singleton;
- `app/services/admin_auth_service.py`: bootstrap, login, bloqueio, troca e
  recuperação;
- `app/admin/router.py` e templates: rotas e telas de acesso;
- `app/main.py`: middleware de sessão;
- `app/config.py`, `.env.example`, documentação e configuração de deploy:
  novos segredos e validação de produção;
- testes de login, logout, expiração por versão, CSRF, bloqueio, alteração e
  recuperação de senha.

## Segurança e compatibilidade

As APIs públicas e o MCP não terão alteração de autenticação. A chave técnica
administrativa será mantida durante esta transição para automações, mas não
será enviada pelo navegador. Não haverá múltiplas contas, permissões por
papel, cadastro público, redefinição por e-mail ou qualquer provedor externo
de identidade.

## Publicação e validação

Antes da publicação, os quatro segredos serão cadastrados no Portainer sem
exibição de seus valores. A migration é executada no start já existente. A
validação de produção cobrirá login, navegação, operação CRUD com CSRF, troca
de senha, invalidação da sessão antiga, logout e recuperação controlada. Em
caso de rollback, `ADMIN_SESSION_SECRET` deve permanecer inalterado para que
o comportamento de sessão seja previsível.

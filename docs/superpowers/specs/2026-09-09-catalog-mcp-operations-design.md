# Catálogo, MCP e Operação Confiável — Design

## Objetivo

Tornar o catálogo único de serviços compatível com todas as integrações da
plataforma e tornar o caminho Hermes → MCP Gateway → API reproduzível,
versionado e observável em produção.

## Decisões

### Catálogo e contratos de integração

`services` permanece o catálogo global: nome, descrição, categoria e estado.
Preço, duração, estado comercial e comissão pertencem exclusivamente a
`professional_services`, que representa uma oferta de um profissional.

As respostas de listagem voltadas a agentes e API devem retornar ofertas, e não
linhas cruas do catálogo. Cada oferta expõe o serviço global, o profissional,
preço e duração efetivamente aplicáveis. Uma busca sem profissional retorna uma
linha por oferta ativa; uma busca com `professional_id` retorna somente as
ofertas ativas daquele profissional. Serviços arquivados, profissionais
inativos e ofertas arquivadas não podem ser retornados para novos
agendamentos.

O contrato público legada de criação/edição de serviços não será usado para o
catálogo administrativo. Será preservado durante a transição, mas adaptado para
não serializar campos comerciais nulos de itens do catálogo. O painel continua
sendo a superfície de gestão do catálogo e das ofertas, sem duplicar preço ou
duração no serviço global.

### MCP

A ferramenta `listar_servicos` consulta as ofertas ativas e formata cada item
com profissional, preço e duração da oferta. Ela nunca lê `price_cents` ou
`duration_minutes` diretamente de `Service`.

`verificar_disponibilidade` e `criar_reserva` já exigem uma oferta ativa; a
alteração garante que a listagem use o mesmo critério. Respostas sem ofertas
retornam mensagem de domínio, sem exceção interna. Testes devem incluir um
serviço de catálogo sem campos legados e uma oferta correspondente.

### Gateway MCP publicado

O gateway é o único endpoint exposto ao Hermes. Ele valida
`X-Gateway-Key` e injeta o Bearer interno da API. A API não precisa ser usada
como endpoint MCP externo do Hermes.

A automação deve construir, testar e publicar `mcp_gateway/Dockerfile` em
`ghcr.io/<repositório>-mcp-gateway`, usando tags por SHA e `latest` apenas na
branch principal. A stack Portainer NPM/Neon referencia a imagem por
`MCP_GATEWAY_IMAGE_TAG`, com valor obrigatório, sem `build:`. O gateway recebe
healthcheck próprio em `/health` e só é considerado pronto se seu upstream API
responder à rota de prontidão.

### Operação e observabilidade

As verificações operacionais mínimas são:

1. API: `GET /ready` retorna 200 e confirma acesso ao banco.
2. Gateway: `GET /health` retorna 200 e confirma a configuração do gateway;
   uma rota de prontidão verifica o upstream API sem revelar segredos.
3. Backup: a documentação exige backup diário externo, retenção definida e um
   teste de restauração periódico.
4. Alertas: o guia de operação orienta monitorar `/ready`, `/mcp` via gateway,
   falhas de backup e erros de webhook/pagamento.

Nenhuma alteração desta entrega modifica senhas, segredos, registros DNS ou a
stack em produção automaticamente.

## Fluxo alvo

```text
Administrador → Catálogo global (services)
                         ↓
Profissional + preço/duração/comissão → professional_services
                         ↓
API / MCP listam somente ofertas ativas
                         ↓
Hermes → MCP Gateway (X-Gateway-Key) → API (/mcp com Bearer interno)
```

## Tratamento de erros

- Sem oferta ativa: resposta de domínio em português, sem erro 500.
- Serviço/profissional/oferta arquivados: indisponíveis para listagem comercial
  e novos agendamentos.
- Gateway sem chave, chave inválida ou upstream indisponível: HTTP 401 ou 502,
  respectivamente, sem vazar token.
- Pipeline não publica uma imagem se testes, lint ou build falharem.

## Testes de aceitação

- Um serviço de catálogo sem preço/duração próprios é listado pelo MCP apenas
  quando existe oferta ativa; a resposta usa os dados da oferta.
- Serviço arquivado ou oferta inativa não aparece no MCP nem na API comercial.
- Gateway valida a chave externa, encaminha o JSON-RPC autenticado e expõe
  health/readiness sem segredo.
- O workflow valida e publica imagens API, backup e gateway nas condições
  corretas.
- As stacks Portainer não possuem `build:` para o gateway e exigem tag
  rastreável.
- A documentação descreve catálogo único, endpoint externo do gateway e o
  procedimento de backup/restauração.

## Fora de escopo

- Troca de credenciais, DNS, Nginx Proxy Manager e Portainer.
- Atribuição de papéis administrativos e trilha de auditoria.
- Implantação em produção antes de revisão, PR e autorização específica.

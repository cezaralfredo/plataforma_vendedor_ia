# Resolução — Autenticação do endpoint `/mcp`

> **Status:** substituído pelo procedimento de operação privada em
> [OPERACAO_MCP_PRIVADO.md](OPERACAO_MCP_PRIVADO.md).

## Causa raiz histórica

O Hermes recebia `401 Unauthorized` porque a chave enviada no cabeçalho
`Authorization` não correspondia exatamente ao valor de `API_KEY` carregado pela
API. O acesso ocorria pelo domínio público e pelo proxy reverso, embora Hermes e
API executassem na mesma VPS.

## Regra atual

- O Hermes usa `http://agenda-api:8000/mcp` pela rede Docker privada
  `agenda_mcp_internal`.
- A API exige `Authorization: Bearer <API_KEY>`.
- O valor de `MCP_ATENDE_AGENDA_API_KEY` no Hermes deve ser igual a `API_KEY` na
  stack da API.
- Credenciais reais pertencem exclusivamente ao Portainer e ao ambiente Hermes;
  não devem ser armazenadas em Git, documentação, histórico de terminal ou logs.

## Tratamento de uma credencial exposta

Uma credencial registrada no histórico deve ser considerada comprometida. Gere
uma substituta fora do repositório, aplique-a nos dois serviços na mesma janela
controlada e invalide o valor anterior. A remoção do texto do repositório não
substitui a rotação.

## Validação segura

Após recriar a API e reiniciar os gateways Hermes, execute `initialize` e
`tools/list` pelo cliente Hermes configurado. O resultado esperado é `200` para
as duas chamadas, logs da API sem novos `401` originados pelo Hermes e `/ready`
saudável.

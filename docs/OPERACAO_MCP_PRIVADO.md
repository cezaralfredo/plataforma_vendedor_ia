# Operação do MCP privado

Este procedimento conecta Hermes e Agenda Atende na mesma VPS sem expor o MCP
pela internet. Substitua somente nomes e valores operacionais no Portainer; não
registre segredos em arquivos versionados.

## Pré-requisitos

- A API usa uma imagem GHCR por tag imutável correspondente a um commit validado.
- Hermes e API executam no mesmo host Docker.
- O administrador consegue editar as duas stacks no Portainer.

## Rede compartilhada

Crie a rede uma única vez na VPS:

```bash
sudo docker network inspect agenda_mcp_internal >/dev/null 2>&1 || \
  sudo docker network create --driver bridge --attachable agenda_mcp_internal
```

Defina `AGENDA_MCP_NETWORK=agenda_mcp_internal` na stack da API e declare a
mesma rede externa na stack Hermes. Depois do deploy, os dois containers devem
listar `agenda_mcp_internal` em `docker inspect`.

## Configuração do Hermes

No ambiente ativo do Hermes, configure somente os nomes de variáveis abaixo:

```dotenv
MCP_ATENDE_AGENDA_URL=http://agenda-api:8000/mcp
MCP_ATENDE_AGENDA_API_KEY=<API_KEY>
```

O valor de `MCP_ATENDE_AGENDA_API_KEY` deve ser igual ao valor de `API_KEY` da
stack da API. Gere a nova chave em um cofre ou gerenciador de senhas, aplique-a
nos dois locais e não a copie para terminal, Git ou tickets.

## Bloqueio público

No Proxy Host público da Agenda no Nginx Proxy Manager, adicione a configuração
avançada abaixo e salve o host:

```nginx
location = /mcp {
    return 404;
}
```

Isso preserva as rotas públicas da aplicação e impede que o proxy encaminhe MCP
da internet para a API.

## Rotação e validação

1. Registre a nova chave em `API_KEY` da stack API e em
   `MCP_ATENDE_AGENDA_API_KEY` do Hermes.
2. Faça o deploy da API com a tag imutável validada e reinicie os gateways
   Hermes para recarregar o ambiente.
3. Execute `initialize` e `tools/list` pelo cliente Hermes configurado.
4. Confirme `200` para as duas chamadas e `/ready` saudável.
5. Inspecione os logs posteriores sem imprimir variáveis de ambiente:

```bash
sudo docker logs --since 30m atende_agenda-api-1 2>&1 | \
  grep -E 'POST /mcp|GET /ready' | tail -100
sudo docker inspect atende_agenda-api-1 hermes --format \
  '{{.Name}} {{range $n,$v := .NetworkSettings.Networks}}{{$n}}={{$v.IPAddress}} {{end}}'
```

O resultado saudável tem chamadas Hermes ao MCP com `200`, `/ready` com `200` e
os dois serviços conectados à rede privada.

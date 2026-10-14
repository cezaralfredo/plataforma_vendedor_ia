# Planejamento da Nova Arquitetura: Orquestração no n8n & Multi-Cliente

> **Registro de Conversa e Decisões de Arquitetura**  
> Data de registro: 14/10/2026  
> Projeto de Origem: `plataforma_atende_agenda`  
> Objetivo: Base para o novo projeto duplicado (evolução para multi-cliente e orquestração via n8n).

---

## 1. Contexto Atual do Sistema em Produção

* **Plataforma Atende Agenda:**
  * Backend em **FastAPI**, **SQLAlchemy 2.0** e **PostgreSQL 16**.
  * Painel Administrativo Web em [app/admin](file:///e:/Projetos/plataforma_atende_agenda/app/admin) (Tailwind + Jinja2).
  * Gestão de agendamentos, catálogo de serviços, profissionais e pagamentos PIX/Boleto/Cartão via **Asaas**.
  * **MCP (Model Context Protocol):** Endpoints `/mcp` e gateway expondo ferramentas prontas para agentes de IA.
* **Operação Atual (Single-Tenant):**
  * O sistema está em produção atendendo **um único cliente/estabelecimento**.
  * O **Hermes** está conectado diretamente ao WhatsApp, atuando como interface conversacional e orquestrador direto.
  * O **n8n** atua em segundo plano com subagentes (reconciliação financeira, cancelamentos, notificações de pagamento e lembretes).

---

## 2. Decisão: Criação de um Novo Projeto Isolado

Para evoluir o sistema sem colocar em risco a operação em produção do cliente atual:
1. **Duplicação da pasta:** O projeto será copiado para um novo diretório (ex.: `plataforma_atende_agenda_v2` ou novo nome do SaaS).
2. **Repositório Git independente:** Início de um novo histórico Git (`git init`), desvinculado do repositório anterior.
3. **Preservação:** O cliente atual permanece rodando intacto no ambiente original.

### Checklist de Limpeza ao Duplicar a Pasta:
Antes de inicializar o Git no novo projeto, remover da pasta duplicada:
- [x] Pasta `.git/` antiga (para criar um repositório limpo).
- [x] Arquivo `.env` com senhas e chaves reais de produção do cliente atual (manter apenas os arquivos `.env.example`).
- [x] Caches locais: `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `node_modules/`, `__pycache__/`, `.worktrees/`.
- [x] Arquivos de banco locais temporários: `agenda.db`, `test_agenda.db` e backups `.sql`.

---

## 3. A Nova Arquitetura Proposta: Omnichannel Híbrido

### 3.1. Suporte a Múltiplos Provedores de WhatsApp
O cliente/empresa poderá escolher livremente o canal de conexão:
1. **Evolution API (QR Code / Baileys):** Conexão rápida e sem burocracia, ideal para estabelecimentos que desejam usar o número existente sem taxas da Meta.
2. **Meta Cloud API Oficial (WhatsApp Business Platform):** Alta estabilidade empresarial, sem risco de desconexão de celular ou banimentos, permitindo selo de empresa verificada.

### 3.2. Mudança de Papéis
| Componente | Papel Anterior | Novo Papel na Arquitetura n8n |
| :--- | :--- | :--- |
| **WhatsApp Inbound** | Hermes conectado ao WhatsApp | Webhooks recebidos no **n8n** (Webhook Evolution ou Webhook Meta Oficial) |
| **n8n Adapter / Normalizer** | Inexistente | Normaliza os payloads distintos para um formato unificado (`phone`, `message_text`, `channel`, `instance_or_phone_id`) |
| **n8n Orquestrador** | Subagentes isolados | **Orquestrador Central**: Roteamento, regras de negócio, limites e controle de sessão |
| **Camada de IA** | Hermes (WhatsApp + Raciocínio) | **AI Agent nativo do n8n** (ou Dify/Hermes como cérebro puro): raciocínio, contexto e execução de MCP Tools |
| **API Agenda** | Backend transacional | Backend transacional com MCP Tools e suporte multi-tenant |
| **WhatsApp Outbound** | Hermes enviando mensagem | Nó Switch no n8n despachando para a API da Evolution ou Graph API da Meta |

---

### 3.3. Fluxo de Atendimento Híbrido no n8n (Padrão Adapter)
```mermaid
flowchart TD
    subgraph Entrada [1. Canais de Entrada WhatsApp]
        Evo[Cliente via Evolution - QR Code] -->|Webhook Inbound /evolution| InEvo[Payload Evolution]
        Meta[Cliente via Meta Oficial - Cloud API] -->|Webhook Inbound /meta| InMeta[Payload Meta]
    end

    subgraph n8n_Normalizacao [2. n8n Adapter / Roteador]
        InEvo --> Normaliza[Normalizador de Entrada:\n• phone\n• message_text\n• channel: evolution | meta\n• instance_id / phone_number_id]
        InMeta --> Normaliza
        Normaliza --> Regras[Identificação do Tenant + Checagem de Horário/Transbordo]
    end

    subgraph Inteligencia [3. Motor de IA Unificado]
        Regras --> AIAgent[AI Agent n8n + Memória de Conversa]
        AIAgent <--> MCP[API Agenda - MCP Gateway /mcp]
        AIAgent --> RespostaTexto[Texto de Resposta Padronizado]
    end

    subgraph Envio [4. Roteamento de Saída]
        RespostaTexto --> Switch{Canal é Meta ou Evolution?}
        Switch -->|Evolution| SendEvo[HTTP: /message/sendText Evolution]
        Switch -->|Meta| SendMeta[HTTP: /messages Graph API Meta]
        SendEvo --> EvoOut[Disparo WhatsApp via Evolution]
        SendMeta --> MetaOut[Disparo WhatsApp via Meta Oficial]
    end
```

---

### 3.4. Atributos Multi-Tenant para Provedor de Mensageria
Na modelagem da empresa/tenant:
* `whatsapp_provider`: `'evolution'` ou `'meta'`
* `evolution_instance`: Nome da instância criada na Evolution API
* `meta_phone_number_id`: ID do número de telefone no portal Meta Developers
* `meta_access_token`: Token permanente do WhatsApp Business Account
* `meta_waba_id`: ID da WhatsApp Business Account

---

## 4. Opções Avaliadas para a Camada de Inteligência

### Opção A: Nó nativo "AI Agent" do n8n *(Mais Recomendada para simplificar a stack)*
* **Como funciona:** O próprio n8n possui o nó `AI Agent` (baseado em LangChain) com nó de modelo (OpenRouter, OpenAI ou Groq), nó de memória de conversa (`PostgreSQL/Redis Chat Memory` por telefone/sessão) e nós de ferramentas (`Custom Tool` chamando os endpoints `/mcp`).
* **Vantagens:** 
  * Elimina completamente a necessidade de containers extras do Hermes.
  * O prompt e as credenciais da empresa podem ser passados dinamicamente com base na instância da Evolution API ou Phone ID da Meta.
  * Todo o fluxo visual fica em uma única plataforma (n8n).

### Opção B: Dify.ai *(Melhor se desejar painel visual de IA)*
* **Como funciona:** Stack Docker do Dify rodando na VPS. O n8n recebe a mensagem do WhatsApp e repassa para a API do Dify (`/v1/chat-messages`).
* **Vantagens:** Workspaces nativos para cada cliente, histórico rico de conversas, métricas de tokens e painel onde o dono da empresa pode personalizar o tom da IA sem tocar em código.

### Opção C: Hermes Multi-Container
* **Como funciona:** Manter o Hermes atual, mas rodando 1 container leve (~60-100MB RAM) para cada cliente, isolando o `config.yaml` e os perfis.
* **Vantagens:** Reutiliza o perfil já testado do Hermes; porém exige gerenciar múltiplos containers e arquivos YAML.

---

## 5. Roteiro de Execução

- [x] **Etapa 1:** Limpeza da pasta duplicada e inicialização do repositório Git novo (`cezaralfredo/plataforma_vendedor_online`).
- [ ] **Etapa 2:** Especificação e configuração dos Webhooks de Entrada no n8n:
  - Endpoint Webhook para Evolution API (`/webhook/whatsapp/evolution`).
  - Endpoint Webhook para Meta Cloud API Oficial (`/webhook/whatsapp/meta` com validação de `hub.challenge`).
- [ ] **Etapa 3:** Construção do Workflow Principal no n8n (`n8n/workflows/orquestrador_whatsapp_ia.json`):
  - Nó Normalizador JavaScript (Adapter).
  - Nó AI Agent configurado com o modelo LLM e memória de sessão por telefone.
  - Nós de Tools MCP integrados aos endpoints `/mcp` da API Agenda (`listar_servicos`, `consultar_disponibilidade`, `criar_agendamento`, `gerar_cobranca_pix`).
  - Nó Router Switch direcionando a resposta de volta ao canal de origem (Evolution ou Meta).
- [ ] **Etapa 4:** Teste fim a fim de conversação, consulta de serviços, agendamento e pagamento.
- [ ] **Etapa 5:** Estruturação da lógica multi-cliente (roteamento dinâmico por instância/phone_number_id no banco).

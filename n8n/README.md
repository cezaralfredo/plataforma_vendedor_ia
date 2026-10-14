# n8n - Orquestrador de Fluxos e Subagentes

Este diretório contém a configuração e templates prontos para o **n8n** na arquitetura da **Plataforma Atende Agenda**.

---

## 🏛️ Papel na Arquitetura

| Componente | Função Principal |
|---|---|
| **Hermes** | **Inteligência Central e Conversação**: conectado diretamente ao WhatsApp, atende os clientes, entende intenções e gera respostas humanizadas. |
| **n8n** | **Orquestrador de Processos e Subagentes**: recebe webhooks da API, orquestra fluxos determinísticos e aciona o WhatsApp nativo do Hermes para mensagens ativas. |
| **API Agenda** | **Base Transacional**: FastAPI + PostgreSQL gerenciando regras da agenda, pagamentos no Asaas e despachando eventos ao n8n. |

---

## 🚀 Como Subir o n8n no Portainer

1. Acesse o **Portainer** → **Stacks** → **Add stack**.
2. **Name**: `n8n`
3. **Build method**: `Web editor`
4. Cole o conteúdo de [docker-compose.n8n.yml](../docker-compose.n8n.yml).
5. O compose já vem pré-configurado para o IP interno:
   * `N8N_HOST`: `147.224.215.151`
   * `WEBHOOK_URL`: `http://147.224.215.151:5678/`
6. Clique em **Deploy the stack**.

---

## 🌐 Acesso ao Painel do n8n

O n8n fica acessível diretamente no seu navegador em:
👉 **`http://147.224.215.151:5678`**

---

## 🔌 Conectar à Stack `agenda_atende`

Na Stack da API no Portainer (`agenda_atende`), adicione a variável de ambiente:
```env
N8N_WEBHOOK_URL=http://147.224.215.151:5678/webhook/pagamento-confirmado
```
> Você também pode usar `http://n8n:5678/webhook/pagamento-confirmado` se ambos estiverem na mesma rede Docker (`agenda_mcp_internal`). Ambos funcionam perfeitamente com latência zero.

---

## 📥 Workflows e Subagentes Prontos para Importação

No painel do n8n (**Workflows** → menu **Import from File**), você pode importar os 4 subagentes:

1. **[orquestrador_agendamentos.json](workflows/orquestrador_agendamentos.json)** (Orquestrador Central de Agendamentos):
   - **Gatilho**: Webhook `POST /webhook/agendamento/criar` (enviado pelo Hermes quando o cliente solicita agendamento).
   - **Ação**: Valida o cliente no banco, cadastra se for novo, cria a reserva com prevenção de conflitos, gera a cobrança PIX no Asaas e responde ao Hermes com o link do pagamento.

2. **[notificacao_pagamento_hermes.json](workflows/notificacao_pagamento_hermes.json)** (Subagente Notificador de Pagamento):
   - **Gatilho**: Webhook `POST /webhook/pagamento-confirmado` (disparado pela API assim que o Asaas confirma).
   - **Ação**: assume uma entrega persistida pela API, envia a confirmação pela bridge WhatsApp nativa do Hermes e só então confirma a entrega para a API.
   - O cron também retenta a cada minuto as entregas sem confirmação do Hermes. Uma falha jamais é marcada como mensagem enviada.

3. **[subagente_financeiro.json](workflows/subagente_financeiro.json)** (Subagente Financeiro e Reconciliação):
   - **Gatilho**: Cron a cada 15 minutos ou Webhook `POST /webhook/financeiro/verificar`.
   - **Ação**: Varre pagamentos pendentes no Asaas, detecta recebimentos, reconcilia os estados na API e prepara disparos.

4. **[subagente_cancelamento.json](workflows/subagente_cancelamento.json)** (Subagente de Cancelamento):
   - **Gatilho**: Webhook `POST /webhook/agendamento/cancelar`.
   - **Ação**: Cancela a reserva na API, libera o horário imediatamente na agenda e envia confirmação de cancelamento cordial ao cliente via WhatsApp pelo Hermes.

5. **[subagente_lembretes.json](workflows/subagente_lembretes.json)** (Subagente de Lembretes Preventivos):
   - **Gatilho**: Agendamento diário (Cron 08:00).
   - **Ação**: Consulta agendamentos confirmados e orquestra mensagens de lembrete preventivo no WhatsApp.

## Variáveis obrigatórias do n8n

Configure estas variáveis no container `agenda_n8n` pelo Portainer. Mantenha as chaves fora do repositório:

```env
AGENDA_API_URL=http://agenda-api:8000
AGENDA_API_KEY=<mesma API_KEY interna da Agenda Atende>

# Seleção de Provedor WhatsApp para Notificações:
# Valores possíveis: 'hermes' (padrão) ou 'meta'
WHATSAPP_NOTIFICATION_PROVIDER=hermes

# Configuração Hermes (WhatsApp Nativo):
HERMES_WHATSAPP_BRIDGE_URL=http://hermes:3000
HERMES_NETWORK=hermes_default

# Configuração Meta WhatsApp Cloud API (opcional, quando WHATSAPP_NOTIFICATION_PROVIDER=meta):
META_WHATSAPP_API_URL=https://graph.facebook.com/v21.0
META_PHONE_NUMBER_ID=<Seu Phone Number ID na Meta>
META_ACCESS_TOKEN=<Seu Token de Acesso Permanente na Meta>
META_PAYMENT_TEMPLATE_NAME=confirmacao_pagamento
META_TEMPLATE_LANGUAGE=pt_BR
META_MESSAGE_TYPE=template
```

### 🛡️ Roteamento Seguro e Resiliente de Provedores
O workflow [`notificacao_pagamento_hermes.json`](workflows/notificacao_pagamento_hermes.json) possui um roteador inteligente:
1. **Padrão Atual (`hermes`)**: Enquanto `WHATSAPP_NOTIFICATION_PROVIDER` for mantido como `hermes` (ou não configurado), o fluxo opera exatamente como antes, despachando via bridge Hermes em `hermes:3000`.
2. **Ativação da Meta Oficial (`meta`)**: Quando desejar usar o WhatsApp Oficial da Meta, basta definir `WHATSAPP_NOTIFICATION_PROVIDER=meta` e preencher `META_PHONE_NUMBER_ID` e `META_ACCESS_TOKEN`.
3. **Fallback Automático contra Falhas**: Caso o provedor seja alterado para `meta` mas as credenciais da Meta estejam vazias ou incompletas, o roteador **não quebra a entrega**. Ele realiza fallback seguro automático para o `hermes` e registra o motivo no log da execução, garantindo que o cliente receba a notificação sem interrupção.

Depois de importar o workflow de confirmação, confirme que ele está **ativo**. Ele normaliza o telefone do cliente para o JID do WhatsApp antes do envio. Faça um PIX de teste: a API deve criar uma entrega `pending`, o n8n deve assumi-la e ela só aparecerá como `sent` após a confirmação de sucesso do provedor ativo devolver o ID da mensagem.


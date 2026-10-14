# Refinamento e robustez do painel administrativo

**Data:** 12 de setembro de 2026
**Base:** `master` no commit `41ab0ce`
**Branch de trabalho:** `codex/admin-quality-hardening`

## Objetivo

Elevar o painel administrativo da Agenda Atende a um nível consistente de operação diária: informações claras, estados confiáveis, ações previsíveis, boa experiência em computadores e celulares e menor dependência de serviços externos no navegador.

O trabalho preservará as regras já aprovadas:

- o catálogo de serviços pertence à empresa;
- preço e duração são definidos no catálogo;
- cada profissional possui comissão própria para cada serviço;
- o agendamento só é efetivado conforme o fluxo financeiro estabelecido;
- exclusões que afetem histórico financeiro ou operacional continuam protegidas;
- nenhuma correção de código apagará dados de produção automaticamente.

## Diagnóstico confirmado

### Dashboard

- Os indicadores e a lista de profissionais dependem de carregamento assíncrono, mas aparecem vazios antes da resposta.
- O texto "Sistema online" e os estados de API, PostgreSQL, Asaas e Hermes são apresentados como valores estáticos e podem transmitir uma condição que não foi realmente verificada.
- Falhas de carregamento aparecem apenas no console, sem orientação para o administrador.

### Agendamentos

- Cadastro, filtros, paginação, detalhes e ações estão disponíveis.
- Ações importantes ainda usam `alert`, `confirm` e `prompt` do navegador, criando uma experiência inconsistente e pouco acessível.
- A listagem em celular exige rolagem horizontal extensa.
- Erros de rede e de domínio não possuem um padrão visual único.

### Pagamentos

- Um pagamento real exibe o tipo técnico `undefined` para o administrador.
- A sincronização com o Asaas não informa claramente se houve atualização, se nada mudou ou se ocorreu falha.
- O identificador técnico do Asaas ocupa destaque excessivo na tabela.
- Ações financeiras precisam continuar protegidas por confirmação explícita e apresentar resultado verificável.

### Profissionais

- A tela realiza uma requisição HTML redundante antes de consultar a API de profissionais.
- A gestão de dados, horários, serviços e comissões funciona, mas ainda usa confirmações e entradas nativas do navegador.
- A tabela é densa em telas pequenas.
- A descrição é truncada mesmo quando curta, acrescentando reticências desnecessárias.

### Serviços

- O catálogo está carregando 16 serviços e 26 ofertas profissionais.
- A detecção de inconsistência considera apenas o nome e marca as três variações de "Corte de cabelo" como duplicadas, apesar de possuírem descrições, preços e durações distintos.
- O rótulo "Arquivar/remover" não informa antecipadamente qual ação será executada.
- O formulário está funcional, mas precisa dos mesmos padrões de feedback e acessibilidade das outras telas.

### Acesso e infraestrutura do frontend

- Login por sessão, CSRF, troca de senha e encerramento de outras sessões estão presentes.
- O painel carrega Tailwind CSS, Font Awesome e HTMX por serviços externos.
- HTMX não é utilizado nas telas atuais.
- O aviso do Tailwind confirma que o compilador em CDN não é indicado para produção.
- Existem templates legados de clientes e administradores sem rotas e sem navegação ativa.

## Estrutura da implementação

O trabalho será dividido em quatro entregas hierárquicas. Cada entrega deve terminar com testes verdes e software utilizável, sem depender da entrega seguinte.

### Entrega 1 — Correção funcional e feedback operacional

1. Normalizar valores destinados à interface:
   - `undefined` passa a ser exibido como "A definir";
   - valores ausentes recebem rótulos legíveis;
   - status técnicos permanecem inalterados na API e no banco.
2. Remover a requisição redundante da página de profissionais.
3. Introduzir um componente comum de mensagens para sucesso, aviso e erro.
4. Exibir carregamento, falha e tentativa de recarregar em Dashboard, Agendamentos, Pagamentos e Profissionais.
5. Tornar a sincronização com o Asaas informativa:
   - indicar que está processando;
   - mostrar o status resultante;
   - diferenciar "sem alteração" de falha;
   - atualizar somente o registro afetado ou recarregar a lista de forma controlada.
6. Ajustar o diagnóstico de duplicidade de serviços para considerar identidade comercial, não apenas o nome bruto. Variações com descrição, preço ou duração diferentes serão sinalizadas como "nomes semelhantes", sem serem tratadas automaticamente como duplicatas.

### Entrega 2 — Experiência administrativa e responsividade

1. Substituir `alert`, `confirm` e `prompt` por modais e notificações do próprio painel.
2. Usar confirmações específicas para cancelar, concluir, excluir, arquivar, remover vínculo e estornar.
3. Manter foco, fechamento por `Esc`, rótulos acessíveis e devolução do foco ao botão de origem.
4. Apresentar Agendamentos, Pagamentos, Profissionais e Serviços como cartões compactos em telas pequenas, mantendo tabelas em telas médias e grandes.
5. Tornar os estados vazios acionáveis e explicar o próximo passo.
6. Diferenciar "Arquivar" de "Excluir definitivamente" antes da confirmação; o backend continuará decidindo qual operação é permitida conforme os vínculos históricos.
7. Reduzir exposição casual de telefone e e-mail nas listagens, mantendo os dados completos em detalhes e formulários administrativos.

### Entrega 3 — Gestão de clientes

1. Criar a entrada "Clientes" no menu principal.
2. Oferecer busca, paginação e indicadores de total e atividade.
3. Permitir criar e editar nome, telefone e e-mail.
4. Exibir histórico resumido de agendamentos e pagamentos do cliente.
5. Permitir arquivamento quando houver histórico e exclusão definitiva somente quando não existirem vínculos.
6. Reutilizar o mesmo catálogo de clientes no formulário de novo agendamento.
7. Remover ou adaptar templates legados para evitar duas implementações concorrentes.

### Entrega 4 — Independência de CDN e validação completa

1. Remover HTMX, pois não possui uso atual.
2. Compilar o CSS do Tailwind durante o build e servir o arquivo pela própria aplicação.
3. Hospedar localmente os ícones realmente utilizados ou substituí-los por SVGs controlados pelo projeto.
4. Definir política de conteúdo compatível com os recursos locais.
5. Adicionar verificações automatizadas para:
   - carregamento e erro das telas;
   - rótulos e normalização de status;
   - modais e confirmações;
   - navegação por teclado;
   - visualização responsiva;
   - fluxos de clientes;
   - ausência de dependências externas inesperadas.

## Componentes e responsabilidades

### Backend administrativo

`app/admin/service.py` continuará concentrando consultas e regras de apresentação do painel. As rotas em `app/admin/router.py` validarão entradas, autorização e CSRF, delegando regras aos serviços. Novas consultas de clientes serão paginadas e não reutilizarão endpoints públicos sem a proteção administrativa.

### Templates e JavaScript

`app/admin/templates/base.html` fornecerá componentes compartilhados de notificação, modal e estado de carregamento. Cada página continuará pequena e responsável por seu próprio estado. Não será introduzido framework SPA nem etapa de frontend independente além da compilação de CSS.

### Dados

Não será criada migração para simples rótulos de interface. Migrações só serão adicionadas se a gestão de clientes exigir um estado persistente de arquivamento que ainda não exista. Dados de produção não serão renomeados, mesclados ou apagados automaticamente.

## Tratamento de erros

- Respostas não bem-sucedidas serão verificadas antes da leitura do corpo.
- Mensagens técnicas serão registradas no servidor; o administrador receberá uma explicação curta e um próximo passo.
- Falha de carregamento não será confundida com lista vazia.
- Botões permanecerão desabilitados enquanto uma operação estiver em andamento.
- Operações financeiras e destrutivas terão confirmação contextual e impedirão duplo envio.
- Links externos de fatura usarão proteção contra acesso ao contexto da janela de origem.

## Segurança e privacidade

- Todas as mutações continuarão exigindo sessão administrativa e CSRF.
- Nenhum token ou credencial será inserido no HTML ou nos logs do navegador.
- Dados pessoais serão exibidos apenas onde forem necessários para a gestão.
- Alteração de senha continuará encerrando as demais sessões.
- Exclusão de clientes, serviços, profissionais e agendamentos respeitará vínculos históricos e financeiros.

## Estratégia de testes

Cada correção começará por um teste que reproduza o comportamento esperado. A validação incluirá:

- testes unitários de normalização e regras de exclusão/arquivamento;
- testes de rotas administrativas, autenticação e CSRF;
- testes de renderização dos templates e JavaScript;
- testes de integração das consultas administrativas;
- verificação visual e funcional em produção após CI, merge e deploy autorizados;
- testes manuais não destrutivos em desktop e celular.

O ambiente local possui Python 3.14 e não consegue carregar a versão atual do SQLAlchemy. A execução oficial continuará no CI com Python 3.11, que é também a versão da imagem de produção.

## Critérios de conclusão

- Nenhum valor técnico `undefined`, `null` ou chave interna aparece para o administrador.
- Nenhuma tela confunde erro de carregamento com ausência de registros.
- Todas as ações fornecem retorno visual claro.
- Os fluxos principais podem ser operados por teclado.
- As telas principais são utilizáveis em 390 px sem rolagem horizontal da página.
- A área Clientes oferece gestão completa com proteção do histórico.
- O painel não depende de Tailwind, HTMX, Font Awesome ou outros recursos remotos em tempo de execução.
- A suíte oficial, lint, build da imagem e smoke tests passam.
- O deploy mantém `/ready` saudável e não introduz erros nos logs.

## Fora do escopo

- Alteração das credenciais atuais.
- Reescrita do painel como SPA.
- Mudança de provedor de pagamentos.
- Exclusão automática de dados existentes identificados como teste, duplicados ou incompletos.
- Alteração do protocolo MCP ou da integração do Hermes.

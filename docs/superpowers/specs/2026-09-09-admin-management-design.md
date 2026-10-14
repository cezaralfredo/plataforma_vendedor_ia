# Gestão Administrativa de Agendamentos, Profissionais e Serviços

## Objetivo

Transformar o painel administrativo em uma área de gestão operacional completa e segura para agendamentos, profissionais, horários, clientes e catálogo de serviços.

## Decisões confirmadas

- O empreendimento terá um catálogo único de serviços.
- Cada profissional poderá oferecer vários serviços do catálogo, com preço, duração e comissão próprios.
- A comissão inicial de cada vínculo profissional-serviço será 10% e poderá ser alterada pelo administrador.
- O administrador poderá criar um cliente durante a criação de um agendamento.
- Profissionais e serviços com histórico serão arquivados, nunca apagados definitivamente.
- Exclusão definitiva só será permitida para registros sem histórico ou vínculos dependentes.
- O fluxo não criará cobranças durante a gestão de agendamentos.

## Modelo de dados

### Catálogo de serviços

`services` passa a representar o catálogo do empreendimento, com nome, descrição, categoria e indicador `active`. O catálogo não terá mais preço, duração ou profissional obrigatório.

### Serviços oferecidos

Uma nova entidade `professional_services` conecta um profissional a um serviço do catálogo. Cada vínculo terá `professional_id`, `service_id`, `price_cents`, `duration_minutes`, `commission_percent`, `active` e datas de auditoria. A combinação profissional-serviço será única. `commission_percent` deve aceitar valores de 0 a 100 e iniciar em 10.

### Agendamentos históricos

Cada agendamento manterá referências ao cliente, profissional e serviço de catálogo, além de cópias imutáveis de preço, duração e comissão usados na criação. Isso preserva o histórico financeiro quando o catálogo ou a comissão forem alterados posteriormente.

### Migração e compatibilidade

A migração preservará os serviços existentes, convertendo cada um em item do catálogo e criando seu vínculo equivalente em `professional_services`. Agendamentos existentes receberão os valores históricos disponíveis do serviço associado. Nenhuma migração alterará valores de pagamentos já registrados.

## Telas e fluxos

### Dashboard

Remover o bloco visual chamado “Ações”. Manter indicadores concisos de agendamentos, receita, profissionais ativos e serviços ativos. Nenhuma ação destrutiva ficará disponível no dashboard.

### Agendamentos

A tela terá criação, edição, cancelamento e exclusão protegida.

- Criar: localizar cliente existente ou criar cliente, selecionar profissional ativo, serviço ativo habilitado para o profissional e um horário disponível.
- Editar: permitir troca de cliente, profissional, serviço, horário e observações apenas antes do encerramento financeiro; a alteração recalcula as cópias de preço, duração e comissão.
- Ações de status: confirmar, cancelar e concluir serão oferecidas apenas para os estados compatíveis.
- Excluir: permitido somente para agendamento sem pagamento e sem histórico operacional que precise ser preservado; os demais casos usam cancelamento.
- Validações: profissional e serviço ativos, vínculo profissional-serviço ativo, horário dentro da disponibilidade e ausência de conflito de agenda.

### Profissionais

Uma página de gestão completa permitirá criar, editar, arquivar e excluir profissionais sem histórico. A tela de detalhe terá três abas:

1. Dados: nome, contato, biografia e situação ativa.
2. Horários: criação, edição e remoção de faixas semanais ou datas específicas, respeitando intervalos válidos e conflitos futuros.
3. Serviços oferecidos: descrição do serviço, preço, duração, comissão e situação do vínculo. O administrador poderá associar itens do catálogo e ajustar cada condição individualmente.

### Serviços

Uma nova área do menu administrará o catálogo único: criar, editar, arquivar, reativar e excluir serviços sem vínculos ou histórico. O painel mostrará quantos profissionais oferecem cada serviço e indicará quando uma exclusão precisa ser substituída por arquivamento.

### Clientes

O cadastro rápido de cliente dentro do formulário de agendamento validará nome e telefone. A busca evitará duplicidade por telefone e reutilizará o cliente existente quando houver correspondência.

## Regras de segurança e integridade

- Exclusão, arquivamento e cancelamento exigem confirmação explícita na interface.
- Operações de edição e exclusão retornam mensagens claras de regra de negócio, nunca erro interno genérico.
- Todas as rotas administrativas exigem a autenticação atual de administrador.
- Ações de pagamento permanecem separadas do fluxo de gestão de agendamentos.
- Alterações de horário não removem disponibilidade que já seja necessária para explicar um agendamento concluído; agendamentos futuros incompatíveis deverão ser identificados antes da confirmação.

## Tratamento do erro atual de “Ações”

O endpoint atual aceita somente confirmar e cancelar, enquanto a interface tenta concluir agendamentos. O módulo unificará os estados permitidos em uma única regra de transição, testada no servidor, para impedir o erro interno e evitar ações inválidas no navegador.

## Critérios de aceite e validação

- CRUD administrativo de catálogo, profissionais, vínculos profissional-serviço e disponibilidade, com arquivamento seguro.
- Criação e edição de agendamento com cliente novo ou existente e validação de disponibilidade.
- Comissão configurável por serviço oferecido e cópia histórica no agendamento.
- Ações de status retornam resposta válida para todas as transições permitidas e erro de domínio para as demais.
- Testes de migração preservam os dados existentes e os valores históricos.
- Testes de rota cobrem autorização, regras de exclusão/arquivamento, conflito de horário e fluxos completos de gestão.
- Regressão completa da suíte antes de publicar.

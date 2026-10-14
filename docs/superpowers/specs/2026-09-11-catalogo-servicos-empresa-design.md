# Catálogo de Serviços da Empresa — Design

## Objetivo

Transformar o catálogo de serviços em uma fonte única controlada pela empresa. Profissionais não criarão serviços: eles serão habilitados para executar serviços existentes, com regras individuais de comissão.

## Contexto e problema atual

Atualmente `services.professional_id` torna cada serviço uma oferta pertencente a um profissional. Isso duplica itens equivalentes, deixa a área de Serviços dependente de cadastros individuais e obriga o agendamento a verificar propriedade do serviço. Também torna impossível representar, de forma clara, o catálogo que a empresa vende.

## Modelo de dados proposto

### Serviço (`services`)

O serviço passa a pertencer exclusivamente à empresa e contém:

- `id`, `name`, `description`, `category`;
- `duration_minutes` e `price_cents`, definidos pela empresa;
- `active`, para ocultar itens que não são mais vendidos sem apagar histórico financeiro;
- datas de criação e atualização.

O campo `professional_id` é removido após a migração.

### Habilitação profissional-serviço (`professional_services`)

Uma nova tabela de associação representa quais profissionais podem executar cada item do catálogo:

- `professional_id` e `service_id`, com unicidade do par;
- `commission_percent`, com valor inicial de 10,00%;
- `active`, para pausar temporariamente a execução por aquele profissional;
- datas de criação e atualização.

A duração e o valor comercial são sempre os do catálogo. A comissão pertence à associação, pois pode variar por profissional e por serviço.

### Agendamentos e pagamentos

O agendamento continua apontando para `service_id` e `professional_id`, mas a validação muda para exigir uma habilitação ativa na tabela de associação.

Uma solicitação de horário cria uma reserva temporária e só se torna `confirmed` quando um pagamento for `received` ou `confirmed`. Reservas com pagamento vencido, cancelado ou sem pagamento até a expiração passam a `cancelled`, deixam de bloquear horário e não entram em receita.

## Regras de exclusão

1. Um serviço sem agendamentos pode ser apagado definitivamente.
2. Um serviço com somente reservas canceladas/expiradas e pagamentos não recebidos pode ser apagado. A exclusão remove essas reservas e seus pagamentos locais não financeiros.
3. Um serviço com qualquer pagamento recebido/confirmado, agendamento confirmado ou atendimento concluído não pode ser apagado. Ele pode ser desativado.
4. Um profissional não pode ser removido quando existirem agendamentos preservados; ele pode ser desativado. Habilitações sem histórico podem ser removidas.

Essas regras impedem a perda de registros financeiros reais e permitem a limpeza de solicitações que nunca se converteram em venda.

## Migração dos dados existentes

1. Criar a tabela `professional_services`.
2. Agrupar serviços legados por nome, categoria, descrição, duração e valor normalizados.
3. Criar um único serviço para cada grupo e transferir os agendamentos para o novo identificador.
4. Criar uma habilitação para cada par profissional–serviço legado, com comissão inicial de 10,00%.
5. Preservar serviços legados distintos quando preço, duração, categoria ou descrição divergirem; nenhum valor é unido por aproximação.
6. Remover a chave estrangeira e a coluna legada `services.professional_id` somente depois de todos os vínculos e agendamentos estarem migrados.

A migração deve ser transacional e reversível dentro da janela de publicação. A rotina deve funcionar em PostgreSQL, que é o banco de produção.

## API e camada de domínio

- `POST /api/services` cria somente itens de catálogo, sem profissional.
- `GET /api/services` lista o catálogo, com filtros de categoria e status; o filtro por profissional retorna apenas serviços para os quais ele está habilitado.
- Endpoints de habilitação permitem incluir, editar comissão/estado e remover a relação profissional–serviço.
- A criação de agendamento e a consulta de horários verificam a associação ativa, em vez de `service.professional_id`.
- A exclusão de serviço executa a regra de preservação: remove apenas dependências expiradas e não financeiras; caso contrário, retorna uma mensagem orientando a desativação.

## Painel administrativo

### Área Serviços

Exibe a lista do catálogo da empresa com categoria, duração, preço, quantidade de profissionais habilitados, status e ações de editar, desativar/reativar e excluir quando permitido. Também permite criar um serviço e abrir a lista de profissionais habilitados.

### Área Profissionais

Exibe a gestão do profissional, de horários e das habilitações. O administrador escolhe itens do catálogo existente, informa a comissão daquele profissional para o serviço e pode ativar, pausar ou remover a habilitação. Não haverá cadastro de serviços dentro do profissional.

### Área Agendamentos

Mostra se a reserva aguarda pagamento, está confirmada, cancelada ou concluída. Ações manuais não podem confirmar uma reserva sem pagamento aprovado.

## Tratamento de erros

- Erro claro se um profissional inativo ou não habilitado for selecionado.
- Erro claro ao tentar excluir serviço com histórico financeiro ou agenda confirmada.
- Conflitos de horário continuam protegidos pelo banco e pela validação de disponibilidade.
- A atualização de pagamento é idempotente; pagamentos recebidos confirmam a reserva, e vencidos/cancelados a liberam.

## Testes de aceitação

1. Um serviço é criado sem profissional e aparece no catálogo administrativo.
2. Dois profissionais habilitados para o mesmo serviço o visualizam sem duplicar o catálogo.
3. Comissão de um profissional não altera a de outro nem o preço de venda.
4. Agendamento falha para profissional não habilitado e funciona para habilitação ativa.
5. Pagamento recebido confirma a reserva; vencido/cancelado libera o horário e não compõe receita.
6. Serviço com somente reservas não pagas expiradas pode ser excluído; serviço com pagamento aprovado só pode ser desativado.
7. Migração preserva todos os agendamentos e cria as habilitações correspondentes.

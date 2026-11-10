# Confiabilidade de mensagens do bot

## Evidência e escopo

A investigação de novembro de 2026 identificou no runtime implantado (revision
`ebbef0ae2304bec612053c020b2e761aa697c83a`) riscos de perda de eventos: resposta
HTTP 202 antes da persistência do payload completo, sobrescrita de estado fora
do lock e abandono do evento quando a única tentativa de lock falha.

Esses defeitos são verificáveis no código; não provam qual deles ocorreu no
incidente. O ID de lote observado excluía uma mensagem do cliente que existia
no histórico da sessão. Isso não reconstrói a entrada completa do modelo.
O ADK inclui o histórico de sessão por padrão; não há evidência suficiente
para afirmar perda determinística na transferência entre subagentes.

Não registrar transcrições, credenciais ou dados pessoais nesta documentação.

## Garantias desejadas

- Mensagem elegível gravada no CRM deve ter trabalho recuperável associado.
- HTTP 202 do runtime deve significar persistência do evento completo.
- Repetição de entrega do mesmo evento não deve duplicar seu texto no lote.
- Trabalho aceito deve sobreviver à reinicialização de um worker.
- Uma execução antiga não pode apagar ou concluir uma geração mais nova.
- Repetição de postback deve reconhecer a resposta já criada no CRM.
- Contexto persistido não pode ser zerado pela inicialização de um turno.

A semântica é entrega com novas tentativas e efeitos idempotentes. Não se deve
prometer exatamente uma execução de ferramenta externa: efeitos de ferramentas
precisam de idempotência própria, especialmente após timeout do modelo.

## Limites operacionais

Redis precisa de persistência e política de memória que preserve trabalho
pendente. AOF com fsync periódico ainda admite uma janela de perda em falha do
host; uma confirmação Redis em memória não equivale a commit em disco.
Restauração de backup, perda do volume e failover devem fazer parte do plano
operacional. O Compose local habilita AOF; confirme a configuração efetiva da
instalação antes de publicar.

Uma resposta já enviada antes da chegada de outra mensagem não pode ser
recolhida por cancelamento de worker. O controle de geração protege trabalho
pendente; não desfaz efeitos externos já concluídos.

Não ampliar automaticamente o replay para canais com moderação ou outros
fluxos com efeitos não idempotentes. Esses fluxos exigem revisão específica.

## Validação necessária

1. Enviar três mensagens próximas contendo intenção, quantidade e datas;
   confirmar que os três IDs aparecem no trabalho e no contexto processado.
2. Repetir o mesmo evento antes e depois da conclusão sem duplicar resposta.
3. Encerrar o worker após aceitar evento, durante IA e após commit do postback
   antes de receber a confirmação; recuperar sem perder mensagem.
4. Executar dois workers na mesma conversa e conversas diferentes em paralelo.
5. Fazer a geração antiga terminar após nova mensagem; ela não deve limpar a nova.
6. Interromper Redis/Processor/CRM; verificar recuperação e alertas de pendência.
7. Transferir para subagente com datas previamente sincronizadas na sessão;
   verificar o contexto real usado pelo ADK.
8. Confirmar que parâmetros existentes, inclusive false e zero, sobrevivem ao turno.

Use IDs sintéticos nos testes. Não reutilize transcrição de cliente em fixtures.

## Publicação

Publicação exige autorização separada. Antes dela, revisar migrations, ordem
compatível de atualização, recuperação do estado legado e configuração Redis.
Registrar os comandos de validação executados e suas limitações. Não considerar
verificação sintática como substituta de testes de banco, jobs e concorrência.

## Limites de contexto e mídia

Preservar o histórico e o estado não garante obediência de um modelo a todas as
instruções. Os testes de contexto verificam a entrada montada pelo ADK, sem
chamada ao modelo; uma avaliação comportamental de reservas continua necessária
antes de afirmar que perguntas repetidas foram eliminadas em todos os cenários.

O postback com ID estável serializa a consulta de duplicatas e a criação da
mensagem usando lock transacional da conversa. Na criação com mídia, o caminho
existente de anexação pode baixar arquivos durante essa transação. Respeitar os
timeouts de download e acompanhar duração de locks; testes com doubles não
substituem um teste concorrente com PostgreSQL real.

## Validação desta alteração

- Processor: três testes passaram com ADK 1.19.0 real, preservando estado e
  montando contexto de root/subagente. `cryptography` foi substituído apenas em
  diretório temporário para contornar incompatibilidade nativa do ambiente.
- CRM: 41 exemplos passaram, cobrindo journal, rollback, entrega, lease, fallback,
  compatibilidade e postback, com bundle, PostgreSQL e Redis isolados em `/tmp`.
- Runtime: cinco pacotes alterados passaram com `-race`, incluindo E2E,
  repositório, handler, worker e dispatch, usando Redis isolado; consultar `evo-bot-runtime/docs/durable-pipeline.md` para arquitetura e transição.

A validação local não publica a correção nem demonstra que uma execução de modelo
em produção nunca repetirá perguntas. A causa exata da exclusão do ID no incidente
continua sem atribuição conclusiva; os defeitos de confiabilidade identificados
foram tratados independentemente dessa atribuição.

A revisão independente anterior ao commit identificou starvation no replay de
journals. A correção adiciona agendamento por evento, reserva transacional com
SKIP LOCKED e backoff; o teste com 501 eventos e 500 falhas confirma a recuperação
do evento seguinte. A migração aditiva deve suceder a criação das tabelas.

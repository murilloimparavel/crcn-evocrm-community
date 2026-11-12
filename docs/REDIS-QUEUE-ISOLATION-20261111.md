# Isolamento das filas CRM e autenticação

## Incidente e estado

Em 11/11/2026 o CRM e a autenticação operavam no mesmo Redis `/1` e ambos
consumiam `default`. O worker de autenticação recebeu o webhook
`171838ce-c108-4aea-92fe-1e7dffbc8499`, falhou cinco vezes com
`uninitialized constant Webhooks` e o reenfileirou. O CRM processou o job
aproximadamente 8 minutos e 42 segundos depois do enqueue. A transcrição desse
áudio falhou por outra causa: o provedor exigia saldo mínimo de US$ 0,50.

Na amostra havia jobs do CRM em `retry`; mensagens em `dead` são históricas e
não devem ser reenviadas automaticamente. Contagens mudam continuamente. O
Compose deste repositório já prevê bancos separados, mas diverge da configuração
efetivamente executada. O Bot Runtime também usa `/1`: mover o CRM inteiro
sem estudar suas chaves alteraria mais do que as filas.

## Candidato a ensaiar

Manter CRM e Bot Runtime no `/1` e configurar **ambos** os processos web e
Sidekiq da autenticação para outro banco Redis dedicado, candidato `/3` (estava
vazio na consulta; confirmar novamente e reservar antes de uso). Preservar a
configuração de cache da autenticação, que é derivada para `/0` no código da
imagem inspecionada. Confirmar, nas imagens exatas, todos os produtores e
consumidores e as demais utilizações de Redis antes de decidir a configuração.
Não mudar somente o worker: os produtores também devem usar o novo banco.

## Preparação necessária antes da produção

1. Obter snapshot privado do Compose atual do Coolify, dos digests e da
   configuração pertinente; validar ausência de alterações concorrentes e
   coordenar a janela com outros operadores.
2. Identificar com as imagens efetivas todos os produtores, workers, nomes de
   classes, cron e chaves Redis. Inventariar listas, retries, agendados e jobs
   em execução por origem, inclusive classes compartilhadas como mailers.
   Não inferir origem apenas pelo nome da fila.
3. Preparar backup privado recuperável e plano para preservar jobs recebidos
   durante o corte. Definir como drenar workers e congelar ou armazenar novos
   eventos, e como transportar jobs de autenticação pendentes com IDs, payloads,
   horários e ordem preservados. Não reexecutar jobs concluídos ou mortos.
4. Ensaiar em staging isolado com as imagens exatas e dados sintéticos: ingestão
   de webhooks, produtor/worker de autenticação, job em execução, fila, retry,
   agendado, cron e chegada durante o corte. Medir perda, duplicação e ordenação.
5. Ensaiar rollback com produtores e workers drenados, reconciliar os jobs novos
   entre os dois bancos, restaurar o Compose anterior e validar processamento.
   A configuração antiga é insegura: rollback é contingência temporária e exige
   monitoramento explícito até nova correção.
6. Confirmar as condições do executor de produção e sua baseline. Em 11/11,
   `enabled` e `baseline_approved` estavam falsos; não contornar esses controles.

## Aplicação e validação pretendidas

Somente depois dos ensaios, aplicar a configuração no Coolify pelo procedimento
operacional revisado, sem recriar Redis/PostgreSQL. Verificar a configuração real
dos dois processos de autenticação e dos processos CRM/runtime, saúde, filas,
cron, retries e processamento de um webhook autorizado. Acompanhar erros de
classe no worker de autenticação e latência do webhook após o corte. Preservar
e reconciliar jobs existentes; não usar `FLUSHDB`, apagar filas ou reexecutar
indiscriminadamente a fila de mortos.

## Evidência local

`python3 tests/redis-isolation/rehearse.py` executa Redis descartável e verifica
separação de filas e preservação de retry com um rollback sintético quiescido.
Esse ensaio **não** testa os processos Rails, Coolify, jobs reais, cron, tráfego
durante corte ou recuperação de produção e não constitui autorização técnica
para aplicar a mudança. Nenhuma alteração em produção foi executada por este
ensaio.

## Ensaio com imagens em execução

`tests/redis-isolation/image-smoke.sh` foi executado na VPS em rede Docker
interna e Redis descartável, sem dados de produção. Usou a imagem CRM ativa
`sha256:681278e27da6…` e a imagem Auth ativa `sha-398bde…`. Os processos Sidekiq
dessas imagens consumiram jobs sintéticos em bancos separados; após parar ambos
os workers, um job pendente sintético foi transferido e consumido no retorno,
enquanto um retry sintético do CRM permaneceu preservado. O ensaio passou.

O teste inicializa workers sintéticos com as dependências das imagens, sem subir
as aplicações Rails, seus produtores, cron ou Coolify. A transferência do job é
apenas uma simulação em dados descartáveis e não é um procedimento de migração
confiável para produção. Não cobre falha durante transferência, duplicidade,
reenfileiramento concorrente ou identificação de jobs ambíguos.

## Ensaio Rails isolado

`tests/redis-isolation/rails-isolated.py` criou uma rede interna, volumes novos,
PostgreSQL e Redis descartáveis, e usou as imagens ativas de CRM e autenticação.
As migrações dos dois Rails passaram e seus produtores enfileiraram jobs reais:
`Licensing::HeartbeatJob` com geração nula e `Webhooks::EvolutionHubEventsJob`
com payload vazio. Os workers corretos executaram ambos em bancos separados. O
webhook vazio testa apenas o despacho do job; não comprova ingestão completa de
mensagem WhatsApp. O projeto e seus volumes descartáveis foram removidos.

Esse ensaio ainda não testa transferência dos jobs reais pendentes, agendados
ou em retry, falhas durante migração, nem rollback pelo Coolify. Portanto não
substitui os testes de corte e reconciliação exigidos antes da produção.

### Reconciliação com payloads do Rails

Em ensaio posterior, `rails-reconcile.rb` usou o produtor Rails real de
`Licensing::HeartbeatJob` para gerar jobs pendentes e agendados; um terceiro
payload real foi colocado sinteticamente no conjunto de retry. Com os workers
parados e Redis descartável, o ensaio migrou e restaurou os três, preservando
scores e ordem da fila, e reconciliou uma falha simulada após a cópia. Em
seguida os workers reais processaram jobs adicionais. O webhook ensaiado
continua com payload vazio e não comprova ingestão WhatsApp completa.

Esse teste manipula apenas fixtures selecionadas em um ambiente sem tráfego.
Não valida um migrador geral, identificação de todos os jobs reais, ordenação
entre várias transferências, journal durável, processo em execução no corte,
interrupção do Redis, recebimento de novos jobs ou reconciliação após retomada.
As rotinas Lua de ensaio continuam proibidas para produção.

## Ensaio de transferência e falhas

`test-atomic-transfer.py` usa Redis descartável e payloads sintéticos no formato
Active Job para testar uma transferência individual de fila, agendamento e retry,
preservação dos scores, retorno ao banco original, repetição e conflito de tipos
e duplicidade. Também foi injetada uma falha após copiar ao destino: Redis não
desfaz escritas de um script que retorna erro, de modo que o teste constatou duas
cópias e removeu manualmente a duplicata sintética antes de prosseguir. O script
de ensaio copia antes de remover a origem para evitar perda silenciosa, mas isso
não garante entrega única. A ordem relativa de listas, classificação de jobs,
journal durável, concorrência e falha de processo/Redis não estão resolvidos.
O Lua é exclusivamente um experimento e não deve ser usado em produção.

O executor instalado ainda estava com `enabled=false` e
`baseline_approved=false`. A versão local do adaptador foi alterada para detectar
mudanças de configuração dos serviços além das imagens, rejeitando mudanças nos
serviços de dados e nas configurações compartilhadas. Os 28 testes do adaptador
passaram, incluindo aplicação e rollback simulado para mudança de ambiente com
imagem inalterada. Essa alteração ainda não foi instalada no executor da VPS nem
ensaiada com Coolify real; a verificação de imagem e saúde, sozinha, não confirma
que a variável Redis foi aplicada. Não ativar os controles nem aplicar o Compose
sem ensaiar o caminho completo e a reconciliação dos jobs.

## Rollback de configuração no Coolify de staging

`coolify-rollback-rehearsal.py` aplicou no serviço de staging uma mudança da
autenticação de `/1` para `/3`, verificou o ambiente real de ambos os contêineres
de autenticação e provocou uma falha após estabilização. O adaptador restaurou
o Compose anterior; os dois contêineres voltaram a `/1`, enquanto os IDs e os
horários de início de PostgreSQL e Redis permaneceram iguais. O staging foi
desligado e a configuração desejada anterior foi conferida na API do Coolify.
Esse ensaio não migrou nem reconciliou jobs reais e não ativa o executor de
produção. O YAML de staging tinha referências compartilhadas de ambiente; o
ensaio copia esses mapas antes de alterar os serviços selecionados.

## Reconciliação e ordem em Redis descartável

`test-ordered-rollback.py` ensaia um único job em fila mista com clientes
parados. Um registro temporário da fila original permite restaurar exatamente a
ordem e remover a duplicata após falha simulada antes ou depois da cópia. O teste
também recusa o rollback quando a fila muda após o snapshot. Esse experimento é
limitado a um job de lista e não resolve jobs em execução, agendados, retry,
durabilidade do journal, interrupção do Redis, classificação de jobs ambíguos ou
novas mensagens após a retomada. Não é um migrador de produção.

## Job em execução e chegada durante corte

`inflight-cutover.sh` usou a imagem real da autenticação com um job de teste em
Sidekiq e Redis descartável. O worker recebeu TSTP enquanto o job estava em
execução; um segundo job foi enfileirado durante a pausa, permaneceu pendente,
foi transferido após o término do primeiro e executado uma vez no novo banco.
Após seu consumo, o rollback de snapshot recusou restaurá-lo, evitando uma
duplicação no ensaio. O teste passou e removeu os contêineres e a rede de teste.

O job é sintético e grava uma confirmação de teste; os jobs reais não possuem
necessariamente uma confirmação durável equivalente. A recusa do rollback é
uma detecção, não uma reconciliação automática após a retomada. Também não foram
testados workers Rails em execução durante o corte de configuração do Coolify,
retentativas e tarefas agendadas concorrentes, ou recuperação após interrupção
do Redis. O procedimento ainda não é seguro para uso em produção.

O ensaio foi ampliado para o cenário posterior à retomada: após confirmar no
marcador sintético que um job terminou, o rollback preservou essa conclusão,
transferiu outro job pendente e manteve os scores de jobs agendado e em retry.
O worker anterior executou o pendente sem repetir o concluído. Passou no Redis
descartável com a imagem Auth real. A reconciliação se apoia em um marcador
criado pelo job de teste; essa premissa não foi comprovada para os jobs reais.

## Recibo durável de conclusão

Foi implementado no submódulo Auth um middleware Sidekiq que grava no PostgreSQL
um recibo por JID depois de `perform` retornar com sucesso. A tabela registra
classe, fila, SHA-256 dos argumentos e horário UTC. Um lock consultivo do
PostgreSQL serializa execuções concorrentes do mesmo JID. Se uma cópia do mesmo
JID reaparecer após uma transferência parcial ou rollback, o worker confere o
payload e reconhece a conclusão sem repetir o job. Uma falha do job não cria
recibo; um JID concluído com payload diferente falha explicitamente.

O teste `tests/redis-isolation/receipt-middleware-smoke.py` passou na VPS usando
a imagem Auth de produção e PostgreSQL/Redis descartáveis. Verificou recibo após
sucesso, ausência após falha, persistência no PostgreSQL e replay do mesmo JID
sem segunda execução. A instância Sidekiq real incluiu o middleware na chain e
executou o fixture uma vez. O middleware e os arquivos foram apenas montados no
ensaio; nenhuma imagem foi construída ou implantada.

O recibo é uma confirmação durável de retorno bem-sucedido do job, não uma
transação distribuída com APIs externas. Um crash entre um efeito externo e o
commit do recibo ainda pode repetir esse efeito, conforme a semântica at-least-
once do Sidekiq. Jobs anteriores à versão com recibos também não ganham prova
retroativa: antes de isolá-los, é necessário drenar os workers antigos e
inventariar/reconciliar separadamente listas, retries e agendamentos. A tabela
não tem política de retenção; não apagar recibos enquanto existirem jobs que
possam ser recuperados ou reintroduzidos.

## Estado do executor e produção

Na última consulta, o executor da VPS continuava com `enabled=false` e
`baseline_approved=false`; a baseline ainda não tem evidência aprovada para o
release exigido pelo executor. Os comandos do executor exigem ainda que o
release venha de `main`, tenha imagens imutáveis compatíveis, QA de staging e
backup verificado. Não alterei essas flags: fazê-lo sem o release publicado e
sem reconciliação das filas seria retirar uma barreira deliberada, não resolver
o bloqueio com evidência.

Nenhum serviço ou configuração de produção foi alterado nesta rodada. A
mudança de recibos ainda precisa entrar em um release aprovado e a reconciliação
geral dos jobs preexistentes no Redis compartilhado continua pendente. A
amostra consultada continha 28 retries e 1.186 entradas históricas em DeadSet;
nenhuma delas foi movida, reexecutada ou removida. A configuração permanece no
Redis `/1` até esses pré-requisitos e o rollback serem comprovados no fluxo de
release instalado.
A leitura dos jobs reais de licenciamento mostra uma cadeia de reagendamento e
condições de contexto; não comprova um recibo durável genérico por job.

# Staging temporário — 10/11/2026

## Executado na VPS

Reutilizada a stack sintética `w3ic7aoj22xbx6ljsb7evu6f`, separada da produção
`tzbydmxtjuilf4xq2gow9gcs`. Rede Docker internal, banco, Redis e volumes exclusivos.
Portas publicadas somente no loopback. Não foram copiados dados de clientes.

O primeiro ciclo executou as migrations Auth, CRM, Core e Processor, todas exit 0.
Os onze serviços ficaram saudáveis durante três amostras consecutivas. O ciclo
terminou com `qa_passed=true`, `stopped=true` em aproximadamente dois minutos.
Todos os containers da stack foram parados, preservando os volumes.

Evidência privada no host: `/data/evocrm-staging/cycle-result.json`.
Logs de migrations e Compose permanecem privados no host, sem uploads ao GitHub.
O ensaio prova a saúde/migração das imagens atuais do staging, não das correções
recentes em branches e não uma restauração real de produção.

## Controlador

`scripts/deploy/staging-cycle.py` valida isolamento, serializa ciclos por flock,
sobe banco/Redis, executa migrations ordenadas, aguarda healthchecks e para a stack
em finally. Nunca executa down -v nem remove volumes. ExecStopPost do systemd
repete a parada; RuntimeMaxSec limita um ciclo travado a 25 minutos.

`--candidate /caminho/privado/manifest.json` aceita exatamente os nove digests
aprovados e pares web/worker iguais. Usa as mesmas imagens para migrations e
readiness. Após sucesso, volta às imagens anteriores sobre o schema migrado para
ensaiar compatibilidade; depois para tudo e restaura o Compose anterior. Essa
modalidade ainda não foi executada na VPS. Não equivale a downgrade de banco.

64 testes locais passaram, incluindo rejeição de rede externa, porta pública,
volume de produção, socket Docker, privilégios e parada após migration falhar.

## Continuação do auto deploy

A ativação continua pendente. A main publicada tem somente um adaptador de
produção sem chamador ativo e um workflow intencionalmente bloqueado. Não foi
habilitado deploy automático nesta operação.

Faltam ensaio de promoção/rollback das imagens candidatas exatas, conciliação dos
pacotes personalizados atuais com os gitlinks publicados, backup externo e
integração do executor com o gatilho de CI da main. Não registrar booleanos de QA
ou rollback como aprovados sem a execução correspondente. Não copiar chave SSH
root para o GitHub Actions. Banco não deve ser restaurado automaticamente.

## Implementação preparada, não ativada

O workflow `auto-release.yml` aguarda CI bem-sucedido de push na main do próprio
repositório; rejeita PRs, forks e commits obsoletos. Executa runtime race/E2E,
constrói sete imagens para os nove serviços, gera SBOM/proveniência e bloqueia
vulnerabilidades HIGH/CRITICAL. Não publica `latest`. Os artifacts de digests
pertencem ao mesmo run; não se aceita artifact indicado por uma entrada externa.

O job de promoção exige `PRODUCTION_DEPLOY_ENABLED=true` e Environment production.
O transporte previsto é uma chave exclusiva para usuário sem grupo Docker, com
forced-command e sudo permitido somente para o executor instalado. Não instalar
chave root nem um runner genérico na VPS. Os secrets necessários são
`DEPLOY_EXECUTOR_KEY`, `DEPLOY_EXECUTOR_KNOWN_HOSTS` e a variável
`DEPLOY_EXECUTOR_HOST`; ainda não foram provisionados.

`release-executor.py` aceita somente um manifesto limitado de SHA/digests via stdin.
O código instalado é revisado e independente do código recebido do CI. A origem
Git privada é fixa e main é conferida novamente após QA e antes da promoção.
Configuração root-owned privada determina backup/verificação, drain/resume,
migration e smoke. Hooks são listas de argv, nunca comandos shell recebidos do CI.
O mesmo lock do adaptador cobre QA, backup, migration e promoção. Recuperação de
uma execução interrompida precisa de reconciliação antes de tentar outra release.

O executor mantém bloqueio enquanto a baseline não tem digests pessoais e probes
verificáveis para promoção e rollback. Ele usa o adaptador Coolify já testado para
snapshot privado, detecção de drift e rollback das imagens em falha. Não reverte DB.
Se houver conflito com mudança manual do Compose, exige intervenção, sem sobrescrever.

Os exemplos de hooks estão intencionalmente vazios: não contornar backup ou drain
com `true`. É necessário instalar os comandos de operação específicos da produção,
ensaiá-los no staging e aprovar a baseline antes de habilitar o transporte.

## Backup disponível

O usuário autorizou o MinIO na mesma VPS provisoriamente. O ensaio criou um
backup novo, restaurou em PostgreSQL isolado sem rede e verificou criptografia,
upload, retenção, download e integridade. `offsite_verified=false` continua
verdadeiro como registro de ausência de cópia externa. O backup não alterou
produção nem restaurou o banco ativo. Futuro destino externo: Google Drive com
[rclone Drive](https://rclone.org/drive/) e autorização inicial no Mac via
[remote setup](https://rclone.org/remote_setup/). A VPS envia somente arquivos
criptografados; verificar download e restauração antes de considerar a cópia válida.

## Ensaio das candidatas integradas

A candidata CRM `eeeeb6358ade3b36447819bc46f27f915da435fd` aplica o patch
`1798fee` sobre o código de produção `6da435a`. O conflito no postback foi
resolvido mantendo a verificação de proveniência antes do callback de dedup.
O Processor `bd69157bc53c10d7a6e6f0e98ea135a49a87d188` aplica `7e33dd4` sobre
`97e6460`; o Runtime permanece `24bdc1a`. As candidatas foram construídas
localmente por ID imutável e não são artefatos publicados de uma main integrada.

As quatro migrações passaram; os 11 containers ficaram saudáveis; as 609 rotas
CRM foram preservadas. O teste sintético agregou as três mensagens e processou
uma única chamada e um único postback, inclusive após repetição de evento.
O ensaio usa Processor e postback simulados, sem LLM nem envio externo.
O rollback por stack via Coolify foi forçado após a candidata saudável e retornou
às imagens anteriores com schema migrado. Produção permaneceu inalterada.

A main do CRM divergia da produção (16 commits exclusivos na main, 29 em
produção) e o Processor também (1 e 13). Além disso, o agregador ainda fixa
referências antigas. A etapa de ativação deve conciliar as bases de origem,
publicar os digests, aplicar probes revisados e ensaiar os hooks de produção.
A chave de leitura do agregador na VPS já foi provisionada; nenhuma chave SSH
root foi enviada ao GitHub. `PRODUCTION_DEPLOY_ENABLED` foi verificado falso.

A promoção preparada usa o endpoint `/start` de cada aplicação alterada, com
`--no-deps`, serializado e verificado por versão/saúde. PostgreSQL e Redis não são
alvos desse adaptador. Os probes `/ready` de Core e Gateway foram confirmados
no staging com as imagens de referência. Para o drain, seguir o ciclo
[TSTP/TERM documentado pelo Sidekiq](https://github.com/sidekiq/sidekiq/wiki/Deployment)
e verificar também os turnos pendentes do runtime.

## Promoção manual autorizada

O rollback seletivo foi ensaiado no staging após uma falha intencional. Os IDs
e horários de início do PostgreSQL e Redis permaneceram iguais durante promoção
e rollback; o staging foi desligado após o ensaio. Os 64 testes dos controles
passaram e o workflow local passou no actionlint.

As três imagens testadas foram publicadas no GHCR por digest e promovidas
manualmente para produção. CRM e Sidekiq usam `eeeeb63` (`sha256:681278e27da6…`),
Processor usa `bd69157` (`sha256:dbe2f7fda92b…`) e Runtime usa `24bdc1a`
(`sha256:64a739d9b012…`). Backup fresco restaurado e verificado no MinIO local.
As migrations CRM `20261110120000` e `20261110140000` passaram. Uma entrada
legada de outubro foi preservada em quarentena junto com o buffer; sem reenvio.

Verificação final: quatro containers saudáveis, PostgreSQL e Redis sem reinício,
HTTPS público 200, zero pendências legadas e duráveis na amostra e zero containers
ativos no staging. O auto deploy da main continua desativado.

## Acesso do Actions e ensaio antes da promoção

O usuário SSH `evocrm-deploy` usa chave exclusiva guardada no Environment
`production`, permitido exclusivamente para a branch `main`. A porta é 2244.
A chave do servidor foi obtida pela conexão administrativa autenticada.
O usuário recebe um comando forçado, sem terminal nem forwarding. O sudo
permite somente o dispatcher instalado e pertencente ao root. Os comandos
permitidos são consulta de acesso, ensaio e envio do manifesto de produção.

O job `qa-on-vps` roda após os builds e scans. O host confere a main atual,
os repositórios e os labels das imagens, executa migrações e contrato de rotas
no staging sintético, ensaia o retorno e desliga o staging. A promoção depende
desse job e da ativação explícita no GitHub e no arquivo privado do host.
Uma operação assíncrona sem resultado confirmado restaura a configuração
desejada e exige reconciliação dos jobs do Coolify antes de retomar workers.

As referências do agregador correspondem às imagens já publicadas.
A integração nas mains dos módulos depende de seus checks e aprovações.
A ativação continua pendente da conciliação de todas as imagens de retorno
e da instalação e validação dos hooks de produção.

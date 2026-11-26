# Fluxo de publicação e deploy do EvoCRM

O único caminho autorizado para promover a stack completa EvoCRM é
`.github/workflows/auto-release.yml`. O workflow manual antigo foi removido
porque era um stub que sempre falhava antes de qualquer deploy e aceitava
variáveis com comandos arbitrários sem executá-los.

## Etapas automatizadas

1. Aguarda o workflow `CI` concluir com sucesso para um `push` na `main` deste
   repositório, rejeitando PRs, forks e commits obsoletos.
2. Confere os gitlinks dos módulos, executa QA, constrói imagens de cada
   componente por digest e verifica SBOM, proveniência e vulnerabilidades.
3. Envia um manifesto restrito ao executor SSH de comando forçado para ensaio
   em staging. O executor verifica migrações, saúde, contratos e rollback antes
   de aceitar a etapa de promoção.
4. A promoção só é considerada quando a flag `PRODUCTION_DEPLOY_ENABLED` está
   habilitada e o Environment `production` autoriza o job. O executor confirma
   backup restaurável, faz drain, executa migrations controladas, promove,
   verifica a saúde e o smoke test, e reverte somente as imagens em caso de
   falha. A base de dados nunca é revertida automaticamente.

Os jobs compartilham concorrência sem cancelamento, e o executor mantém um lock
no host. Artefatos e logs privados de produção não são enviados como artefatos
do Actions.

## Estado atual e limites

`PRODUCTION_DEPLOY_ENABLED` está configurada como `false`. O workflow de release
está bloqueado por isso e por gates adicionais do executor. Uma execução de
novembro falhou ao detectar que vários gitlinks não correspondiam à `main` dos
módulos; outro candidato falhou na varredura de imagens. Os gitlinks precisam
ser revisados e alinhados módulo por módulo, e imagens precisam passar pelos
scans antes de uma promoção.

Esse fluxo constrói e promove a stack por imagens com digests imutáveis. Ele não
repuxa somente o serviço CRM mantendo `:latest`. Não habilite a flag para
implantar uma única imagem móvel. Um fluxo CRM-only que preserve `latest` exige
um executor restrito separado, que valide o digest e a revisão do artefato e
atualize somente CRM e Sidekiq, com backup, verificação de saúde e rollback
ensaiados. Até essa implementação ser revisada, mantenha a promoção desligada.

O workflow de verificação de acesso (`deploy-access-check.yml`) comprova somente
que o transporte ao executor restrito funciona. Ele não aprova uma release e
não implanta serviços.

## Repull seletivo do CRM (preparado, desativado)

O workflow `crm-repull.yml` recebe o SHA completo do CRM e o digest aprovado da
imagem, exige execução a partir da `main`, Environment `production` e a variável
`CRM_REPULL_ENABLED=true`. O executor instalado no host também exige os gates
`crm_repull_enabled` e `crm_repull_rehearsed`. O exemplo de configuração mantém
ambos falsos. Não os habilite antes de revisar o executor, instalá-lo pelo
procedimento restrito e ensaiar no staging os mesmos hooks e imagens.

O executor usa o lock da stack, confere `latest` contra a tag de SHA e o digest
aprovado, verifica a configuração e os containers, executa hooks de backup,
restore de storage, compatibilidade de schema e drain, e recria apenas CRM e
Sidekiq com Compose síncrono e sem pull adicional. O Compose do Coolify mantém
`latest`. Em falha de saúde ou smoke, restaura a imagem anterior na tag local e
verifica a recuperação. Falha ou timeout do comando de recriação exige
reconciliação, pois o resultado pode ser ambíguo. Nunca reverte o banco.

Os hooks são configurados no host em listas argv root-owned. O exemplo não
contém implementações de compatibilidade, storage, drain ou smoke: devem ser
escritas e ensaiadas antes da ativação. O backup existente de MinIO é na mesma
VPS e não constitui cópia externa. O snapshot de storage deve ser verificado e
sua consistência com o banco tratada pelo operador. As verificações de saúde não
substituem teste funcional autenticado da pipeline.

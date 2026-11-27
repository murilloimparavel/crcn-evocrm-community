# Repull seletivo de CRM e Sidekiq

Este runbook descreve o fluxo em desenvolvimento. A implementação ainda não está pronta para produção; acompanhe o estado e as evidências em [CRM-REPULL-CHECKLIST.md](CRM-REPULL-CHECKLIST.md).

## Componentes e fluxo

O usuário informa no GitHub Actions o SHA do CRM e o digest aprovado da imagem. O workflow `.github/workflows/crm-repull.yml` exige a branch `main`, confirmação explícita, flag `CRM_REPULL_ENABLED` e acesso ao Environment `production`. Uma chave SSH restrita encaminha um manifesto ao executor instalado no host. O manifesto não pode conter comandos arbitrários.

O executor confirma a imagem e a configuração, verifica backup e compatibilidade por hooks instalados no host, drena o Sidekiq, recria apenas `evocrm_crm` e `evocrm_crm_sidekiq` e verifica saúde e smoke autenticado. O Compose continua referenciando `latest`; o digest aprovado e os IDs efetivos precisam ser registrados separadamente, pois `latest` pode mudar.

A promoção seletiva e a release da stack compartilham o lock do host. O lock não impede alterações manuais no Coolify ou Docker. Confirme a ausência de outras operações e recuse o deploy se o Compose ou os containers mudarem após a captura.

## Falhas e recuperação

- **Smoke falhou depois da recriação confirmada:** tentar rollback da aplicação para a imagem anterior, aguardar saúde, repetir smoke e retomar o worker.
- **Timeout, falha parcial ou resultado incerto da recriação:** registrar `reconciliation-required`, interromper novas tentativas e verificar o estado real antes de qualquer ação. Uma operação pendente pode competir com o rollback.
- **Drain ou retomada falharam:** registrar reconciliação e verificar o estado das filas e do worker.
- **Drift no Coolify:** não sobrescrever alterações concorrentes; reconciliar com o operador.

Rollback não restaura automaticamente o banco. Uma imagem anterior só é uma opção de recuperação se for acessível e compatível com o schema atual. Conserve o digest anterior e uma referência imutável no registry; uma cópia local pode ser apagada por limpeza Docker. Não mova a tag `latest` no registry sem autorização para essa ação.

## Como modificar o fluxo

1. Trabalhe em uma branch e revise separadamente workflow, dispatcher, executor, hooks e configuração de exemplo. Não inclua tokens, `.env`, dados ou snapshots privados.
2. Preserve a seleção fixa dos serviços, o lock, a verificação de digest, as regras de reconciliação e os gates de produção. Não execute comandos fornecidos pelo input do Actions.
3. Adicione testes para o comportamento alterado, incluindo tipos reais de erros dos subprocessos, operações parciais e isolamento de produção/staging.
4. Valide o workflow no CI e ensaie a mesma versão do executor no staging isolado. O staging deve usar rede e volumes próprios, imagens e tag exclusivas, usuário e pipeline sintéticos e encerramento garantido.
5. Documente SHA, digests, resultados, rollback e limitações. Revise o PR e confirme checks antes de integrar.
6. Instale no host somente a versão revisada e root-owned, com dispatcher restrito. Verifique backup restaurável, health checks, compatibilidade de schema e rollback ensaiado antes de ativar qualquer gate.

O Environment `production` e os comandos instalados devem ser verificados no momento da ativação. Um Environment com política de branch não comprova por si só a existência de aprovador obrigatório. Um HTTP 2xx do Coolify ou container `running` não comprova que o deploy terminou de forma saudável.

## Referências

- `scripts/deploy/crm-repull-executor.py`: validação e execução da operação.
- `scripts/deploy/crm-repull-plan.py`: validação dos serviços e da imagem.
- `scripts/deploy/ssh-entrypoint.sh` e `ssh-dispatch.py`: entrada SSH restrita.
- `deploy/executor-config.example.json`: gates e hooks previstos, desativados por padrão.
- [PRODUCTION-DEPLOYMENT.md](PRODUCTION-DEPLOYMENT.md): release coordenada e limites atuais.

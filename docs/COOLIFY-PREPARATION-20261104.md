# Coolify Caldas: merges e preparação — 04/11/2026

Estado: **produção não liberada**. Nenhum deploy ou migration de produção foi
executado por esta preparação. O fluxo de produção do agregador continua com
bloqueio explícito e sem executor de promoção instalado.

## Merges

| Repositório | PR | Resultado |
|---|---|---|
| Agregador | [#2](https://github.com/murilloimparavel/crcn-evocrm-community/pull/2) | Merge `48fd89dcf1407f78c563a90eb0ee7c887f89478c` |
| Sofia | [#24](https://github.com/murilloimparavel/sofia-central-frontend/pull/24) | Merge `20773efacb25f1a50d36bcb1641b0ae93a72fc6a` |
| Search | [#9](https://github.com/murilloimparavel/crcn-search-api/pull/9) | Merge `62e032489659e8e5933ab8c92a986745e0062583` |
| Auth | [#2](https://github.com/murilloimparavel/evo-auth-service-community/pull/2) | Revisão externa obrigatória pendente |
| CRM | [#32](https://github.com/murilloimparavel/evo-ai-crm-community/pull/32) | Revisão externa obrigatória pendente |
| Processor | [#13](https://github.com/murilloimparavel/evo-ai-processor-community/pull/13) | Revisão externa obrigatória pendente |
| Core | [#1](https://github.com/murilloimparavel/evo-ai-core-service-community/pull/1) | Revisão externa obrigatória pendente |
| Runtime | [#6](https://github.com/murilloimparavel/evo-bot-runtime/pull/6) | Revisão externa obrigatória pendente |
| Flow | [#1](https://github.com/murilloimparavel/evo-flow-community/pull/1) | Revisão externa obrigatória pendente |
| Evolution API | [#1](https://github.com/murilloimparavel/evolution-api/pull/1) | Revisão externa obrigatória pendente |
| Evolution Go | [#1](https://github.com/murilloimparavel/evolution-go/pull/1) | Revisão externa obrigatória pendente |

Os onze heads tinham checks verdes antes da operação. Foram usados merges normais,
com correspondência ao SHA validado. A regra de uma aprovação dos oito módulos
públicos foi preservada. Nenhum gitlink foi avançado em lote.

## Travas de produção

- O workflow Search `Publish Search API image` foi desabilitado pela API **antes**
  do merge; ele contém uma chamada real ao Coolify. Permanece desabilitado.
- `PRODUCTION_DEPLOY_ENABLED=false` configurado e conferido no agregador e Search.
- Esta preparação adiciona a condição explícita dessa variável nos dois workflows
  de deploy. O agregador mantém também seu `exit 1` de bloqueio.
- O publisher de imagens da Sofia concluiu após o merge. Publicação de imagem
  não foi acompanhada de chamada de deploy por esta preparação.
- Existem workflows históricos de candidatos em outras branches. Eles não estão
  na `main` auditada e não foram usados para promover produção nesta operação.

## Validações reais no servidor

Host: `vps-caldas`; Coolify 4.5.3; Service UUID
`tzbydmxtjuilf4xq2gow9gcs`.

- Compose efetivo validado com `docker compose config --quiet`: exit 0.
- Dump lógico PostgreSQL criado e restaurado em container sem rede, com a mesma
  imagem pgvector por digest. `pg_restore --exit-on-error` concluiu; **137 tabelas
  públicas** verificadas. Arquivo de 138.128.351 bytes, checksum e permissão 600.
- Storage Auth e CRM lidos por mounts somente de leitura, arquivados e restaurados
  em volumes temporários. `tar --compare` confirmou a cópia restaurada. O arquivo
  Auth tem 10.240 bytes (volume sem arquivos nesta coleta); CRM, 286.525.440 bytes.
- Containers e volumes temporários dos ensaios foram removidos. Arquivos de backup,
  checksums e logs permanecem privados em `/var/backups/evocrm-validation`.
- **Não foram comprovados:** cópia externa, retenção, roles/grants, restauração
  funcional da aplicação e consistência do mesmo instante entre DB e storage.
  O dump usa `--no-owner --no-acl`; não é uma prova de recuperação completa de RLS.
- Snapshot privado do Compose e inventário sem valores de ambiente foram guardados
  em `/data/evocrm-deploy-preparation`, sem copiar dados de clientes para o Git.
- Overlay candidato `deploy/compose.coolify.healthchecks.yml` mesclado com o
  Compose real apenas para `docker compose config --quiet`: exit 0. Não foi
  aplicado; os probes e as imagens finais ainda precisam de ensaio em staging.
- A leitura atual mantém sete serviços de aplicação sem healthcheck Docker. Gateway
  e Core ainda usam `evoapicloud/*:latest`; os demais usam pacotes personalizados,
  que precisam de conciliação antes de trocar por imagens genéricas do agregador.
- Houve uma atualização de CRM/Sofia por outro processo antes dos merges:
  `services.updated_at=15:06:34 UTC`, containers iniciados às 15:06:48 UTC;
  os merges desta operação foram às 15:07:42 UTC. O snapshot foi atualizado para
  refletir esse estado, sem sobrescrever a configuração do serviço.

## Adaptador preparado, sem ativação

`scripts/deploy/coolify-service.py` contém o cliente do contrato instalado:

- PATCH `/api/v1/services/{uuid}` com Compose base64 e `instant_deploy=false`;
- POST `/api/v1/deploy` para o UUID fixo do EvoCRM;
- verificação local das imagens efetivas e healthcheck de todos os serviços,
  exigindo rodadas consecutivas saudáveis, além do smoke fornecido pelo executor;
- snapshot privado e sincronizado em disco antes da primeira escrita, lock local
  exclusivo e validação do hash do Compose para detectar drift;
- rollback de **aplicação** em falha de escrita ambígua, deploy, health ou smoke,
  com verificação da recuperação. Nunca restaura banco automaticamente;
- recusa de rollback se detectar uma edição concorrente desconhecida;
- recusa de redirects com token, HTTP, outros recursos e endpoints não permitidos,
  inclusive GET `/deploy`, que não pode contornar o bloqueio de escrita.

O CLI expõe somente planejamento. `promote()` é uma biblioteca sem chamador ativo;
o futuro executor precisa verificar QA, backup, migration e aprovação antes de
chamá-la. Não foi instalado serviço, timer, webhook, runner de produção ou token
mutável. Um lock local não impede edição pelo painel Coolify: haverá necessidade
operacional de congelar mudanças concorrentes durante a promoção.

**32 testes locais passaram**, incluindo rollback simulado, drift, exclusão mútua,
privacidade do snapshot e bloqueio de mutações. Não representam um ensaio real de
promover/reverter a aplicação no Coolify. O código foi apenas colocado no diretório
de preparação do servidor, sem executar promoção.

## O que ainda falta antes de ativar

1. Aprovação externa e merge dos oito módulos protegidos.
2. Plano GitHub compatível para proteger agregador, Sofia e Search privados.
3. Staging isolado com dados sintéticos; imagens finais por digest e revisão
   individual de commits e dos pacotes personalizados atuais.
4. QA/E2E e ensaio real de promoção/rollback no Coolify staging, com token de
   privilégio mínimo e verificação de estado dos containers, sem confiar apenas
   em HTTP 200 da API de deploy. Services não retornam deployment UUID de Application.
5. Healthchecks reais para Gateway/Core e demais serviços, heartbeat dos workers
   e smoke funcional autenticado. Validar os comandos nas imagens exatas.
6. Tirar migrations/seeds do startup e criar executor único, ordenado e fail-fast,
   com lock, expand/contract e restauração funcional ensaiada.
7. Backup externo criptografado, retenção, roles/grants, cobertura de eventual
   armazenamento remoto e RPO/RTO/consistência entre banco e anexos.
8. Integrar o adaptador ao executor confiável, com evidências verificadas do SHA
   liberado, alertas e aprovação. O token de produção não foi instalado no CI.
9. Apresentar os resultados e pendências ao responsável e obter liberação de
   ativação. Até lá, manter flag false, workflow Search desabilitado e stub bloqueado.

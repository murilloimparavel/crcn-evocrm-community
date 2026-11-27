# Checklist de repull seletivo do CRM

Objetivo: implantar CRM e Sidekiq mantendo `latest` na configuração, com imagem aprovada por digest, backup verificável, smoke autenticado e rollback de aplicação.

Estado: desenvolvimento. Executor não instalado e gates de produção desativados. Uma caixa só deve ser marcada com evidência específica, não apenas com código escrito.

## Sprint 1: correção e controle de falhas

- [x] Corrigir caminho de rollback para falha confirmada do smoke, usando o mesmo tipo de exceção do subprocesso.
- [x] Registrar reconciliação se o drain falhar ou se a retomada após rollback falhar.
- [x] Testar localmente falha do smoke, timeout de recriação e falhas de drain e retomada.
- [ ] Revisar CI e integrar a correção na main.
- [ ] Cobrir falha parcial de recriação, drift concorrente e interrupções adicionais antes da ativação.

## Sprint 2: hooks e isolamento de staging

- [ ] Integrar ponto de entrada específico de staging, rede interna, volumes e tag exclusivos.
- [ ] Revisar e testar hooks de backup e restauração do banco e storage.
- [ ] Validar compatibilidade da candidata e da imagem anterior com o schema.
- [ ] Implementar drain e retomada verificáveis do Sidekiq do CRM.
- [ ] Criar usuário, permissões, pipeline, etapa e item sintéticos em staging.
- [ ] Gerar credencial temporária e verificar smoke autenticado e rejeição de credencial inválida.
- [ ] Revisar e publicar os hooks com testes e sem dados ou credenciais.

## Sprint 3: ensaio real no staging

- [ ] Registrar imagens, Compose e estado anterior; validar isolamento e lock.
- [ ] Executar backup e restore verificados.
- [ ] Promover a candidata e verificar CRM, Sidekiq e smoke autenticado.
- [ ] Forçar falha e verificar rollback da imagem, smoke e retomada das filas.
- [ ] Ensaiar timeout, drift e resultado parcial sem operação concorrente.
- [ ] Confirmar que banco e Redis não foram recriados, limpar recursos e desligar staging.
- [ ] Registrar digests, resultado e limitações do ensaio.

## Sprint 4: preparação e ativação de produção

- [ ] Revisar origem, CI e digest candidato; guardar referência imutável de rollback no GHCR.
- [ ] Verificar backup recente, restauração, storage e política de cópia externa.
- [ ] Revisar Environment production, acesso restrito e aprovação aplicável.
- [ ] Instalar o executor e hooks revisados no host e confirmar versão e permissões.
- [ ] Habilitar gates somente após evidências de staging e checagens de produção.
- [ ] Executar repull autorizado de CRM e Sidekiq e verificar imagem, saúde, filas e painel.
- [ ] Registrar resultado, reconciliação ou rollback, sem incluir segredos.

## Evidências

- PR #15 integrou o executor inicial e manteve os gates desligados.
- A baseline do staging passou em migrations e saúde; o ciclo não ensaiou rollback.
- A Sprint 1 foi testada localmente; a execução real de staging ainda está pendente.

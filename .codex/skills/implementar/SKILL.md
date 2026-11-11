---
name: implementar
description: Implementa a solicitação no repositório correto, valida e encaminha revisão independente sem publicar sem autorização.
---

# Implementar

1. Leia instruções aplicáveis, pedido e critérios de aceite. Confirme repositório, branch, estado de trabalho e remote autorizado.
2. Preserve trabalho preexistente. Se a árvore estiver suja ou o módulo estiver em uso, implemente em clone/worktree isolado; nunca descarte ou inclua mudanças alheias.
3. Faça a menor solução completa, seguindo padrões do projeto e cobrindo autorização, persistência, concorrência e compatibilidade quando aplicáveis.
4. Rode validações direcionadas e examine o diff. Não encerre apenas porque os testes passaram.
5. Antes de propor merge, peça revisão independente a um subagent que não implementou a mudança. Forneça pedido e critérios, mas deixe-o inspecionar o diff sem conduzir a conclusão. Corrija achados confirmados e solicite novo review após cada atualização relevante.
6. Prossiga automaticamente pelos passos já autorizados. Peça decisão humana somente para escolha de produto/risco material, falta de acesso ou ação fora do escopo autorizado; explique o bloqueio específico e avance o trabalho independente.

Informe arquivos, validações, resultado da revisão independente, mudanças remotas realizadas apenas quando autorizadas, e pendências reais. Não faça commit, push, merge ou deploy sem autorização explícita aplicável.

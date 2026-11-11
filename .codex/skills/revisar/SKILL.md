---
name: revisar
description: Revisa implementação local ou PR no GitHub com evidência independente, identifica bloqueios e encaminha correções até novo review quando autorizado.
---

# Revisar

O objetivo é levar a mudança a uma decisão de qualidade verificável, sem confundir análise com conclusão. O autor da implementação não pode ser o único revisor: para mudanças de código, segurança ou deploy, use um subagent independente para revisar o diff; quem implementou não deve orientar o subagent além do escopo e critérios de aceite.

1. Leia as instruções aplicáveis, pedido original, critérios de aceite, diff integral e código adjacente. Confira autor, branch, SHA, estado do PR e checks atuais.
2. Separe implementação e revisão. Peça a um subagent independente revisão adversarial do diff e validações, sem editar arquivos. Faça também sua própria conferência e reconcilie achados com evidência do código/testes.
3. Se o usuário pediu revisão no GitHub ou já autorizou a revisão do PR, registre lá `APPROVE`, `REQUEST_CHANGES` ou `COMMENT` conforme evidência. Não use aprovação para sinalizar progresso. Sem autorização para registrar externamente, produza parecer local.
4. Para cada bloqueio corrigível localmente e autorizado, encaminhe a correção ao implementador (preferencialmente agente diferente do revisor), acompanhe-a até novo SHA e rode os checks pertinentes. Depois peça ao revisor independente que revise novamente o diff atualizado. Se depender de autor externo, faça um único acompanhamento após o próximo checkpoint útil do PR/CI (ou um intervalo razoável, no máximo 30 minutos nesta execução); sem atualização, encerre como `aguardando autor`, registre o pedido já feito e prossiga com outras tarefas independentes, sem repetir cobranças. Se uma PR ampla não couber em uma única revisão, divida por áreas/arquivos até cobrir o conjunto; se o contexto ou acesso acabar, registre `revisão parcial` e o subconjunto pendente sem alegar cobertura integral.
5. Não encerre ao encontrar um problema: registre todos os bloqueios conhecidos, proponha e execute próximos passos já autorizados e verifique o resultado. Só pare diante de limite real (credencial/acesso indisponível, decisão de produto/risco fora do escopo ou operação irreversível sem autorização).
6. Verifique checks exigidos, scan de segurança quando aplicável, compatibilidade e estado final do review. Antes de tratar review como aprovação GitHub válida, confirme que o autor é diferente, a conta revisora tem permissão e as regras de proteção aceitam essa identidade. Não confunda revisão de subagent com review GitHub, CI verde com aprovação nem review `COMMENT` com aprovação.

Relate achados por severidade com caminho/linha, cenário e evidência; liste correções feitas, revisão independente, checks e bloqueios restantes. Se cobertura não foi integral, declare precisamente o que faltou e continue o trabalho possível.

Não faça commit, push, merge ou deploy salvo pedido explícito ou autorização já presente na tarefa. Preserve alterações existentes e use clones/worktrees isolados para evitar sobrescrever trabalho em curso.

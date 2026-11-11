---
name: publicar
description: Investiga, revisa e executa publicação autorizada, acompanhando CI/deploy e rollback até estado comprovado.
---

# Publicar

Um pedido explícito autoriza apenas a ação e o destino claramente solicitados, mais os passos rotineiros indispensáveis dentro desse escopo. Deploy não implica merge, push à branch protegida, atualização de gitlinks ou publicação de outra PR. Não peça aprovação repetida para etapas rotineiras já autorizadas. Respeite sempre instruções do repositório; elas prevalecem sobre escolhas genéricas desta skill.

1. Leia instruções, confira estado/diff/SHA e remote. Confirme que o remote está na lista autorizada; nunca adicione `upstream` nem avance gitlinks em lote.
2. Descubra workflow, gatilho, checks, ambiente, migrations, health checks e rollback. Não presuma que push à `main` publica.
3. Faça revisão independente antes de merge: o implementador não pode ser o único revisor. Use subagent distinto para revisar diff e evidências; corrija achados, peça nova revisão e aguarde checks obrigatórios. Uma revisão de subagent não conta por si só como aprovação do GitHub: confirme que a conta que registrará o review é distinta do autor, tem permissão e pode satisfazer as regras da branch. Se isso falhar, reporte como bloqueio externo sem declarar aprovação.
4. Se o usuário autorizou publicação, prepare e execute a operação no escopo pedido após gates passarem. Comunique destino e andamento de forma concisa; não interrompa para escolhas operacionais rotineiras.
5. Acompanhe CI, deploy e health checks até estado terminal. Verifique versão ativa e fluxos críticos. Em falha, pare novas tentativas. Execute rollback somente se esse rollback específico estiver documentado no plano e coberto pela autorização; caso contrário use apenas um forward-fix seguro já autorizado ou solicite autorização para o rollback concreto. Não reverta dados destrutivamente.
6. Se houver bloqueio, faça o diagnóstico e toda correção possível dentro da autorização. Solicite decisão apenas para risco/escopo novo, autorização realmente necessária ou credencial indisponível, com evidência e ação concreta.

Registre PR/SHA, review independente, checks, mecanismo, health pós-publicação e rollback ou limitação. Nunca declare conclusão sem evidência verificável.

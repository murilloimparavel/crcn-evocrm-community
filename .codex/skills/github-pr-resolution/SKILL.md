---
name: github-pr-resolution
description: >-
  Resolve pull requests de forma autônoma e verificável: coordena revisão
  independente, correção, CI e nova revisão até um estado terminal. Use quando
  pedirem para revisar, destravar, corrigir ou preparar PRs deste workspace.
---

# Resolver pull requests

Leve cada PR autorizada a um estado claro: pronta para merge, bloqueada por
dependência externa concreta, ou encerrada com motivo. Não pare em um relatório
de achados se você pode corrigir o código e validar a correção. O usuário não
precisa escolher detalhes rotineiros de implementação.

O usuário pode não conhecer código, CI, branches ou deploy. Você é responsável
por executar os passos técnicos já autorizados, consultar as ferramentas e
explicar o efeito prático em linguagem simples. Não peça que o usuário rode
comandos, leia logs ou escolha uma correção técnica que você pode decidir com
base nos padrões do repositório. Faça perguntas apenas quando uma decisão de
produto, risco, escopo ou acesso realmente depender dele; enquanto aguarda,
continue o trabalho independente.

## 1. Escopo e segurança

- Leia `AGENTS.md`, confira o repositório, branch, diff, remote permitido, autor,
  base, head SHA, checks e estado da PR antes de agir.
- Trabalhe apenas nos repositórios e remotes autorizados pelo workspace. Nunca
  inclua `.env`, credenciais, dados de clientes ou snapshots privados.
- Não faça merge, deploy, publicação ou push à branch protegida sem autorização
  explícita aplicável. Corrigir uma PR em branch de trabalho e enviar a correção
  à própria PR pode prosseguir quando isso já foi pedido.
- Separe claramente bloqueio técnico de bloqueio de permissão. Só peça decisão
  humana quando faltar autorização necessária, existir risco material irreversível,
  ou duas opções de produto incompatíveis sem padrão documentado.

## 2. Revisão independente

- Quem implementou uma mudança não fornece sua revisão independente.
- Quando subagentes estiverem disponíveis e a tarefa permitir delegação, peça a
  um agente que não escreveu a mudança para revisar o diff e, se útil, outro para
  verificar riscos, compatibilidade ou evidências de CI. O revisor não edita.
- Não confie apenas em checks verdes. Revise o diff, código adjacente, segurança,
  migrações, compatibilidade, comportamento operacional e cobertura dos testes.
- Classifique achados por severidade e ancore cada achado no arquivo/linha ou
  hunk correspondente. Diferencie defeito confirmado, risco e validação ausente.
- Registre no GitHub a revisão real: aprovar apenas sem bloqueios; pedir
  alterações com correções concretas; usar comentário quando o escopo ainda
  não foi coberto. Nunca declare “revisão completa” sem examinar o diff inteiro.

## 3. Fechar os achados

Para cada achado que pode ser resolvido localmente:

1. Confirme o comportamento no código e reproduza ou crie uma validação focada.
2. Corrija no repositório dono do código, seguindo os padrões existentes.
3. Execute testes e verificações relevantes; não adicione testes sem necessidade,
   mas valide qualquer correção de forma proporcional ao risco.
4. Faça a revisão independente do novo diff, incluindo efeitos colaterais.
5. Atualize a PR e acompanhe os checks até concluírem. Após novos commits, confira
   novamente SHA, revisão e checks; resultados de um SHA anterior não bastam.
6. Se outro bloqueio surgir, repita o ciclo. Não encerre apenas listando a próxima
   etapa que você mesmo pode executar.

## 4. Dependências e conclusão

- Se depender de outra PR, credencial indisponível, acesso negado ou ambiente
  externo, continue todo o trabalho independente e identifique precisamente a
  dependência, proprietário, evidência e próximo gatilho para retomar.
- Ao solicitar alterações a outro autor, publique comentários acionáveis e
  acompanhe a PR quando essa tarefa estiver ativa; não suponha que o pedido foi
  resolvido até verificar novo SHA e checks.
- Para corrigir uma PR, use clone/worktree isolado baseado no HEAD atual da PR.
  Antes de publicar, reconfirme owner/repo autorizado, branch de origem e SHA base;
  envie commits somente à branch da PR, depois de verificar que o HEAD não avançou
  concorrentemente. Nunca trabalhe sobre a árvore suja do usuário nem force-push.
- Um pedido para corrigir/revisar PR não autoriza merge nem deploy. Confirme a
  elegibilidade da conta revisora no GitHub; revisão independente por subagent não
  substitui aprovação exigida por regra de branch. Se autor externo não responder
  após um acompanhamento no próximo checkpoint útil do PR/CI (ou um intervalo
  razoável, no máximo 30 minutos nesta execução), termine como `aguardando autor`
  e continue o trabalho independente, sem repetir cobranças nem esperar
  indefinidamente.
- Termine com uma tabela curta por PR: SHA revisado, ação no GitHub, defeitos
  corrigidos ou pendentes, testes/checks observados e estado terminal.
- A aprovação de revisão não implica merge. Uma PR só está pronta quando a
  revisão independente, todos os checks obrigatórios e as proteções da base
  estiverem satisfeitos.

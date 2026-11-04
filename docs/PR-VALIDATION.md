# Validação de PR por repositório

Preparação local em 04/11/2026. Workflows de PR não fazem deploy, push de imagem
nem usam credenciais de produção. Cada pipeline possui um check final que exige
sucesso dos jobs necessários, inclusive lint dos próprios workflows com actionlint
1.7.7. Falha, cancelamento ou job necessário pulado reprova o check final.

| Repositório | Workflow | Check final | Validações |
|---|---|---|---|
| crcn-evocrm-community | ci.yml | PR ready | Compose, Dockerfiles dos 10 módulos, migrations CRM/Auth, credencial de leitura, Actions e controles de deploy |
| evo-auth-service-community | test.yml | PR ready | RSpec existente e Actions |
| evo-ai-crm-community | ci.yml | CRM required checks | RuboCop, Brakeman, RSpec, build Docker sem publicação e Actions |
| sofia-central-frontend | test.yml | PR ready | TypeScript, builds moderno/Chrome 109, Vitest selecionado, ESLint do PR e Actions |
| evo-ai-core-service-community | go-test.yml | PR ready | Build, vet e testes Go com go.community.mod e Actions |
| evo-bot-runtime | ci.yml | PR ready | Build, vet e testes Go com Redis isolado e Actions |
| evo-ai-processor-community | pr-validation.yml | PR ready | Pytest unitário e integração, Actions |
| evo-flow-community | pr-validation.yml | PR ready | Build Nest/TypeScript, guard tenant-db, Jest e Actions |
| evolution-api | check_code_quality.yml | PR ready | ESLint, geração Prisma PostgreSQL, build e Actions |
| evolution-go | pr-validation.yml | PR ready | Build, vet e testes Go, dependências nativas, Actions |
| crcn-search-api | pr-validation.yml | PR ready | Testes de regressão e integração npm, Actions |

## Limites e pré-requisitos

- Auth conserva três exclusões históricas explícitas no comando RSpec; Sofia
  conserva a lista de testes Vitest selecionados. Esses checks não atestam a
  suíte inteira desses módulos. Evolution API não tem diretório `test/` no
  checkout; o script npm test é watch e não foi usado como teste fictício de CI.
- Guardas existentes dos módulos continuam separados. Checks condicionais por
  caminhos não foram transformados em requisitos globais de merge.
- O agregador precisa de `SUBMODULES_SSH_KEYS`, com **somente leitura** dos dez
  repositórios pessoais. A listagem de nomes dos secrets do agregador retornou
  vazia nesta sessão. Não reutilizar o token pessoal amplo do `gh` nesse secret.
  Sem a credencial, o check explica a falha e não aprova silenciosamente.
- PR de fork sem acesso aos secrets não consegue validar os módulos privados;
  trazer o commit para branch interna revisada. Não usar pull_request_target para
  executar código de PR com credenciais privilegiadas.
- Os workflows precisam ser revisados e publicados nos respectivos repositórios.
  A preparação não faz commit/push nem avança os gitlinks do agregador.
- Depois da primeira execução real bem-sucedida, configurar a proteção de
  main/develop para exigir o check final da tabela e revisão de PR. A consulta
  anterior do agregador retornou HTTP 403 por limitação do plano privado. Ainda
  não foi comprovado suporte de proteção em cada módulo. CI sem proteção de
  branch não impede merge manual de PR vermelho.
- Novas suítes podem revelar falhas ou dependências preexistentes. Corrigir os
  problemas, não usar continue-on-error, passWithNoTests ou exclusões novas só
  para produzir um check verde.

## Validação local

Actionlint executado sobre todos os workflows do agregador e dos dez módulos.
Foi corrigido o input inexistente ruby-version-file em ruby/setup-ruby do Auth;
a action detecta .ruby-version automaticamente. Evolution API passou a declarar
DATABASE_PROVIDER=postgresql para gerar Prisma e não inicializa o submódulo opcional
externo manager durante CI. Nenhuma dependência de aplicação foi alterada.

Execuções completas de Ruby, Python, Go, build Docker, Nest e frontend ainda
precisam ocorrer nos runners. A validação estática do workflow não comprova que
as suítes de aplicação passam.

A suíte npm completa do Search API foi executada localmente. Foram detectados
e corrigidos dois testes com datas expiradas, fixando somente o relógio da
dependência de datas nos testes. As validações de data da aplicação permanecem
ativas, incluindo o cenário de rejeição de datas passadas. Os 15 testes dos
controles de deploy do agregador também passaram.

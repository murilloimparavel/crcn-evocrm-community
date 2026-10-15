# CRCN EvoCRM Community

Agregador privado dos módulos EvoCRM usados pela Central de Reservas Caldas Novas (CRCN). Cada componente permanece no seu repositório próprio; este projeto registra os commits selecionados como submódulos Git.

## Módulos

| Caminho | Repositório |
| --- | --- |
| `services/evo-auth-service-community` | [murilloimparavel/evo-auth-service-community](https://github.com/murilloimparavel/evo-auth-service-community) |
| `services/evo-ai-crm-community` | [murilloimparavel/evo-ai-crm-community](https://github.com/murilloimparavel/evo-ai-crm-community) |
| `frontend/sofia-central-frontend` | [murilloimparavel/sofia-central-frontend](https://github.com/murilloimparavel/sofia-central-frontend) |
| `services/evo-ai-processor-community` | [murilloimparavel/evo-ai-processor-community](https://github.com/murilloimparavel/evo-ai-processor-community) |
| `services/evo-ai-core-service-community` | [murilloimparavel/evo-ai-core-service-community](https://github.com/murilloimparavel/evo-ai-core-service-community) |
| `services/evo-bot-runtime` | [murilloimparavel/evo-bot-runtime](https://github.com/murilloimparavel/evo-bot-runtime) |
| `services/evo-flow-community` | [murilloimparavel/evo-flow-community](https://github.com/murilloimparavel/evo-flow-community) |
| `services/evo-nexus` | [murilloimparavel/evo-nexus](https://github.com/murilloimparavel/evo-nexus) |
| `integrations/evolution-api` | [murilloimparavel/evolution-api](https://github.com/murilloimparavel/evolution-api) |
| `integrations/evolution-go` | [murilloimparavel/evolution-go](https://github.com/murilloimparavel/evolution-go) |

Todos os URLs de submódulos usam exclusivamente a conta `murilloimparavel`. Não configure remotes `upstream` para repositórios da organização `evolution-foundation` neste agregador.

## Clonar

```bash
git clone --recurse-submodules https://github.com/murilloimparavel/crcn-evocrm-community.git
```

Se já clonou sem os módulos:

```bash
git submodule update --init --recursive
```

## Atualizar módulos

Os submódulos ficam fixados em commits específicos no agregador. Para avançar todos para os commits das branches padrão remotas:

```bash
git submodule update --remote --merge
git status --short
git add .gitmodules services frontend integrations
git commit -m "chore: update EvoCRM modules"
git push
```

Revise cada atualização antes de registrar o novo gitlink. Alterações de código devem ser commitadas e enviadas no repositório do respectivo módulo antes de atualizar o agregador.

## Segurança

- Nunca adicione `.env`, credenciais, dumps de produção ou dados pessoais.
- Cada repositório de módulo mantém seu próprio histórico, permissões e fluxo de revisão.
- O agregador registra apenas referências Git (gitlinks), sem copiar o conteúdo dos módulos para este repositório.

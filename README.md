# CRCN EvoCRM Community

Agregador privado do stack EvoCRM operado pela Central de Reservas Caldas Novas. Assim como o repositório de referência, este repositório reúne os componentes em diretórios de primeiro nível e fixa cada módulo em um commit específico por meio de submódulos Git.

## Módulos

| Módulo | Repositório |
| --- | --- |
| `evo-auth-service-community` | [murilloimparavel/evo-auth-service-community](https://github.com/murilloimparavel/evo-auth-service-community) |
| `evo-ai-crm-community` | [murilloimparavel/evo-ai-crm-community](https://github.com/murilloimparavel/evo-ai-crm-community) |
| `sofia-central-frontend` | [murilloimparavel/sofia-central-frontend](https://github.com/murilloimparavel/sofia-central-frontend) |
| `evo-ai-processor-community` | [murilloimparavel/evo-ai-processor-community](https://github.com/murilloimparavel/evo-ai-processor-community) |
| `evo-ai-core-service-community` | [murilloimparavel/evo-ai-core-service-community](https://github.com/murilloimparavel/evo-ai-core-service-community) |
| `evo-bot-runtime` | [murilloimparavel/evo-bot-runtime](https://github.com/murilloimparavel/evo-bot-runtime) |
| `evo-flow-community` | [murilloimparavel/evo-flow-community](https://github.com/murilloimparavel/evo-flow-community) |
| `evo-nexus` | [murilloimparavel/evo-nexus](https://github.com/murilloimparavel/evo-nexus) |
| `evolution-api` | [murilloimparavel/evolution-api](https://github.com/murilloimparavel/evolution-api) |
| `evolution-go` | [murilloimparavel/evolution-go](https://github.com/murilloimparavel/evolution-go) |
| `crcn-search-api` | [murilloimparavel/crcn-search-api](https://github.com/murilloimparavel/crcn-search-api) |

Os módulos e arquivos de orquestração pertencem à conta `murilloimparavel`. O frontend canônico é `sofia-central-frontend`.

## Clonar o stack

```bash
git clone --recurse-submodules https://github.com/murilloimparavel/crcn-evocrm-community.git
```

Para inicializar os módulos de um clone existente:

```bash
git submodule update --init --recursive
```

## Atualizar módulos

O agregador registra referências imutáveis dos submódulos. Para avançar os módulos às branches padrão remotas e gravar os novos gitlinks:

```bash
git submodule update --remote --merge
git status --short
git add .gitmodules evo-auth-service-community evo-ai-crm-community sofia-central-frontend \
  evo-ai-processor-community evo-ai-core-service-community evo-bot-runtime \
  evo-flow-community evo-nexus evolution-api evolution-go crcn-search-api
git commit -m "chore: update EvoCRM modules"
git push
```

Revise as mudanças antes de registrar os novos commits. Desenvolva e publique código dentro do repositório do módulo correspondente.

## Segurança

- Não adicione `.env`, credenciais, dumps de produção ou dados pessoais.
- Cada módulo mantém seu histórico, permissões e fluxo de revisão próprios.
- Os submódulos apontam somente para repositórios `murilloimparavel`.

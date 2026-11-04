#!/usr/bin/env bash
set -euo pipefail

# Portable allowlist; compatible with macOS system Bash and GitHub runners.
expected_modules="$(cat <<'EOF'
evo-auth-service-community
evo-ai-crm-community
sofia-central-frontend
evo-ai-processor-community
evo-ai-core-service-community
evo-bot-runtime
evo-flow-community
evolution-api
evolution-go
crcn-search-api
EOF
)"

expected_count="$(printf '%s\n' "$expected_modules" | wc -l | tr -d ' ')"
actual_count="$(git config -f .gitmodules --get-regexp '^submodule\..*\.path$' | wc -l | tr -d ' ')"
if [[ "$actual_count" -ne "$expected_count" ]]; then
  echo "::error::.gitmodules contém $actual_count módulos; esperados $expected_count" >&2
  exit 1
fi

while IFS= read -r name; do
  path="$(git config -f .gitmodules --get "submodule.${name}.path")"
  url="$(git config -f .gitmodules --get "submodule.${name}.url")"
  wanted_url="https://github.com/murilloimparavel/${name}.git"
  if [[ "$path" != "$name" || "$url" != "$wanted_url" ]]; then
    echo "::error::submodule $name deve usar path=$name e URL $wanted_url" >&2
    exit 1
  fi
  if ! git ls-tree HEAD -- "$path" | awk '$1 == "160000" && $2 == "commit" { found=1 } END { exit !found }'; then
    echo "::error::$path não está registrado como gitlink no commit" >&2
    exit 1
  fi
done <<< "$expected_modules"

echo "OK: $expected_count submódulos apontam para os repositórios pessoais autorizados e estão fixados como gitlinks."

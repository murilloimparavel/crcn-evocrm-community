#!/bin/sh
set -eu
case "${SSH_ORIGINAL_COMMAND:-}" in
  access-check) exec /usr/bin/sudo -n /usr/local/sbin/evocrm-release-dispatch access-check ;;
  rehearse) exec /usr/bin/sudo -n /usr/local/sbin/evocrm-release-dispatch rehearse ;;
  '') exec /usr/bin/sudo -n /usr/local/sbin/evocrm-release-dispatch ;;
  *) printf '%s\n' 'Unsupported executor operation' >&2; exit 1 ;;
esac

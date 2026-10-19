#!/bin/sh
# Monta a configuração do Alertmanager a partir do modelo e sobe o processo.
set -eu
cp /etc/alertmanager/alertmanager.yml.modelo /tmp/alertmanager.yml
url="${ALERTA_WEBHOOK_URL:-}"
if [ -n "$url" ]; then
  case "$url" in
    https://*) ;;
    *) echo "ALERTA_WEBHOOK_URL precisa começar com https://" >&2; exit 1 ;;
  esac
  case "$url" in
    *"'"*|*'"'*|*' '*) echo "ALERTA_WEBHOOK_URL não pode ter aspas nem espaços" >&2; exit 1 ;;
  esac
  printf "    webhook_configs:\n      - url: '%s'\n        send_resolved: true\n" "$url" >> /tmp/alertmanager.yml
fi
exec /bin/alertmanager --config.file=/tmp/alertmanager.yml --storage.path=/alertmanager --web.listen-address=:9093

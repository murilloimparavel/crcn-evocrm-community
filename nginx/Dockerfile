FROM nginx:alpine

# Default upstream targets. Override any of these at deploy time when the
# backend service names in your stack differ from the defaults below.
ENV AUTH_UPSTREAM=evo_auth:3001 \
    CRM_UPSTREAM=evo_crm:3000 \
    CORE_UPSTREAM=evo_core:5555 \
    PROCESSOR_UPSTREAM=evo_processor:8000 \
    BOT_RUNTIME_UPSTREAM=evo_bot_runtime:8080

# Limit envsubst to the upstream vars so nginx's own $variables (e.g. $host,
# $request_uri) are not touched at render time.
ENV NGINX_ENVSUBST_FILTER="^(AUTH|CRM|CORE|PROCESSOR|BOT_RUNTIME)_UPSTREAM$"

COPY default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 3030

FROM nginx:1.31.8-alpine3.24@sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11

# The v3.24 package index publishes the patched libxslt version that fixes the
# HIGH findings from the previous floating nginx:alpine base.
RUN apk add --no-cache --upgrade 'libxslt=1.1.43-r4'

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

# syntax=docker/dockerfile:1
# =============================================================================
# Frontend image — Vite build served by nginx, which also reverse-proxies /api.
#
# Node 22 rather than 20: Vite 8 requires Node >= 20.19 or >= 22.12, and 22 is
# the branch that satisfies it without depending on which 20.x patch the tag
# happens to point at.
#
# The runtime stage is nginx:alpine with the compiled static bundle — no Node in
# the final image, which keeps it around 50 MB and removes the entire npm
# dependency tree from the runtime attack surface.
# =============================================================================

FROM node:22-alpine AS builder

WORKDIR /app

# Dependencies first so a source-only change reuses the cached install layer.
COPY frontend/package.json frontend/package-lock.json ./
# `npm ci` for a lockfile-exact install. --no-audit/--no-fund keep build logs
# readable; vulnerabilities are checked in CI instead, where it can fail a build.
RUN npm ci --no-audit --no-fund

COPY frontend/ ./

# tsc -b runs first inside the build script, so a type error fails the image
# build rather than shipping broken code.
RUN npm run build

FROM nginx:alpine AS runtime

LABEL org.opencontainers.image.title="Compliance Intelligence Copilot — UI" \
      org.opencontainers.image.description="React SPA for grounded AML/KYC compliance answers" \
      org.opencontainers.image.licenses="MIT"

RUN rm -rf /usr/share/nginx/html/*
COPY --from=builder /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]

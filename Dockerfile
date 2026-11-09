# Образ службы amem (спецификация подпроекта 4, разд. 7). Цели:
#   service — amem serve (по умолчанию);
#   web     — то же плюс статика веб-интерфейса (amem[web]: пакет amem-web из web/python), служба отдаёт её по /ui.
# Сборка: docker build -t amem .   или   docker build --target web -t amem-web .
# Внутри — клиент PostgreSQL 18 (pg_dump, pg_restore) для amem backup; семантическая модель — по
# --build-arg AMEM_EXTRAS=embed (fastembed, образ заметно больше).

FROM node:24-bookworm-slim AS ui
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
COPY docs/api /src/docs/api
RUN npm run build


FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# клиент PostgreSQL 18 из репозитория PGDG: в Debian — старее, а pg_dump не снимает базу новее себя
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-18 \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
ENV AMEM_PG_BIN=/usr/lib/postgresql/18/bin

ARG AMEM_EXTRAS=""
COPY pyproject.toml README.md LICENSE.txt /src/amem/
COPY amem /src/amem/amem
RUN if [ -n "$AMEM_EXTRAS" ]; then pip install "/src/amem[$AMEM_EXTRAS]"; else pip install /src/amem; fi \
 && rm -rf /src/amem

# данные, состояние и бэкапы — тома (docker-compose.yml); служба не от root
RUN useradd --system --uid 10001 --user-group --home-dir /var/lib/amem amem \
 && install -d -o amem -g amem /var/lib/amem /var/lib/amem/objects /var/lib/amem/state /var/lib/amem/backups \
      /var/lib/amem/docs
ENV HOME=/var/lib/amem \
    AMEM_DATA=/var/lib/amem/objects \
    AMEM_STATE=/var/lib/amem/state \
    AMEM_BACKUPS=/var/lib/amem/backups \
    AMEM_HOST=0.0.0.0 \
    AMEM_PORT=8767
WORKDIR /var/lib/amem
EXPOSE 8767
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8767/health', timeout=4).read() == b'ok' else 1)"
USER amem
# amem init — миграции и корень хранилища (повтор безопасен); без AMEM_TOKENS — --no-auth: порт наружу только
# 127.0.0.1 (compose), с AMEM_TOKENS — вход по токенам
CMD ["sh", "-c", "amem init && if [ -n \"$AMEM_TOKENS\" ]; then exec amem serve; else exec amem serve --no-auth; fi"]


FROM base AS web
USER root
COPY web/python /src/amem-web
COPY --from=ui /src/web/python/amem_web/dist /src/amem-web/amem_web/dist
RUN pip install /src/amem-web && rm -rf /src/amem-web
USER amem


FROM base AS service

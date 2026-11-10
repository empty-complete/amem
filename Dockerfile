# Образ службы amemo (спецификация подпроекта 4, разд. 7). Цели:
#   service — amemo serve (по умолчанию);
#   web     — то же плюс статика веб-интерфейса (amemo[web]: пакет amemo-web из web/python), служба отдаёт её по /ui.
# Сборка: docker build -t amemo .   или   docker build --target web -t amemo-web .
# Внутри — клиент PostgreSQL 18 (pg_dump, pg_restore) для amemo backup; смысловой поиск — по
# --build-arg AMEMO_EXTRAS=embed (fastembed, образ заметно больше), а включает его в запущенной службе
# amemo embed enable --yes: модель (~250 МБ) ложится в AMEMO_MODELS на томе состояния. Распознавание сканов PDF — по
# --build-arg OCR_LANGS="rus eng" (языки tesseract, amemo ocr install при сборке; пусто — без OCR).

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
RUN printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-18 \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
ENV AMEMO_PG_BIN=/usr/lib/postgresql/18/bin

ARG AMEMO_EXTRAS=""
COPY pyproject.toml README.md LICENSE.txt /src/amemo/
COPY amemo /src/amemo/amemo
RUN if [ -n "$AMEMO_EXTRAS" ]; then pip install "/src/amemo[$AMEMO_EXTRAS]"; else pip install /src/amemo; fi \
 && rm -rf /src/amemo

# языковые данные OCR — в образе, не в томе: их задаёт сборка; amemo.toml не правится — настройки в окружении
ARG OCR_LANGS=""
ARG OCR_QUALITY=fast
ENV AMEMO_OCR_DATA=/usr/share/amemo/tessdata \
    AMEMO_OCR_LANGUAGES="${OCR_LANGS}"
RUN install -d /usr/share/amemo/tessdata \
 && if [ -n "$OCR_LANGS" ]; then amemo ocr install --no-config --quality "$OCR_QUALITY" $OCR_LANGS; fi

# данные, состояние и бэкапы — тома (docker-compose.yml); служба не от root
RUN useradd --system --uid 10001 --user-group --home-dir /var/lib/amemo amemo \
 && install -d -o amemo -g amemo /var/lib/amemo /var/lib/amemo/objects /var/lib/amemo/state /var/lib/amemo/backups \
      /var/lib/amemo/docs
# AMEMO_IN_CONTAINER: служба в образе не обновляет себя сама (amemo/updates.py), только сообщает о новой версии
ENV HOME=/var/lib/amemo \
    AMEMO_IN_CONTAINER=1 \
    AMEMO_DATA=/var/lib/amemo/objects \
    AMEMO_STATE=/var/lib/amemo/state \
    AMEMO_BACKUPS=/var/lib/amemo/backups \
    AMEMO_MODELS=/var/lib/amemo/state/models \
    AMEMO_HOST=0.0.0.0 \
    AMEMO_PORT=8767
WORKDIR /var/lib/amemo
EXPOSE 8767
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8767/health', timeout=4).read() == b'ok' else 1)"
USER amemo
# amemo init — миграции и корень хранилища (повтор безопасен); без AMEMO_TOKENS — --no-auth: порт наружу только
# 127.0.0.1 (compose), с AMEMO_TOKENS — вход по токенам
CMD ["sh", "-c", "amemo init && if [ -n \"$AMEMO_TOKENS\" ]; then exec amemo serve; else exec amemo serve --no-auth; fi"]


FROM base AS web
USER root
COPY web/python /src/amemo-web
COPY --from=ui /src/web/python/amemo_web/dist /src/amemo-web/amemo_web/dist
RUN pip install /src/amemo-web && rm -rf /src/amemo-web
USER amemo


FROM base AS service

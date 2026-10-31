FROM python:3.12.11-slim-bookworm

ARG BUILD_VERSION=0.8.6
ARG APP_SOURCE_REF=v0.8.6
ARG INCLUDE_AI_SDK=false
ARG AI_SDK_WHEEL_SHA256=""
# Optional local release rehearsal: immutable git archive, never household data.
ARG APP_SOURCE_ARCHIVE_SHA256=""

LABEL io.hass.name="Home Energy Optimiser" \
      io.hass.description="Read-only Home Assistant energy dashboard and collector" \
      io.hass.type="app" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="amd64" \
      org.opencontainers.image.revision="${APP_SOURCE_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/home-energy-optimiser
RUN --mount=type=secret,id=local_source_archive \
    --mount=type=secret,id=panel_sdk_wheel,target=/tmp/ai_control_panel_client-1.0.4-py3-none-any.whl \
    if [ -s /run/secrets/local_source_archive ]; then \
      test -n "$APP_SOURCE_ARCHIVE_SHA256" \
      && printf '%s  %s\n' "$APP_SOURCE_ARCHIVE_SHA256" /run/secrets/local_source_archive | sha256sum --check - \
      && tar --extract --gzip --strip-components=1 --file /run/secrets/local_source_archive; \
    else \
      curl --fail --location --silent --show-error \
        "https://github.com/meust3/home-energy-optimiser/archive/${APP_SOURCE_REF}.tar.gz" \
        | tar --extract --gzip --strip-components=1; \
    fi \
    && python -m pip install --constraint requirements-runtime.txt . \
    && case "${INCLUDE_AI_SDK}" in \
      true) test -n "$AI_SDK_WHEEL_SHA256" \
        && printf '%s  %s\n' "$AI_SDK_WHEEL_SHA256" /tmp/ai_control_panel_client-1.0.4-py3-none-any.whl | sha256sum --check --status \
        && python -m pip install --constraint requirements-runtime.txt /tmp/ai_control_panel_client-1.0.4-py3-none-any.whl ;; \
      false) true ;; \
      *) exit 1 ;; \
    esac \
    && chmod 0755 home_energy_optimiser/run.sh \
    && rm -rf .git .env .venv data logs captures exports secrets credentials \
      tests docs .pytest_cache .ruff_cache .mypy_cache htmlcov \
    && find . -type f \( -name '*.db' -o -name '*.sqlite*' -o -name '*.dump' \
      -o -name '*.backup' -o -name '*.bak' -o -name '*.sql' -o -name '*.jsonl' \
      -o -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' \) \
      -delete \
    && apt-get purge --auto-remove --yes curl \
    && rm -rf /root/.cache

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home \
      --shell /usr/sbin/nologin app

EXPOSE 8099
# Supervisor mounts /data/options.json as root:root 0600. The entrypoint performs
# one narrowly scoped root bootstrap, then execs the application through gosu.
USER 0:0
ENTRYPOINT ["/opt/home-energy-optimiser/home_energy_optimiser/run.sh"]

# syntax=docker/dockerfile:1.7
FROM python:3.12.11-slim-bookworm

ARG BUILD_VERSION=0.6.4
ARG APP_SOURCE_REF=8e2c165976130a0f99b441bf242c5c7ce10f163e
ARG INCLUDE_AI_SDK=false

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
RUN --mount=type=secret,id=panel_sdk_wheel,target=/tmp/ai_control_panel_client-1.0.1-py3-none-any.whl \
    curl --fail --location --silent --show-error \
      "https://github.com/meust3/home-energy-optimiser/archive/${APP_SOURCE_REF}.tar.gz" \
      | tar --extract --gzip --strip-components=1 \
    && python -m pip install . \
    && case "${INCLUDE_AI_SDK}" in \
      true) echo 'a10d6a3170bb0c564e478d338bcac293dbdb0adc1748acc838d1cfabb8db65bb  /tmp/ai_control_panel_client-1.0.1-py3-none-any.whl' | sha256sum --check --status \
        && python -m pip install /tmp/ai_control_panel_client-1.0.1-py3-none-any.whl ;; \
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

FROM python:3.12.11-slim-bookworm

ARG BUILD_VERSION=0.4.0
ARG APP_SOURCE_REF=v0.4.0

LABEL io.hass.name="Home Energy Optimiser" \
      io.hass.description="Read-only Home Assistant energy dashboard and collector" \
      io.hass.type="app" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="amd64"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/home-energy-optimiser
RUN curl --fail --location --silent --show-error \
      "https://github.com/meust3/home-energy-optimiser/archive/${APP_SOURCE_REF}.tar.gz" \
      | tar --extract --gzip --strip-components=1 \
    && python -m pip install . \
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

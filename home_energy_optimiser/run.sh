#!/usr/bin/env bash
set -euo pipefail

readonly source_options="/data/options.json"
readonly runtime_dir="/run/home-energy-optimiser"
readonly runtime_options="${runtime_dir}/options.json"

if [[ "$(id -u)" != "0" ]]; then
  echo "Home Assistant App bootstrap must start as root" >&2
  exit 1
fi

umask 077
install -d -o app -g app -m 0700 "${runtime_dir}"
rm -f -- "${runtime_options}"

if [[ ! -e "${source_options}" ]]; then
  echo "Unable to read Home Assistant App options file: file not found" >&2
  exit 1
fi

if ! install -o app -g app -m 0600 "${source_options}" "${runtime_options}" \
  2>/dev/null; then
  echo "Unable to read Home Assistant App options file: permission denied or unreadable" >&2
  exit 1
fi

export HOME_ENERGY_APP_OPTIONS_PATH="${runtime_options}"
cd /opt/home-energy-optimiser

if (( $# > 0 )); then
  exec gosu app:app "$@"
fi
exec gosu app:app python tools/run_home_assistant_app.py

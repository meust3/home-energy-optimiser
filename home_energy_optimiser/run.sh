#!/usr/bin/env bash
set -euo pipefail

cd /opt/home-energy-optimiser
exec python tools/run_home_assistant_app.py

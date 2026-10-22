#!/usr/bin/env bash
set -euo pipefail

python -m pip install -r backend/requirements.txt
python backend/manage.py collectstatic --noinput

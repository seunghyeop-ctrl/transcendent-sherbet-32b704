#!/usr/bin/env sh
set -eu
exec python3 app.py --host "${PROMPT_EXTRACTOR_HOST:-0.0.0.0}" --port "${PORT:-5001}"

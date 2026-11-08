#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x ".venv/bin/python" ]; then
  echo "Create .venv and install requirements-all.txt first. See README_FIRST.md."
  exit 1
fi
exec ./.venv/bin/python radio-map/serve.py "$@"

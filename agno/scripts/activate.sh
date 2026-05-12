#!/usr/bin/env bash
# Source questo script (non eseguirlo): source scripts/activate.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/../.venv"

if [[ ! -d "$VENV" ]]; then
    echo "Virtualenv non trovato in $VENV. Esegui prima: python -m venv .venv && pip install -r requirements.txt"
    return 1
fi

source "$VENV/bin/activate"
echo "Ambiente attivo: $(python --version) — $(which python)"

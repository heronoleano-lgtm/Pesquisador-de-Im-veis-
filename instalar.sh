#!/usr/bin/env sh
# Instala o Buscador de imóveis (macOS, Linux e Termux no Android).
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python || true)
[ -z "$PY" ] && { echo "Python não encontrado. Instale o Python 3.10+ (python.org, ou: pkg install python no Termux)."; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3,10))' || { echo "Precisa do Python 3.10 ou mais novo."; exit 1; }
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[rapido]" || .venv/bin/python -m pip install -e .
echo; echo "Pronto! Para usar: ./iniciar.sh"

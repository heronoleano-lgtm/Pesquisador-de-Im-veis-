#!/usr/bin/env sh
cd "$(dirname "$0")"
[ -x .venv/bin/buscaimoveis ] || { echo "Rode ./instalar.sh primeiro."; exit 1; }
exec .venv/bin/buscaimoveis servir --celular

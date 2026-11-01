#!/data/data/com.termux/files/usr/bin/sh
# Instala o Buscador de imóveis dentro do Termux (Android). Rode, na pasta do pacote:
#     sh termux/instalar-termux.sh
set -e
cd "$(dirname "$0")/.."

if [ -z "$PREFIX" ] || [ ! -d "$PREFIX/bin" ]; then
  echo "Este script é para o app Termux (instale pelo F-Droid ou pelo GitHub do Termux)."
  exit 1
fi

echo "=== 1/4 Pacotes do sistema ==="
pkg update -y
pkg install -y python python-pip tur-repo
pkg update -y                      # carrega a lista de pacotes do repositório TUR
pkg install -y python-numpy python-pandas   # prontos, sem compilar
pkg install -y termux-api || true           # notificações do Android (precisa também do app Termux:API)

echo "=== 2/4 Bibliotecas Python ==="
# O Termux usa um pip próprio: não rode "pip install --upgrade pip".
instalar() { pip install "$@" || pip install --break-system-packages "$@"; }
LIBS="flask httpx beautifulsoup4 pyyaml waitress"
if ! instalar $LIBS; then
  echo "Falhou. Tentando de novo com o compilador instalado..."
  pkg install -y clang make
  instalar $LIBS
fi

echo "=== 3/4 O buscador ==="
pip install --no-deps . || pip install --no-deps --break-system-packages .

echo "=== 4/4 Conferindo ==="
python -c "import pandas, numpy, flask, httpx, bs4, yaml, buscaimoveis; print('pandas', pandas.__version__, '| buscador', buscaimoveis.__version__)"
echo
echo "Pronto! Para usar:  sh termux/iniciar-termux.sh"

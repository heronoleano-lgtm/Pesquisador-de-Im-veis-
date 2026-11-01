#!/data/data/com.termux/files/usr/bin/sh
# Inicia o buscador no Termux e abre o navegador do celular.  Uso:  sh termux/iniciar-termux.sh
if ! command -v buscaimoveis >/dev/null 2>&1; then
  echo "Rode primeiro:  sh termux/instalar-termux.sh"
  exit 1
fi
termux-wake-lock 2>/dev/null   # impede o Android de pausar o Termux com a tela apagada
echo "As buscas salvas rodam sozinhas enquanto isto estiver aberto. Para parar: Ctrl+C aqui no Termux."
exec buscaimoveis servir --abrir

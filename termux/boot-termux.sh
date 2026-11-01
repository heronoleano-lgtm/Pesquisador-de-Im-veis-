#!/data/data/com.termux/files/usr/bin/sh
# Faz o servidor subir sozinho quando o celular liga. Precisa do app Termux:Boot (abra-o uma vez).
# Instalação:
#     mkdir -p ~/.termux/boot && cp termux/boot-termux.sh ~/.termux/boot/buscaimoveis && chmod +x ~/.termux/boot/buscaimoveis
termux-wake-lock
exec buscaimoveis servir >> "$HOME/buscaimoveis.log" 2>&1

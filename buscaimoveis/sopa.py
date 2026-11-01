"""Leitura de HTML. Usa o lxml quando instalado (mais tolerante com HTML quebrado); sem ele, usa o analisador
que já vem com o Python, o que permite instalar no celular (Termux) sem compilar nada."""
import os

from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401
    _PADRAO = "lxml"
except ImportError:
    _PADRAO = "html.parser"

PARSER = os.environ.get("BUSCAIMOVEIS_PARSER") or _PADRAO


def sopa(html):
    return BeautifulSoup(html, PARSER)

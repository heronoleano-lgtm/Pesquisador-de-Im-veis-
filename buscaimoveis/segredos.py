"""Chaves de API e senhas de serviços: lidas de variáveis de ambiente ou de ~/.buscaimoveis/chaves.json
(arquivo legível só pelo dono). Nos arquivos de configuração, escreva ${NOME} no lugar da chave."""
import json
import os
import re

from .banco import casa

_PADRAO = re.compile(r"\$\{([A-Za-z0-9_]+)\}")
_NOME = re.compile(r"[A-Z][A-Z0-9_]{1,63}")


def _arquivo():
    return casa() / "chaves.json"


def _lidas():
    try:
        d = json.loads(_arquivo().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def valor(nome):
    return os.environ.get(nome) or _lidas().get(nome) or ""


def guardar(nome, v):
    if not _NOME.fullmatch(nome or ""):
        raise ValueError("use um nome em MAIÚSCULAS, números e _, por exemplo GECKOAPI_CHAVE")
    d = _lidas()
    d[nome] = v
    _arquivo().write_text(json.dumps(d), encoding="utf-8")
    try:
        os.chmod(_arquivo(), 0o600)
    except OSError:
        pass  # Windows não usa essas permissões


def nomes():
    return sorted(_lidas())


def expandir(o):
    """Troca ${NOME} pela chave, em textos, listas e dicionários."""
    if isinstance(o, str):
        return _PADRAO.sub(lambda m: valor(m.group(1)), o)
    if isinstance(o, list):
        return [expandir(x) for x in o]
    if isinstance(o, dict):
        return {k: expandir(v) for k, v in o.items()}
    return o


def faltando(o):
    """Nomes de chaves citadas como ${NOME} que não estão guardadas nem no ambiente."""
    achados = set()

    def varre(x):
        if isinstance(x, str):
            achados.update(m for m in _PADRAO.findall(x) if not valor(m))
        elif isinstance(x, list):
            for i in x:
                varre(i)
        elif isinstance(x, dict):
            for i in x.values():
                varre(i)
    varre(o)
    return sorted(achados)

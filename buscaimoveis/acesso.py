"""Senha de acesso: protege a interface quando ela é aberta para outros aparelhos (celular, nuvem)."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from .banco import casa

ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sem I, L, O, 0 e 1, que se confundem na tela do celular
MAX_FALHAS, JANELA, BLOQUEIO = 5, 600, 300


def _arquivo():
    return casa() / "acesso.json"


def _hash(senha, sal):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, 200_000).hex()


def _so_dono(caminho):
    try:
        os.chmod(caminho, 0o600)
    except OSError:
        pass  # Windows não usa essas permissões


def definir_senha(senha):
    sal = secrets.token_bytes(16)
    _arquivo().write_text(json.dumps({"sal": sal.hex(), "hash": _hash(senha, sal)}), encoding="utf-8")
    _so_dono(_arquivo())


def gerar_codigo():
    """Código aleatório de 8 caracteres, mostrado como XXXX-XXXX. Devolve (como_mostrar, como_guardar)."""
    c = "".join(secrets.choice(ALFABETO) for _ in range(8))
    return f"{c[:4]}-{c[4:]}", c


def senha_configurada():
    return bool(os.environ.get("BUSCAIMOVEIS_SENHA")) or _arquivo().exists()


def conferir(senha):
    senha = senha or ""
    env = os.environ.get("BUSCAIMOVEIS_SENHA")
    if env:
        return hmac.compare_digest(env.encode("utf-8"), senha.encode("utf-8"))
    try:
        d = json.loads(_arquivo().read_text(encoding="utf-8"))
        sal = bytes.fromhex(d["sal"])
    except (OSError, ValueError, KeyError):
        return False
    # Os códigos gerados são aceitos sem hífen e em minúsculas; senhas escolhidas por você valem só como digitadas.
    tentativas = {senha, senha.replace("-", "").replace(" ", "").upper()}
    return any(hmac.compare_digest(_hash(t, sal), d["hash"]) for t in tentativas)


def segredo_da_sessao():
    p = casa() / "segredo"
    if not p.exists():
        p.write_text(secrets.token_hex(32), encoding="utf-8")
        _so_dono(p)
    return p.read_text(encoding="utf-8").strip()


class Limitador:
    """Depois de 5 senhas erradas em 10 minutos, bloqueia o endereço por 5 minutos."""

    def __init__(self):
        self._f, self._b, self._l = {}, {}, threading.Lock()

    def segundos_bloqueado(self, quem):
        with self._l:
            return max(0, int(self._b.get(quem, 0) - time.time()))

    def falhou(self, quem):
        agora = time.time()
        with self._l:
            l = [t for t in self._f.get(quem, []) if agora - t < JANELA] + [agora]
            self._f[quem] = l
            if len(l) >= MAX_FALHAS:
                self._b[quem], self._f[quem] = agora + BLOQUEIO, []

    def acertou(self, quem):
        with self._l:
            self._f.pop(quem, None)

"""Envio de notificações: Termux (notificação do Android), ntfy e Telegram. As mensagens de erro nunca
incluem endereços completos nem chaves."""
import secrets
import shlex
import shutil
import subprocess

from . import segredos

CANAIS = ("termux", "ntfy", "telegram")


def configurados(cfg):
    """Canais pedidos em `alertas.notificar` que o programa conhece."""
    pedidos = cfg.get("notificar") or []
    pedidos = [pedidos] if isinstance(pedidos, str) else pedidos
    return [c for c in pedidos if c in CANAIS]


def novo_topico():
    return "buscaimoveis-" + secrets.token_urlsafe(12).replace("_", "x").replace("-", "y").lower()


def _termux(titulo, corpo, link, ident):
    exe = shutil.which("termux-notification")
    if not exe:
        raise RuntimeError("termux-notification não encontrado: rode  pkg install termux-api  e instale o app Termux:API")
    cmd = [exe, "--title", titulo, "--content", corpo, "--id", str(ident), "--group", "imoveis", "--priority", "high"]
    if link:
        cmd += ["--action", f"termux-open-url {shlex.quote(link)}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        raise RuntimeError("o Termux:API não respondeu (o app Termux:API está instalado e com permissão?)")
    if r.returncode:
        raise RuntimeError(f"termux-notification falhou (código {r.returncode})")


def _ntfy(cli, cfg, titulo, corpo, link):
    n = segredos.expandir(cfg.get("ntfy") or {})
    topico = (n.get("topico") or "").strip()
    if not topico:
        raise RuntimeError("falta `ntfy.topico` em alertas (gere um com: buscaimoveis topico)")
    servidor = (n.get("servidor") or "https://ntfy.sh").rstrip("/")
    msg = {"topic": topico, "title": titulo, "message": corpo, "tags": ["house"], "priority": 3}
    if link:
        msg["click"] = link
    cab = {"Authorization": "Bearer " + n["token"]} if n.get("token") else {}
    try:
        r = cli.post(servidor + "/", json=msg, headers=cab, timeout=20)
    except Exception as e:
        raise RuntimeError(f"ntfy indisponível ({type(e).__name__})")
    if r.status_code >= 400:
        raise RuntimeError(f"o ntfy recusou a mensagem (código {r.status_code})")


def _telegram(cli, cfg, titulo, corpo, link):
    t = segredos.expandir(cfg.get("telegram") or {})
    token, chat = (t.get("token") or "").strip(), str(t.get("chat_id") or "").strip()
    if not token or not chat:
        raise RuntimeError("faltam `telegram.token` e `telegram.chat_id` em alertas")
    texto = f"{titulo}\n{corpo}" + (f"\n{link}" if link else "")
    try:
        r = cli.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": texto}, timeout=20)
    except Exception as e:
        raise RuntimeError(f"Telegram indisponível ({type(e).__name__})")
    if r.status_code >= 400:
        raise RuntimeError(f"o Telegram recusou a mensagem (código {r.status_code}); confira o token e o chat_id")


def enviar(cfg, titulo, corpo, link="", ident=1, cliente=None):
    """Manda a mensagem por todos os canais configurados. Devolve {canal: (ok, mensagem_de_erro)}."""
    canais = configurados(cfg)
    resultado = {}
    if any(c != "termux" for c in canais) and cliente is None:
        import httpx
        cliente = httpx.Client(timeout=20)
    for c in canais:
        try:
            if c == "termux":
                _termux(titulo, corpo, link, ident)
            elif c == "ntfy":
                _ntfy(cliente, cfg, titulo, corpo, link)
            else:
                _telegram(cliente, cfg, titulo, corpo, link)
            resultado[c] = (True, "")
        except Exception as e:
            resultado[c] = (False, str(e)[:200])
    return resultado

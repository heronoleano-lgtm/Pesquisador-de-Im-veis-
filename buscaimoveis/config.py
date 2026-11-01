"""Leitura do arquivo sites.yaml (guardado na pasta do usuário)."""
import shutil
from pathlib import Path

import yaml

from .banco import casa

PADRAO = {"coleta": {"atraso": 3.0, "respeitar_robots": True}, "sites": {}, "apis": {},
          "alertas": {"intervalo_min": 120, "queda_minima_pct": 3, "silencio": "", "notificar": [], "link": ""}}


def caminho():
    dest = casa() / "sites.yaml"
    if not dest.exists():
        shutil.copy(Path(__file__).parent / "sites_exemplo.yaml", dest)
    return dest


def carregar_config():
    with open(caminho(), encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["coleta"] = {**PADRAO["coleta"], **(cfg.get("coleta") or {})}
    cfg["sites"] = cfg.get("sites") or {}
    cfg["apis"] = cfg.get("apis") or {}
    cfg["alertas"] = {**PADRAO["alertas"], **(cfg.get("alertas") or {})}
    return cfg


def novo_coletor(bloquear_internos=False):
    from .coleta import Coletor
    c = carregar_config()["coleta"]
    return Coletor(bloquear_internos=bloquear_internos,
                   **{k: v for k, v in c.items() if k in ("atraso", "respeitar_robots", "user_agent")})

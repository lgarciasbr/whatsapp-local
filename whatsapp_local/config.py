# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Configuração: contas de WhatsApp, pasta dos dados e segredos.

Arquivo: ~/.config/whatsapp-local/config.json (ou WA_CONFIG). Exemplo:

    {
      "dados": "~/.local/share/whatsapp-local",
      "conta_padrao": "trabalho",
      "contas": {
        "trabalho": {"fonte": "waha", "url": "https://waha.exemplo.com", "sessao": "default"},
        "mac": {"fonte": "desktop", "dados": "~/.local/share/whatsapp-local/trabalho"},
        "pessoal": {"fonte": "wacli", "conta_wacli": "pessoal"}
      },
      "whisper": {"idioma": "pt"},
      "sync": {...}
    }

A API key do WAHA nunca fica no config.json: vem da variável WAHA_API_KEY_<CONTA>
(ex.: WAHA_API_KEY_TRABALHO) ou do arquivo segredos.env na mesma pasta do config.
"""
import json
import os
import re
import sys

from .modelo import ErroFonte


def _pasta(var_xdg, padrao, var_windows):
    if sys.platform == "win32" and os.environ.get(var_windows):
        return os.path.join(os.environ[var_windows], "whatsapp-local")
    return os.path.join(os.environ.get(var_xdg) or os.path.expanduser(padrao), "whatsapp-local")


PASTA_CONFIG = os.environ.get("WA_CONFIG_DIR") or _pasta("XDG_CONFIG_HOME", "~/.config", "APPDATA")
DADOS_PADRAO = _pasta("XDG_DATA_HOME", "~/.local/share", "LOCALAPPDATA")


def expandir(caminho):
    return os.path.abspath(os.path.expanduser(os.path.expandvars(caminho)))


def nome_variavel(conta):
    return "WAHA_API_KEY_" + re.sub(r"[^A-Z0-9]", "_", conta.upper())


class Config:
    def __init__(self, caminho=None):
        self.caminho = expandir(caminho or os.environ.get("WA_CONFIG") or os.path.join(PASTA_CONFIG, "config.json"))
        self.existe = os.path.exists(self.caminho)
        if self.existe:
            with open(self.caminho, encoding="utf-8") as f:
                try:
                    self.dados = json.load(f)
                except ValueError as e:
                    raise ErroFonte(f"{self.caminho} não é um JSON válido: {e}")
        else:
            self.dados = {}
        self.pasta_dados = expandir(self.dados.get("dados") or DADOS_PADRAO)
        self.contas = self.dados.get("contas") or {}
        if not self.contas and sys.platform == "darwin":
            self.contas = {"mac": {"fonte": "desktop"}}  # sem config: o app do Mac, se houver
        self.conta_padrao = self.dados.get("conta_padrao") or next(iter(self.contas), None)
        self.whisper = self.dados.get("whisper") or {}
        self.sync = self.dados.get("sync") or {}

    def conta(self, nome=None):
        nome = nome or self.conta_padrao
        if not nome:
            raise ErroFonte(f"Nenhuma conta configurada. Rode o instalador ou crie {self.caminho}.")
        if nome not in self.contas:
            raise ErroFonte(f"Conta '{nome}' não existe em {self.caminho}. Contas: {', '.join(self.contas) or 'nenhuma'}.")
        conta = dict(self.contas[nome])
        conta["nome"] = nome
        if conta.get("fonte") not in ("desktop", "waha", "wacli"):
            raise ErroFonte(f"Conta '{nome}': \"fonte\" deve ser \"desktop\", \"waha\" ou \"wacli\".")
        return conta

    def pasta_conta(self, nome):
        """Cache de mídia e transcrições da conta. Duas contas do mesmo número (app do Mac e
        WAHA) podem apontar para a mesma pasta: o id das mensagens é o mesmo."""
        return expandir(self.contas.get(nome, {}).get("dados") or os.path.join(self.pasta_dados, nome))

    def segredo(self, chave):
        if os.environ.get(chave):
            return os.environ[chave]
        arquivo = os.path.join(os.path.dirname(self.caminho), "segredos.env")
        if os.path.exists(arquivo):
            with open(arquivo, encoding="utf-8") as f:
                for linha in f:
                    if "=" in linha and not linha.lstrip().startswith("#"):
                        k, v = linha.strip().split("=", 1)
                        if k.strip() == chave:
                            return v.strip().strip("'\"")
        return None


def abrir_fonte(cfg, nome_conta=None):
    from .cache import Cache
    conta = cfg.conta(nome_conta)
    cache = Cache(cfg.pasta_conta(conta["nome"]))
    if conta["fonte"] == "waha":
        from .waha import FonteWaha
        chave = cfg.segredo(conta.get("api_key_env") or nome_variavel(conta["nome"]))
        return FonteWaha(conta, cache, chave)
    if conta["fonte"] == "wacli":
        from .wacli import FonteWacli
        return FonteWacli(conta, cache)
    from .desktop import FonteDesktop
    return FonteDesktop(conta, cache)

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Configurador opcional da integração com https://github.com/lgarciasbr/obsidian-crm.

Execute depois de instalar o whatsapp-local. Não instala nem altera o plugin, as
notas ou o AGENTS.md do CRM. Só configura `sync.obsidian_crm` no whatsapp-local.
"""
import argparse
import copy
import json
import os
import shutil
import tempfile
from datetime import datetime

from whatsapp_local.config import Config, expandir
from whatsapp_local.modelo import ErroFonte
from whatsapp_local.obsidian_crm import PLUGIN, pasta_crm


def preparar(cfg, vault, contas):
    """Valida sem gravar nem acessar WhatsApp. Preserva todas as opções existentes."""
    if not cfg.existe or not cfg.dados.get("contas"):
        raise ErroFonte("Instale e configure o whatsapp-local primeiro: python3 instalar.py")
    if not contas:
        raise ErroFonte("Selecione pelo menos uma conta.")
    for conta in contas:
        cfg.conta(conta)
    dados = copy.deepcopy(cfg.dados)
    sync = dados.setdefault("sync", {})
    integracao = sync.setdefault("obsidian_crm", {})
    anterior = integracao.get("vault")
    if anterior and expandir(anterior) != expandir(vault):
        raise ErroFonte("Já existe integração com outro vault. Use outro arquivo de configuração "
                        "para não levar associações de pessoas para o vault errado.")
    integracao.update(vault=expandir(vault), contas=list(dict.fromkeys(contas)))
    integracao.pop("conta", None)
    raiz = pasta_crm(integracao)
    if not os.path.isdir(os.path.join(raiz, "People")):
        raise ErroFonte(f"People/ não encontrada em {raiz}. Configure o plugin primeiro: {PLUGIN}")
    return dados, raiz


def salvar(cfg, dados):
    if dados == cfg.dados:
        return None
    backup = cfg.caminho + "." + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".bak"
    shutil.copy2(cfg.caminho, backup)
    os.chmod(backup, 0o600)
    fd, temporario = tempfile.mkstemp(prefix=".config-", dir=os.path.dirname(cfg.caminho))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temporario, cfg.caminho)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="config.json do whatsapp-local")
    parser.add_argument("--vault", help="pasta do vault")
    parser.add_argument("--contas", nargs="+", help="contas onde procurar; primeira = principal")
    parser.add_argument("--confirmado", action="store_true", help="grava após validar, sem perguntar")
    args = parser.parse_args()
    try:
        cfg = Config(args.config)
        if not cfg.existe or not cfg.dados.get("contas"):
            raise ErroFonte("Instale e configure o whatsapp-local primeiro: python3 instalar.py")
        print(f"Integração opcional com o Obsidian CRM: {PLUGIN}")
        print("Mantém as conversas das pessoas do CRM no vault, com transcrição local.\n"
              "Não altera o plugin, as notas de pessoas nem o AGENTS.md.")
        atual = cfg.sync.get("obsidian_crm") or {}
        vault = args.vault or input(f"Vault [{atual.get('vault', '')}]: ").strip() or atual.get("vault")
        if not vault:
            raise ErroFonte("Informe o vault.")
        print("Contas disponíveis: " + ", ".join(cfg.contas))
        padrao = atual.get("contas") or [atual.get("conta") or cfg.conta_padrao]
        contas = args.contas
        if not contas:
            resposta = input(f"Contas, separadas por vírgula [{', '.join(padrao)}]: ").strip()
            contas = [c.strip() for c in resposta.split(",") if c.strip()] if resposta else padrao
        dados, raiz = preparar(cfg, vault, contas)
        print(f"Destino: {raiz}/WhatsApp/\nContas: {', '.join(contas)}\nConfig: {cfg.caminho}")
        if not args.confirmado and input("Salvar integração? [s/N]: ").strip().lower() not in ("s", "sim"):
            print("Nada alterado.")
            return 0
        backup = salvar(cfg, dados)
        print(f"Salvo. Backup: {backup}" if backup else "Já estava configurado assim; nada alterado.")
        print("Para sincronizar todas as pessoas encontradas pelo telefone: wa sync")
        return 0
    except (ErroFonte, ValueError, OSError) as e:
        print(f"Erro: {e}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nInterrompido; configuração não confirmada não é gravada.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
import copy
import json
import os
from unittest import mock

import instalar
import integrar_obsidian_crm as integrar
from tests.base import Caso
from tests.fakes import vault_crm
from whatsapp_local.modelo import ErroFonte


class ConfiguradorCRM(Caso):
    def preparar(self, existente=False):
        vault = os.path.join(self.tmp, "Vault")
        vault_crm(vault, "Relacionamentos", {"Fulana": "+5511900000000"})
        opcoes = {"dias": 14, "conversas": [{"conversa": "Grupo comum"}]}
        if existente:
            opcoes["obsidian_crm"] = {"vault": vault, "conta": "trabalho",
                                     "pessoas": {"Fulana": "123@lid"},
                                     "grupos": [{"conversa": "Equipe"}]}
        cfg = self.config(sync=opcoes)
        segredos = os.path.join(self.tmp, "segredos.env")
        with open(segredos, "w") as f:
            f.write("segredo-nao-alterar")
        return cfg, vault, segredos

    def test_integracao_nova_preserva_config_e_nao_altera_vault(self):
        cfg, vault, segredos = self.preparar()
        antes = copy.deepcopy(cfg.dados)
        dados, raiz = integrar.preparar(cfg, vault, ["trabalho"])
        self.assertEqual(cfg.dados, antes)  # preparação não modifica nem grava
        self.assertTrue(raiz.endswith("Relacionamentos"))
        backup = integrar.salvar(cfg, dados)
        with open(backup) as f:
            self.assertEqual(json.load(f), antes)
        with open(segredos) as f:
            self.assertEqual(f.read(), "segredo-nao-alterar")
        self.assertEqual(dados["contas"], antes["contas"])
        self.assertEqual(dados["sync"]["conversas"], antes["sync"]["conversas"])
        self.assertEqual(os.listdir(raiz), ["People"])
        self.assertEqual(os.stat(cfg.caminho).st_mode & 0o777, 0o600)

    def test_existente_preserva_associacoes_e_grupos(self):
        cfg, vault, _ = self.preparar(True)
        dados, _ = integrar.preparar(cfg, vault, ["trabalho"])
        integracao = dados["sync"]["obsidian_crm"]
        self.assertEqual(integracao["pessoas"], {"Fulana": "123@lid"})
        self.assertEqual(integracao["grupos"], [{"conversa": "Equipe"}])
        integrar.salvar(cfg, dados)
        cfg.dados = dados
        self.assertIsNone(integrar.salvar(cfg, dados))  # idempotente
        with self.assertRaises(ErroFonte):
            integrar.preparar(cfg, os.path.join(self.tmp, "Outro"), ["trabalho"])

    def test_conta_ou_vault_invalidos_nao_gravam(self):
        cfg, vault, _ = self.preparar()
        with open(cfg.caminho, "rb") as f:
            antes = f.read()
        for alvo, contas in [(vault, ["inexistente"]), (vault, []), (self.tmp, ["trabalho"])]:
            with self.assertRaises(ErroFonte):
                integrar.preparar(cfg, alvo, contas)
        with open(cfg.caminho, "rb") as f:
            self.assertEqual(f.read(), antes)

    def test_cancelar_configurador_nao_grava(self):
        cfg, vault, _ = self.preparar()
        with open(cfg.caminho, "rb") as f:
            antes = f.read()
        argv = ["integrar_obsidian_crm.py", "--config", cfg.caminho,
                "--vault", vault, "--contas", "trabalho"]
        with mock.patch("sys.argv", argv), mock.patch("builtins.input", return_value="n"):
            self.assertEqual(integrar.main(), 0)
        with open(cfg.caminho, "rb") as f:
            self.assertEqual(f.read(), antes)

    def test_registro_da_skill_no_pi(self):
        pasta = os.path.join(self.tmp, "pi", "skills")
        os.makedirs(os.path.dirname(pasta))
        with mock.patch.dict(instalar.AGENTES, {"Pi": pasta}, clear=True), mock.patch("builtins.input", return_value="s"):
            instalar.skill()
        destino = os.path.join(pasta, "whatsapp-local", "SKILL.md")
        self.assertEqual(os.path.realpath(destino), os.path.join(instalar.AQUI, "skill", "SKILL.md"))

# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Coleta independente: seleção, falhas e trava compartilhada, sem rede real."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from whatsapp_local import sync
from whatsapp_local.cli import main
from whatsapp_local.modelo import ErroFonte
from whatsapp_local.trava import Ocupado, trava


class Coletar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = SimpleNamespace(pasta_dados=self.tmp.name,
                                   contas={"a": {"fonte": "wacli"}, "b": {"fonte": "wacli"},
                                           "mac": {"fonte": "desktop"}, "servidor": {"fonte": "waha"}})
        self.cfg.conta = lambda nome: self.cfg.contas[nome]

    def test_todas_wacli_sem_sync_nem_crm(self):
        with patch.object(sync, "abrir_fonte") as abrir, patch.object(sync, "_executar") as exportar:
            resultados = sync.coletar(self.cfg, log=lambda *_: None)
            self.assertEqual([c.args[1] for c in abrir.call_args_list], ["a", "b"])
            self.assertEqual(abrir.return_value.atualizar.call_count, 2)
            exportar.assert_not_called()
            self.assertEqual([r[0] for r in resultados], ["ok", "ok"])

    def test_conta_especifica(self):
        with patch.object(sync, "abrir_fonte") as abrir:
            sync.coletar(self.cfg, "b", log=lambda *_: None)
            abrir.assert_called_once_with(self.cfg, "b")
        with self.assertRaises(ErroFonte):
            sync.coletar(self.cfg, "mac")

    def test_falha_de_uma_conta_nao_impede_a_outra(self):
        ruim, boa = Mock(), Mock()
        ruim.atualizar.side_effect = ErroFonte("sessão indisponível")
        with patch.object(sync, "abrir_fonte", side_effect=[ruim, boa]):
            resultados = sync.coletar(self.cfg, log=lambda *_: None)
        self.assertEqual([r[0] for r in resultados], ["erro", "ok"])
        boa.atualizar.assert_called_once()

    def test_nao_concorre_com_sync_nem_outra_coleta(self):
        with trava(os.path.join(self.tmp.name, "sync.lock")):
            with self.assertRaises(Ocupado), patch.object(sync, "abrir_fonte") as abrir:
                sync.coletar(self.cfg)
            abrir.assert_not_called()

    def test_sem_wacli_nao_finge_sucesso(self):
        self.cfg.contas = {"mac": {"fonte": "desktop"}}
        with self.assertRaises(ErroFonte):
            sync.coletar(self.cfg)

    def test_cli_falha_retorna_codigo_um(self):
        with patch("whatsapp_local.cli.Config", return_value=self.cfg), patch.object(
                sync, "coletar", return_value=[("erro", "a", "falhou")]) as coletar:
            with self.assertRaises(SystemExit) as erro:
                main(["--conta", "a", "coletar"])
            self.assertEqual(erro.exception.code, 1)
            coletar.assert_called_once_with(self.cfg, "a")

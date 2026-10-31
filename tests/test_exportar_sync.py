# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
import hashlib
import json
import os
import unittest

from tests.base import AGORA, DIA, Caso
from tests.fakes import vault_crm
from whatsapp_local import exportar, operacoes, sync
from whatsapp_local.config import abrir_fonte
from whatsapp_local.trava import Ocupado, trava

FULANA = "111111111111111@lid"
BELTRANO = "333333333333333@lid"
GRUPO = "120363000000000001@g.us"


def ler(caminho):
    with open(caminho, encoding="utf-8") as f:
        return f.read()


def hashes(pasta):
    out = {}
    for n in os.listdir(pasta):
        with open(os.path.join(pasta, n), "rb") as f:
            out[n] = hashlib.sha256(f.read()).hexdigest()
    return out


class Exportacao(Caso):
    def setUp(self):
        super().setUp()
        self.waha.chats = [{"id": FULANA, "name": "Fulana de Tal", "ts": AGORA - DIA}]
        self.waha.msg(FULANA, "3A01", AGORA - 40 * DIA, corpo="mensagem antiga")
        self.audio = self.waha.msg(FULANA, "3A02", AGORA - 2 * DIA, tipo="ptt", duration="5", mimetype="audio/ogg")
        self.waha.arquivos = {self.audio: b"OggS"}
        self.fonte = abrir_fonte(self.config())
        self.base = os.path.join(self.tmp, "Notas")

    def exportar(self, dias=None):
        conv = self.fonte.conversas()[0]
        msgs = self.fonte.mensagens(FULANA, AGORA - dias * DIA if dias else None)
        operacoes.transcrever(self.fonte, msgs, {}, log=lambda *_: None)
        regs = operacoes.registros(self.fonte, conv, msgs, {})
        return exportar.exportar(regs, FULANA, self.base, "Privado - Fulana de Tal", "Conversa privada com Fulana de Tal")

    def test_janela_curta_nao_apaga_historico(self):
        self.exportar()
        self.waha.mensagens[FULANA] = [m for m in self.waha.mensagens[FULANA] if "3A01" not in m["id"]]  # sumiu da fonte
        r = self.exportar(dias=30)
        md = ler(os.path.join(r["pasta"], "Transcript - Conversa privada com Fulana de Tal.md"))
        self.assertIn("mensagem antiga", md)
        self.assertIn("transcrição de 3A02.opus", md)
        self.assertEqual(sorted(os.listdir(os.path.join(r["pasta"], "Anexos"))), ["2026-09-19 - 3A02.ogg"])

    def test_mantem_data_e_anexo_ja_exportados(self):
        r = self.exportar()
        dados = os.path.join(r["pasta"], "Mensagens.json")
        regs = json.loads(ler(dados))
        regs[0]["data"] = "2026-08-12 10:00"  # data exata vinda de outra fonte
        regs[1]["anexo_exportado"] = "nome-antigo.ogg"
        os.rename(os.path.join(r["pasta"], "Anexos", "2026-09-19 - 3A02.ogg"), os.path.join(r["pasta"], "Anexos", "nome-antigo.ogg"))
        with open(dados, "w") as f:
            json.dump(regs, f)
        self.exportar()
        regs = json.loads(ler(dados))
        self.assertEqual(regs[0]["data"], "2026-08-12 10:00")
        self.assertEqual(os.listdir(os.path.join(r["pasta"], "Anexos")), ["nome-antigo.ogg"])

    def test_nao_sobrescreve_transcript_sem_mensagens_json(self):
        pasta = os.path.join(self.base, "Privado - Fulana de Tal")
        os.makedirs(pasta)
        with open(os.path.join(pasta, "Transcript - Conversa privada com Fulana de Tal.md"), "w") as f:
            f.write("feito à mão")
        with self.assertRaises(exportar.ErroExportacao):
            self.exportar()
        self.assertEqual(ler(os.path.join(pasta, "Transcript - Conversa privada com Fulana de Tal.md")), "feito à mão")


class Sync(Caso):
    def setUp(self):
        super().setUp()
        w = self.waha
        w.chats = [{"id": FULANA, "name": "Fulana de Tal", "ts": AGORA - DIA},
                   {"id": BELTRANO, "name": "Beltrano", "ts": AGORA - DIA},
                   {"id": "444@lid", "name": "Beltrano Lima", "ts": AGORA - DIA},
                   {"id": GRUPO, "name": "Equipe Projeto", "ts": AGORA - DIA}]
        for chat in (FULANA, BELTRANO, "444@lid", GRUPO):
            w.msg(chat, "M" + chat[:3], AGORA - DIA, corpo=f"oi de {chat}")
        w.lids = [{"lid": FULANA, "pn": "554891234567@c.us"}]

    def test_por_nome_fixa_o_id(self):
        cfg = self.config(sync={"destino": os.path.join(self.tmp, "Notas"),
                                "conversas": [{"conversa": "Fulana de Tal"}, {"conversa": "Equipe Projeto"}]})
        r = sync.executar(cfg, log=lambda *_: None)
        self.assertEqual([t for t, _, _ in r], ["ok", "ok"])
        # dados privados: só o usuário lê
        self.assertEqual(os.stat(cfg.pasta_dados).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(cfg.pasta_dados, "sync-estado.json")).st_mode & 0o777, 0o600)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "Notas", "Grupo Equipe Projeto")))
        self.waha.chats[0]["name"] = "Fulana T."  # o nome mudou no WhatsApp: segue pelo id gravado
        r = sync.executar(cfg, log=lambda *_: None)
        self.assertEqual(r[0][0], "ok")

    def test_nome_ambiguo_vira_erro_sem_parar_os_outros(self):
        cfg = self.config(sync={"destino": os.path.join(self.tmp, "Notas"),
                                "conversas": [{"conversa": "beltr"}, {"conversa": "Fulana de Tal"}]})
        r = sync.executar(cfg, log=lambda *_: None)
        self.assertEqual([t for t, _, _ in r], ["erro", "ok"])
        self.assertIn("Mais de uma conversa", r[0][2])

    def test_obsidian_crm(self):
        vault = os.path.join(self.tmp, "Vault")
        vault_crm(vault, "14 - CRM", {"Fulana de Tal": "+5548991234567", "Beltrano Lima": "", "Carlos": "+5511900000001"})
        antes = hashes(os.path.join(vault, "14 - CRM", "People"))
        cfg = self.config(sync={"obsidian_crm": {"vault": vault, "pessoas": {"Beltrano Lima": "444@lid"},
                                                 "grupos": [{"conversa": "Equipe Projeto", "nome": "Projeto"}]}})
        r = {rotulo: tipo for tipo, rotulo, _ in sync.executar(cfg, log=lambda *_: None)}
        self.assertEqual(r, {"People/Fulana de Tal": "ok",       # telefone sem o 9 no WhatsApp
                             "People/Beltrano Lima": "ok",      # confirmado no config
                             "People/Carlos": "pendente",    # sem conversa: não associa por nome
                             "Group/Projeto": "ok"})
        wa = os.path.join(vault, "14 - CRM", "WhatsApp")
        self.assertTrue(os.path.isfile(os.path.join(wa, "People", "Fulana de Tal", "Mensagens.json")))
        self.assertTrue(os.path.isfile(os.path.join(wa, "Group", "Projeto", "Mensagens.json")))
        self.assertIn("obsidian-crm", ler(os.path.join(wa, "Status da sincronização.md")))
        self.assertEqual(antes, hashes(os.path.join(vault, "14 - CRM", "People")))  # só lê as notas do CRM

    def test_obsidian_crm_em_duas_contas(self):
        from tests.fakes import CHAVE, WahaFalso
        pessoal = WahaFalso()
        self.addCleanup(pessoal.parar)
        os.environ["WAHA_API_KEY_PESSOAL"] = CHAVE
        self.addCleanup(os.environ.pop, "WAHA_API_KEY_PESSOAL")
        # FULANA está nas duas contas; no trabalho, a conversa mais antiga passa da janela do sync
        self.waha.msg(FULANA, "ANTIGA", AGORA - 200 * DIA, corpo="mensagem de meses atrás")
        pessoal.chats = [{"id": FULANA, "name": "Fulana", "ts": AGORA - DIA}, {"id": "777@lid", "name": "Gringo", "ts": AGORA - DIA}]
        pessoal.msg(FULANA, "P1", AGORA - DIA, corpo="oi pelo pessoal")
        pessoal.msg("777@lid", "P2", AGORA - DIA, corpo="hello")
        pessoal.lids = [{"lid": FULANA, "pn": "554891234567@c.us"}, {"lid": "777@lid", "pn": "14155550100@c.us"}]
        # Beltrano Lima: número antigo no CRM (conversa BELTRANO) e o novo confirmado (444@lid)
        self.waha.lids.append({"lid": BELTRANO, "pn": "5511988880000@c.us"})
        vault = os.path.join(self.tmp, "Vault")
        vault_crm(vault, "CRM", {"Fulana de Tal": "48991234567", "Beltrano Lima": "11988880000",
                                 "Gringo": "+14155550100", "Sem Ninguém": "11977776666"})
        contas = {"trabalho": {"fonte": "waha", "url": self.waha.url, "sessao": "default"},
                  "pessoal": {"fonte": "waha", "url": pessoal.url, "sessao": "pessoal"}}
        cfg = self.config(contas=contas, sync={"dias": 30, "obsidian_crm": {
            "vault": vault, "contas": ["trabalho", "pessoal"], "pessoas": {"Beltrano Lima": "444@lid"}}})
        r = {rotulo: tipo for tipo, rotulo, _ in sync.executar(cfg, log=lambda *_: None)}
        self.assertEqual(r, {"People/Fulana de Tal": "ok",                     # sem 55 no CRM
                             "People/Fulana de Tal (pessoal)": "ok",           # mesma pessoa na outra conta
                             "People/Beltrano Lima": "ok",                     # confirmada
                             "People/Beltrano Lima (+55 11 98888-0000)": "ok", # número antigo, do CRM
                             "People/Gringo (pessoal)": "ok",                  # +1 explícito: sem 55
                             "People/Sem Ninguém": "pendente"})
        md = ler(os.path.join(vault, "CRM", "WhatsApp", "People", "Fulana de Tal",
                              "Transcript - Conversa privada com Fulana de Tal.md"))
        self.assertIn("mensagem de meses atrás", md)  # primeira exportação: histórico completo
        status = ler(os.path.join(vault, "CRM", "WhatsApp", "Status da sincronização.md"))
        self.assertIn("trabalho (WAHA", status)
        self.assertIn("pessoal (WAHA", status)

    def test_trava(self):
        cfg = self.config()
        with trava(os.path.join(cfg.pasta_dados, "sync.lock")):
            with self.assertRaises(Ocupado):
                with trava(os.path.join(cfg.pasta_dados, "sync.lock")):
                    pass


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import os
import unittest

from tests.base import AGORA, DIA, Caso
from tests.fakes import vault_crm
from whatsapp_local import exportar, operacoes, sync
from whatsapp_local.config import abrir_fonte
from whatsapp_local.trava import Ocupado, trava

ANA = "111111111111111@lid"
BRUNO = "333333333333333@lid"
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
        self.waha.chats = [{"id": ANA, "name": "Ana Souza", "ts": AGORA - DIA}]
        self.waha.msg(ANA, "3A01", AGORA - 40 * DIA, corpo="mensagem antiga")
        self.audio = self.waha.msg(ANA, "3A02", AGORA - 2 * DIA, tipo="ptt", duration="5", mimetype="audio/ogg")
        self.waha.arquivos = {self.audio: b"OggS"}
        self.fonte = abrir_fonte(self.config())
        self.base = os.path.join(self.tmp, "Notas")

    def exportar(self, dias=None):
        conv = self.fonte.conversas()[0]
        msgs = self.fonte.mensagens(ANA, AGORA - dias * DIA if dias else None)
        operacoes.transcrever(self.fonte, msgs, {}, log=lambda *_: None)
        regs = operacoes.registros(self.fonte, conv, msgs, {})
        return exportar.exportar(regs, ANA, self.base, "Privado - Ana Souza", "Conversa privada com Ana Souza")

    def test_janela_curta_nao_apaga_historico(self):
        self.exportar()
        self.waha.mensagens[ANA] = [m for m in self.waha.mensagens[ANA] if "3A01" not in m["id"]]  # sumiu da fonte
        r = self.exportar(dias=30)
        md = ler(os.path.join(r["pasta"], "Transcript - Conversa privada com Ana Souza.md"))
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
        pasta = os.path.join(self.base, "Privado - Ana Souza")
        os.makedirs(pasta)
        with open(os.path.join(pasta, "Transcript - Conversa privada com Ana Souza.md"), "w") as f:
            f.write("feito à mão")
        with self.assertRaises(exportar.ErroExportacao):
            self.exportar()
        self.assertEqual(ler(os.path.join(pasta, "Transcript - Conversa privada com Ana Souza.md")), "feito à mão")


class Sync(Caso):
    def setUp(self):
        super().setUp()
        w = self.waha
        w.chats = [{"id": ANA, "name": "Ana Souza", "ts": AGORA - DIA},
                   {"id": BRUNO, "name": "Bruno", "ts": AGORA - DIA},
                   {"id": "444@lid", "name": "Bruno Lima", "ts": AGORA - DIA},
                   {"id": GRUPO, "name": "Equipe Projeto", "ts": AGORA - DIA}]
        for chat in (ANA, BRUNO, "444@lid", GRUPO):
            w.msg(chat, "M" + chat[:3], AGORA - DIA, corpo=f"oi de {chat}")
        w.lids = [{"lid": ANA, "pn": "554891234567@c.us"}]

    def test_por_nome_fixa_o_id(self):
        cfg = self.config(sync={"destino": os.path.join(self.tmp, "Notas"),
                                "conversas": [{"conversa": "Ana Souza"}, {"conversa": "Equipe Projeto"}]})
        r = sync.executar(cfg, log=lambda *_: None)
        self.assertEqual([t for t, _, _ in r], ["ok", "ok"])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "Notas", "Grupo Equipe Projeto")))
        self.waha.chats[0]["name"] = "Ana S."  # o nome mudou no WhatsApp: segue pelo id gravado
        r = sync.executar(cfg, log=lambda *_: None)
        self.assertEqual(r[0][0], "ok")

    def test_nome_ambiguo_vira_erro_sem_parar_os_outros(self):
        cfg = self.config(sync={"destino": os.path.join(self.tmp, "Notas"),
                                "conversas": [{"conversa": "brun"}, {"conversa": "Ana Souza"}]})
        r = sync.executar(cfg, log=lambda *_: None)
        self.assertEqual([t for t, _, _ in r], ["erro", "ok"])
        self.assertIn("Mais de uma conversa", r[0][2])

    def test_obsidian_crm(self):
        vault = os.path.join(self.tmp, "Vault")
        vault_crm(vault, "14 - CRM", {"Ana Souza": "+5548991234567", "Bruno Lima": "", "Carlos": "+5511900000001"})
        antes = hashes(os.path.join(vault, "14 - CRM", "People"))
        cfg = self.config(sync={"obsidian_crm": {"vault": vault, "pessoas": {"Bruno Lima": "444@lid"},
                                                 "grupos": [{"conversa": "Equipe Projeto", "nome": "Projeto"}]}})
        r = {rotulo: tipo for tipo, rotulo, _ in sync.executar(cfg, log=lambda *_: None)}
        self.assertEqual(r, {"People/Ana Souza": "ok",       # telefone sem o 9 no WhatsApp
                             "People/Bruno Lima": "ok",      # confirmado no config
                             "People/Carlos": "pendente",    # sem conversa: não associa por nome
                             "Group/Projeto": "ok"})
        wa = os.path.join(vault, "14 - CRM", "WhatsApp")
        self.assertTrue(os.path.isfile(os.path.join(wa, "People", "Ana Souza", "Mensagens.json")))
        self.assertTrue(os.path.isfile(os.path.join(wa, "Group", "Projeto", "Mensagens.json")))
        self.assertIn("obsidian-crm", ler(os.path.join(wa, "Status da sincronização.md")))
        self.assertEqual(antes, hashes(os.path.join(vault, "14 - CRM", "People")))  # só lê as notas do CRM

    def test_trava(self):
        cfg = self.config()
        with trava(os.path.join(cfg.pasta_dados, "sync.lock")):
            with self.assertRaises(Ocupado):
                with trava(os.path.join(cfg.pasta_dados, "sync.lock")):
                    pass


if __name__ == "__main__":
    unittest.main()

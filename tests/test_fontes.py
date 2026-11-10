# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
import os
import sqlite3
import unittest

from tests.base import AGORA, DIA, Caso
from tests.fakes import criar_app_mac
from whatsapp_local.config import abrir_fonte
from whatsapp_local.modelo import (Ambigua, ErroFonte, MidiaIndisponivel, normalizar_telefone, resolver_conversa,
                                   variantes_telefone)

FULANA = "111111111111111@lid"
GRUPO = "120363000000000001@g.us"


class Telefones(unittest.TestCase):
    def test_nono_digito_nos_dois_sentidos(self):
        self.assertEqual(variantes_telefone("5548991234567"), {"5548991234567", "554891234567"})
        self.assertEqual(variantes_telefone("554891234567"), {"554891234567", "5548991234567"})
        self.assertEqual(variantes_telefone("14155550100"), {"14155550100"})


    def test_pais_padrao_so_quando_nao_explicito(self):
        self.assertEqual(normalizar_telefone("19991537534"), "5519991537534")      # DDD + celular
        self.assertEqual(normalizar_telefone("(11) 5555-0100"), "551155550100")    # DDD + fixo
        self.assertEqual(normalizar_telefone("+5548991234567"), "5548991234567")   # já tem o país
        self.assertEqual(normalizar_telefone("+14155550100"), "14155550100")       # outro país, explícito
        self.assertEqual(normalizar_telefone("2025550100", ddi="1"), "12025550100")
        self.assertEqual(normalizar_telefone(""), "")


class Resolver(unittest.TestCase):
    convs = [{"id": "1@lid", "nome": "Fulana de Tal", "grupo": False, "ultima": 1},
             {"id": "2@lid", "nome": "Fulana", "grupo": False, "ultima": 1},
             {"id": "3@lid", "nome": "Fulanita", "grupo": False, "ultima": 1},
             {"id": "554891234567@c.us", "nome": "Beltrano", "grupo": False, "ultima": 1}]

    def test_nome_exato_vence_parcial(self):
        self.assertEqual(resolver_conversa(self.convs, "fulana")["id"], "2@lid")

    def test_nome_ambiguo_nao_chuta(self):
        with self.assertRaises(Ambigua):
            resolver_conversa(self.convs, "fulan")

    def test_numero_com_nono_digito(self):
        self.assertEqual(resolver_conversa(self.convs, "+5548991234567")["nome"], "Beltrano")

    def test_numero_sem_codigo_do_pais(self):
        self.assertEqual(resolver_conversa(self.convs, "48991234567")["nome"], "Beltrano")

    def test_nao_achou(self):
        with self.assertRaises(ErroFonte):
            resolver_conversa(self.convs, "Zé")


class Waha(Caso):
    def preparar(self):
        w = self.waha
        w.chats = [{"id": FULANA, "name": "Fulana de Tal", "ts": AGORA - DIA}, {"id": GRUPO, "name": "Equipe", "ts": AGORA - 2 * DIA}]
        w.msg(FULANA, "3A01", AGORA - 3 * DIA, corpo="oi")
        self.audio = w.msg(FULANA, "3A02", AGORA - 2 * DIA, tipo="ptt", duration="12", mimetype="audio/ogg; codecs=opus")
        # mídia que o WEBJS devolve sem timestamp: vale a hora da chave da mídia
        w.msg(FULANA, "3A03", None, tipo="ptt", mediaKeyTimestamp=AGORA - DIA - 60, mimetype="audio/ogg; codecs=opus")
        w.msg(FULANA, "3A05", None, corpo="texto que o WEBJS devolve sem data nenhuma")
        w.msg(FULANA, "3A04", AGORA - DIA, tipo="document", filename="Proposta.pdf", caption="Proposta.pdf",
              mimetype="application/pdf")
        w.msg(GRUPO, "3B01", AGORA - 2 * DIA, corpo="bom dia", participante="222@lid")
        w.contatos = [{"id": "5511988887777@c.us", "name": "Carla Lima"}]
        w.lids = [{"lid": "222@lid", "pn": "5511988887777@c.us"}, {"lid": FULANA, "pn": "554891234567@c.us"}]
        w.arquivos = {self.audio: b"OggS-audio"}
        return abrir_fonte(self.config())

    def test_mensagens_no_formato_comum(self):
        fonte = self.preparar()
        msgs = fonte.mensagens(FULANA, AGORA - 10 * DIA)
        self.assertEqual([m["id"] for m in msgs], ["3A01", "3A02", "3A03", "3A04"])
        self.assertTrue(msgs[2]["data_aproximada"])
        doc = msgs[3]
        self.assertEqual((doc["texto"], doc["legenda"]), ("Proposta.pdf", None))  # legenda igual ao nome não repete
        self.assertEqual(msgs[1]["duracao"], 12)
        # sem data nenhuma: fica de fora, mas registrado para o sync avisar
        self.assertEqual(fonte.sem_data[FULANA], ["false_" + FULANA + "_3A05"])

    def test_periodo_nao_para_em_mensagem_sem_data(self):
        fonte = self.preparar()
        # 3A03 vem sem timestamp: o filtro do WAHA pararia ali e perderia 3A01 e 3A02
        self.assertEqual([m["id"] for m in fonte.mensagens(FULANA, AGORA - 10 * DIA)], ["3A01", "3A02", "3A03", "3A04"])
        self.assertTrue(all("filter.timestamp" not in p for p in self.waha.pedidos))

    def test_nome_do_participante_pelo_telefone(self):
        fonte = self.preparar()
        self.assertEqual(fonte.nomes()["222@lid"], "Carla Lima")

    def test_indice_de_telefone_aceita_o_nono_digito(self):
        fonte = self.preparar()
        self.assertIn(FULANA, fonte.indice_telefones()["5548991234567"])

    def test_baixa_e_nao_repete_o_que_saiu_do_servidor(self):
        fonte = self.preparar()
        msgs = {m["id"]: m for m in fonte.mensagens(FULANA)}
        caminho = fonte.baixar(msgs["3A02"])
        with open(caminho, "rb") as f:
            self.assertEqual(f.read(), b"OggS-audio")
        self.assertEqual(os.path.splitext(caminho)[1], ".opus")
        with self.assertRaises(MidiaIndisponivel):
            fonte.baixar(msgs["3A03"])
        self.assertEqual(fonte.status_midia(msgs["3A03"])[0], "indisponivel")

    def test_api_key_errada(self):
        self.preparar()
        os.environ["WAHA_API_KEY_TRABALHO"] = "errada"
        with self.assertRaises(ErroFonte):
            abrir_fonte(self.config()).conversas()


class DataWaha(unittest.TestCase):
    def test_data_em_milissegundos_vira_segundos(self):
        from whatsapp_local.waha import data_de
        self.assertEqual(data_de({"_data": {"mediaKeyTimestamp": 1793500000123}}), 1793500000)
        self.assertEqual(data_de({"timestamp": 1793500000}), 1793500000)
        self.assertIsNone(data_de({}))


class Desktop(Caso):
    def test_le_o_app_do_mac(self):
        pasta = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(pasta, "Message", "Media"))
        with open(os.path.join(pasta, "Message", "Media", "a.opus"), "wb") as f:
            f.write(b"OggS")
        criar_app_mac(pasta, [(1, FULANA, "Fulana de Tal", False), (2, GRUPO, "Equipe", True)], [
            {"pk": 10, "chat_pk": 1, "wid": "3A01", "ts": AGORA - 3 * DIA, "texto": "oi"},
            {"pk": 11, "chat_pk": 1, "wid": "3A02", "tipo": 3, "ts": AGORA - 2 * DIA, "caminho": "Media/a.opus", "duracao": 12},
            {"pk": 12, "chat_pk": 1, "wid": None, "tipo": 10, "ts": AGORA - DIA // 2},
            {"pk": 13, "chat_pk": 2, "wid": "3B01", "ts": AGORA - DIA, "texto": "bom dia", "membro": ("222@lid", None)},
        ], agenda=[("222@lid", "5511988887777@s.whatsapp.net", "Carla Lima", "+55 11 98888-7777")])
        cfg = self.config(contas={"mac": {"fonte": "desktop", "pasta_whatsapp": pasta}}, conta_padrao="mac")
        fonte = abrir_fonte(cfg)
        msgs = fonte.mensagens(FULANA)
        self.assertEqual([m["id"] for m in msgs], ["3A01", "3A02", "pk12"])  # sem id do WhatsApp: id local
        self.assertEqual(fonte.status_midia(msgs[1])[0], "disco")
        self.assertEqual(fonte.nomes()["222@lid"], "Carla Lima")
        self.assertIn("222@lid", fonte.indice_telefones()["5511988887777"])
        self.assertEqual([c["nome"] for c in fonte.conversas()], ["Fulana de Tal", "Equipe"])


class Wacli(Caso):
    def preparar(self, **extra):
        pasta = os.path.join(self.tmp, "espelho")
        os.makedirs(pasta)
        self.audio = os.path.join(pasta, "a.opus")
        with open(self.audio, "wb") as f:
            f.write(b"OggS")
        con = sqlite3.connect(os.path.join(pasta, "wacli.db"))
        con.executescript("""
            create table chats (jid text primary key, kind text, name text, last_message_ts integer);
            create table contacts (jid text primary key, phone text, push_name text, full_name text,
                first_name text, business_name text, system_name text);
            create table contact_aliases (jid text primary key, alias text);
            create table messages (rowid integer primary key, chat_jid text, msg_id text, sender_jid text,
                sender_name text, ts integer, from_me integer, text text, display_text text, media_type text,
                media_caption text, filename text, mime_type text, file_length integer, local_path text,
                direct_path text, media_unavailable_at integer, revoked integer, reaction_to_id text,
                deleted_at integer);
        """)
        con.execute("insert into chats values (?, 'dm', 'Fulana de Tal', ?)", (FULANA, AGORA - DIA))
        con.execute("insert into chats values (?, 'group', 'Equipe', ?)", (GRUPO, AGORA - 2 * DIA))
        con.execute("insert into chats values ('status@broadcast', 'broadcast', 'Status', ?)", (AGORA,))
        con.execute("insert into contacts values (?, '554891234567', null, 'Fulana de Tal', null, null, null)", (FULANA,))
        con.execute("insert into contacts values ('222@lid', '5511988887777', 'Carla', null, null, null, null)")
        con.execute("insert into contact_aliases values ('222@lid', 'Carla Lima')")
        linhas = [
            (FULANA, "3A01", None, AGORA - 3 * DIA, 0, "oi", None, None, None, None, None, None, None, None, 0, None, None),
            (FULANA, "3A02", None, AGORA - 2 * DIA, 0, None, None, "audio", None, None, "audio/ogg", 4, self.audio, None, 0, None, None),
            (FULANA, "3A03", None, AGORA - DIA, 0, None, None, "document", "Proposta.pdf", "Proposta.pdf", "application/pdf", 9, None, "/mmg", 0, None, None),
            (FULANA, "3A04", None, AGORA, 0, None, None, None, None, None, None, None, None, None, 0, "3A01", None),
            (FULANA, "3A05", None, AGORA - DIA // 2, 0, "apagada daqui", None, None, None, None, None, None, None, None, 0, None, AGORA),
            (GRUPO, "3B01", "222@lid", AGORA - 2 * DIA, 0, "bom dia", None, None, None, None, None, None, None, None, 0, None, None),
        ]
        con.executemany("""insert into messages (chat_jid, msg_id, sender_jid, ts, from_me, text, display_text,
            media_type, media_caption, filename, mime_type, file_length, local_path, direct_path,
            revoked, reaction_to_id, deleted_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", linhas)
        con.commit()
        con.close()
        cfg = self.config(contas={"espelho": dict({"fonte": "wacli", "store": pasta}, **extra)}, conta_padrao="espelho")
        return abrir_fonte(cfg)

    def test_mensagens_no_formato_comum(self):
        fonte = self.preparar()
        msgs = fonte.mensagens(FULANA, AGORA - 10 * DIA)
        self.assertEqual([m["id"] for m in msgs], ["3A01", "3A02", "3A03"])  # reação e apagada ficam de fora
        self.assertEqual(msgs[2]["texto"], "Proposta.pdf")
        self.assertIsNone(msgs[2]["legenda"])
        self.assertEqual([c["nome"] for c in fonte.conversas()], ["Fulana de Tal", "Equipe"])
        self.assertEqual(fonte.nomes()["222@lid"], "Carla Lima")
        self.assertIn(FULANA, fonte.indice_telefones()["5548991234567"])
        self.assertEqual(fonte.status_midia(msgs[1])[0], "disco")

    def test_abre_banco_wal(self):
        fonte = self.preparar()
        con = sqlite3.connect(os.path.join(fonte.store, "wacli.db"))
        con.execute("pragma journal_mode=wal")
        con.close()
        fonte._con = None
        self.assertEqual([c["nome"] for c in fonte.conversas() if not c["grupo"]], ["Fulana de Tal"])

    def test_baixa_pelo_comando_somente_leitura(self):
        fonte = self.preparar()
        script = os.path.join(self.tmp, "wacli")
        with open(script, "w") as f:
            f.write("#!/bin/sh\nprintf %s \"$*\" > \"$0.args\"\nprintf OggS > \"${11}\"\n")
        os.chmod(script, 0o755)
        fonte.executavel = script
        msg = next(m for m in fonte.mensagens(FULANA) if m["id"] == "3A03")
        caminho = fonte.baixar(msg)
        with open(caminho, "rb") as f:
            self.assertEqual(f.read(), b"OggS")
        with open(script + ".args") as f:
            self.assertIn("--read-only", f.read())

    def test_conta_wacli_desconhecida(self):
        base = os.path.join(self.tmp, "wacli-home")
        os.makedirs(base)
        config = os.path.join(base, "config.yaml")
        with open(config, "w") as f:
            f.write("default_account: pessoal\naccounts:\n  pessoal:\n    store: accounts/pessoal\n")
        from whatsapp_local.wacli import ler_contas, resolver_store
        self.assertEqual(ler_contas(config), ("pessoal", {"pessoal": "accounts/pessoal"}))
        os.environ["WACLI_STORE_DIR"] = base
        self.addCleanup(os.environ.pop, "WACLI_STORE_DIR", None)
        self.assertTrue(resolver_store({"nome": "espelho"}).endswith("accounts/pessoal"))
        xdg = os.path.join(self.tmp, "xdg")
        os.makedirs(os.path.join(xdg, "wacli"))
        with open(os.path.join(xdg, "wacli", "config.yaml"), "w") as f:
            f.write("default_account: trabalho\naccounts:\n  trabalho:\n    store: accounts/trabalho\n")
        os.environ["XDG_STATE_HOME"] = xdg
        self.addCleanup(os.environ.pop, "XDG_STATE_HOME", None)
        os.environ.pop("WACLI_STORE_DIR", None)
        self.assertTrue(resolver_store({"nome": "espelho", "conta_wacli": "trabalho"}).endswith("accounts/trabalho"))
        with self.assertRaises(ErroFonte):
            resolver_store({"nome": "espelho", "conta_wacli": "outra"})

    def test_lid_do_session_e_o_mesmo_id_das_outras_fontes(self):
        fonte = self.preparar()
        con = sqlite3.connect(os.path.join(fonte.store, "session.db"))
        con.execute("create table whatsmeow_lid_map (lid text primary key, pn text unique not null)")
        con.execute("insert into whatsmeow_lid_map values ('111111111111111', '554891234567')")
        con.commit()
        con.close()
        # a conversa está gravada no telefone; o id exposto é o @lid, como no app do Mac e no WAHA
        con = sqlite3.connect(os.path.join(fonte.store, "wacli.db"))
        con.execute("update chats set jid = '554891234567@s.whatsapp.net' where jid = ?", (FULANA,))
        con.execute("update messages set chat_jid = '554891234567@s.whatsapp.net' where chat_jid = ?", (FULANA,))
        con.commit()
        con.close()
        fonte._con = None
        fonte._lids = None
        self.assertEqual([c["id"] for c in fonte.conversas() if not c["grupo"]], [FULANA])
        self.assertEqual([m["id"] for m in fonte.mensagens(FULANA)], ["3A01", "3A02", "3A03"])
        self.assertIn(FULANA, fonte.indice_telefones()["5548991234567"])
        script = os.path.join(self.tmp, "wacli-midia")
        with open(script, "w") as f:
            f.write("#!/bin/sh\nprintf %s \"$*\" > \"$0.args\"\nprintf OggS > \"${11}\"\n")
        os.chmod(script, 0o755)
        fonte.executavel = script
        msg = next(m for m in fonte.mensagens(FULANA) if m["id"] == "3A03")
        fonte.baixar(msg)
        with open(script + ".args") as f:
            self.assertIn("--chat 554891234567@s.whatsapp.net", f.read())

    def test_atualizar_o_espelho_antes_de_ler(self):
        fonte = self.preparar()
        script = os.path.join(self.tmp, "wacli-sync")
        with open(script, "w") as f:
            f.write("#!/bin/sh\nprintf %s \"$*\" > \"$0.args\"\nexit 0\n")
        os.chmod(script, 0o755)
        fonte.executavel = script
        fonte.atualizar()
        with open(script + ".args") as f:
            args = f.read()
        self.assertIn("sync --once", args)
        self.assertNotIn("send", args)
        with open(script, "w") as f:
            f.write("#!/bin/sh\necho falhou >&2\nexit 1\n")
        os.chmod(script, 0o755)
        with self.assertRaises(ErroFonte) as ctx:
            fonte.atualizar()
        self.assertIn("Nada foi lido", str(ctx.exception))

    def test_sync_nao_le_espelho_que_nao_atualizou(self):
        from whatsapp_local.sync import Contexto, preparar_espelhos
        fonte = self.preparar()
        script = os.path.join(self.tmp, "wacli-falha")
        with open(script, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(script, 0o755)
        cfg = self.config(contas={"espelho": {"fonte": "wacli", "store": fonte.store, "executavel": script}},
                          conta_padrao="espelho", sync={"conversas": [{"conversa": "Fulana"}]})
        indisponiveis = preparar_espelhos(cfg, log=lambda *_: None)
        self.assertIn("espelho", indisponiveis)
        with self.assertRaises(ErroFonte):
            Contexto(cfg, indisponiveis).conversas("espelho")


if __name__ == "__main__":
    unittest.main()

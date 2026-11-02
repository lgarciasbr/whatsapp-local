# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
import os
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


if __name__ == "__main__":
    unittest.main()

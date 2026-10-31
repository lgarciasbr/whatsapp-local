"""Fontes falsas para os testes. Tudo inventado: nenhum dado real."""
import json
import os
import sqlite3
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

CHAVE = "chave-de-teste"
APPLE_EPOCH = 978307200


class WahaFalso:
    """Servidor HTTP com o subconjunto da API do WAHA que o whatsapp-local usa."""

    def __init__(self):
        self.chats = []         # [{"id", "name", "ts"}]
        self.mensagens = {}     # chat -> [mensagem WAHA crua]
        self.contatos = []      # [{"id", "name", "pushname"}]
        self.lids = []          # [{"lid", "pn"}]
        self.arquivos = {}      # id WAHA da mensagem -> bytes (mídia ainda no WhatsApp)
        self.pedidos = []
        servidor = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                servidor.pedidos.append(self.path)
                if self.headers.get("X-Api-Key") != CHAVE:
                    return self._json({"message": "Unauthorized"}, 401)
                url = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                partes = [urllib.parse.unquote(p) for p in url.path.split("/")[1:]]
                self._json(*servidor.rota(partes, q))

            def _json(self, corpo, status=200):
                dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode()
                self.send_response(status)
                self.end_headers()
                self.wfile.write(dados)

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def parar(self):
        self.http.shutdown()
        self.http.server_close()

    def rota(self, p, q):
        if p[:2] == ["api", "sessions"]:
            return {"name": p[2], "status": "WORKING", "me": {"id": "5511900000000@c.us"}}, 200
        if p[:2] == ["api", "contacts"]:
            return self.contatos, 200
        if p[:2] == ["api", "files"]:
            return self.arquivos[p[3]], 200
        if p[2] == "lids":
            return self.lids, 200
        if p[2:4] == ["chats", "overview"]:
            ini = int(q.get("offset", 0))
            pagina = self.chats[ini:ini + int(q.get("limit", 100))]
            return [{"id": c["id"], "name": c["name"], "lastMessage": {"timestamp": c["ts"]}} for c in pagina], 200
        if p[2] == "chats" and p[4] == "messages" and len(p) == 5:
            msgs = sorted(self.mensagens.get(p[3], []), key=lambda m: -(m.get("timestamp") or 0))
            if "filter.timestamp.gte" in q:
                msgs = [m for m in msgs if (m.get("timestamp") or m["_data"].get("mediaKeyTimestamp")) >= int(q["filter.timestamp.gte"])]
            ini = int(q.get("offset", 0))
            return msgs[ini:ini + int(q.get("limit", 100))], 200
        if p[2] == "chats" and p[4] == "messages":
            m = next(m for m in self.mensagens[p[3]] if m["id"] == p[5])
            m = dict(m)
            if m["id"] in self.arquivos:
                m["media"] = {"url": f"http://localhost:3000/api/files/default/{m['id']}", "mimetype": m["_data"]["mimetype"]}
            else:
                m["media"] = {"url": None, "error": {"details": "Error: has no media\n  at ..."}}
            return m, 200
        return {"message": "não implementado: " + "/".join(p)}, 404

    def msg(self, chat, wid, ts, tipo="chat", corpo="", eu=False, participante=None, **extra):
        mid = f"{'true' if eu else 'false'}_{chat}_{wid}" + (f"_{participante}" if participante else "")
        x = {"id": mid, "timestamp": ts, "fromMe": eu, "body": corpo, "participant": participante,
             "_data": dict({"type": tipo}, **extra)}
        if ts is None:
            del x["timestamp"]
        self.mensagens.setdefault(chat, []).append(x)
        return mid


def criar_app_mac(pasta, conversas, mensagens, agenda=()):
    """Cria ChatStorage.sqlite e ContactsV2.sqlite mínimos, no esquema do WhatsApp Desktop.
    conversas: [(pk, jid, nome, grupo)]; mensagens: [dict com pk, chat_pk, wid, tipo, eu, ts, texto, ...]."""
    os.makedirs(os.path.join(pasta, "Message"), exist_ok=True)
    con = sqlite3.connect(os.path.join(pasta, "ChatStorage.sqlite"))
    con.executescript("""
        create table ZWACHATSESSION (Z_PK integer primary key, ZCONTACTJID text, ZPARTNERNAME text,
            ZSESSIONTYPE integer, ZLASTMESSAGEDATE real);
        create table ZWAMESSAGE (Z_PK integer primary key, ZSTANZAID text, ZMESSAGETYPE integer, ZISFROMME integer,
            ZMESSAGEDATE real, ZTEXT text, ZCHATSESSION integer, ZMEDIAITEM integer, ZGROUPMEMBER integer);
        create table ZWAMEDIAITEM (Z_PK integer primary key, ZMEDIALOCALPATH text, ZMEDIAURL text, ZMEDIAKEY blob,
            ZTITLE text, ZMOVIEDURATION integer, ZFILESIZE integer);
        create table ZWAGROUPMEMBER (Z_PK integer primary key, ZCONTACTNAME text, ZFIRSTNAME text, ZMEMBERJID text);
        create table ZWAPROFILEPUSHNAME (ZJID text, ZPUSHNAME text);
    """)
    for pk, jid, nome, grupo in conversas:
        ultima = max((m["ts"] for m in mensagens if m["chat_pk"] == pk), default=0) - APPLE_EPOCH
        con.execute("insert into ZWACHATSESSION values (?,?,?,?,?)", (pk, jid, nome, 1 if grupo else 0, ultima))
    for m in mensagens:
        media = None
        if m.get("caminho") or m.get("duracao"):
            media = m["pk"]
            con.execute("insert into ZWAMEDIAITEM values (?,?,?,?,?,?,?)",
                        (media, m.get("caminho"), None, None, None, m.get("duracao"), None))
        membro = None
        if m.get("membro"):
            membro = m["pk"]
            con.execute("insert into ZWAGROUPMEMBER values (?,?,?,?)", (membro, m["membro"][1], None, m["membro"][0]))
        con.execute("insert into ZWAMESSAGE values (?,?,?,?,?,?,?,?,?)",
                    (m["pk"], m.get("wid"), m.get("tipo", 0), 1 if m.get("eu") else 0, m["ts"] - APPLE_EPOCH,
                     m.get("texto"), m["chat_pk"], media, membro))
    con.commit()
    con.close()
    con = sqlite3.connect(os.path.join(pasta, "ContactsV2.sqlite"))
    con.execute("create table ZWAADDRESSBOOKCONTACT (ZLID text, ZWHATSAPPID text, ZFULLNAME text, ZPHONENUMBER text)")
    con.executemany("insert into ZWAADDRESSBOOKCONTACT values (?,?,?,?)", agenda)
    con.commit()
    con.close()


def vault_crm(pasta, raiz, pessoas):
    """Vault do Obsidian com o plugin CRM: pessoas = {nome: telefone ou None}."""
    os.makedirs(os.path.join(pasta, ".obsidian", "plugins", "crm"), exist_ok=True)
    with open(os.path.join(pasta, ".obsidian", "plugins", "crm", "data.json"), "w") as f:
        json.dump({"crmRoot": raiz}, f)
    people = os.path.join(pasta, raiz, "People")
    os.makedirs(people, exist_ok=True)
    for nome, telefone in pessoas.items():
        with open(os.path.join(people, nome + ".md"), "w", encoding="utf-8") as f:
            f.write(f"---\ntype: crm/person\ncrm_id: person-{nome.lower()}\nname: {nome}\n"
                    f"phone: {json.dumps(telefone) if telefone else ''}\ntags:\n  - crm/person\n---\n\n# {nome}\n")
    with open(os.path.join(people, "Nota solta.md"), "w") as f:
        f.write("# não é pessoa do CRM\n")

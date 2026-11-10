# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Fonte wacli: o espelho local do wacli (https://wacli.sh), só leitura.

O wacli é um aparelho vinculado ao WhatsApp nesta máquina. Ele guarda as mensagens
em wacli.db. Esta fonte lê esse banco e, para mídia que ainda não está no disco,
pede o arquivo ao comando `wacli` em modo somente leitura (sem marcar como lida e
sem gravar no espelho). Quem mantém o espelho atualizado é o `wacli sync`, fora daqui.
"""
import os
import shutil
import sqlite3
import subprocess

from .config import expandir
from .modelo import MIDIA, ErroFonte, MidiaIndisponivel, ext_de, variantes_telefone

TIPO = {"image": 1, "video": 2, "audio": 3, "ptt": 3, "voice": 3, "vcard": 4, "contact": 4,
        "location": 5, "live_location": 5, "document": 8, "gif": 11, "sticker": 15}
PASTA_WACLI = os.path.expanduser("~/.wacli")


class FonteWacli:
    tipo = "wacli"

    def __init__(self, conta, cache):
        self.conta, self.cache = conta, cache
        self.store = resolver_store(conta)
        self.banco = self.store if self.store.endswith(".db") else os.path.join(self.store, "wacli.db")
        if self.store.endswith(".db"):
            self.store = os.path.dirname(self.banco)
        self.executavel = conta.get("executavel") or shutil.which("wacli")
        self.sessao = os.path.join(self.store, "session.db")
        self._con = None
        self._lids = None  # telefone -> lid, só o mapa de identidade (não lê chaves)

    @property
    def con(self):
        if self._con is None:
            if not os.path.exists(self.banco):
                raise ErroFonte(f"Não achei o espelho do wacli em {self.banco}. "
                                "Pareie a conta com `wacli auth` e rode `wacli sync --once`.")
            # mode=ro falha no banco WAL do wacli ("unable to open database file"), mesmo com o arquivo no lugar.
            # query_only lê o WAL e recusa escrita. Não é a flag URI mode=ro.
            try:
                con = sqlite3.connect(self.banco)
                con.execute("pragma query_only=on")
            except sqlite3.Error as e:
                raise ErroFonte(f"Não consegui ler {self.banco}: {e}. Se o `wacli sync` estiver rodando, tente de novo.")
            con.row_factory = sqlite3.Row
            self._con = con
        return self._con

    @property
    def lids(self):
        """telefone (só dígitos) -> lid (só dígitos). O wacli guarda a conversa no telefone;
        o app do Mac e o WAHA usam o @lid. O mapa fica no session.db, ao lado do espelho."""
        if self._lids is None:
            self._lids = {}
            if os.path.exists(self.sessao):
                try:
                    con = sqlite3.connect(self.sessao)
                    con.execute("pragma query_only=on")
                    for lid, pn in con.execute("select lid, pn from whatsmeow_lid_map"):
                        if lid and pn:
                            self._lids["".join(c for c in pn if c.isdigit())] = "".join(c for c in lid if c.isdigit())
                    con.close()
                except sqlite3.Error:
                    self._lids = {}
        return self._lids

    def _id_exposto(self, jid):
        """O id que as outras fontes usam. Conversa privada com mapa lid fica em @lid."""
        user, _, servidor = (jid or "").partition("@")
        if servidor == "s.whatsapp.net" and user in self.lids:
            return self.lids[user] + "@lid"
        return jid

    def _ids_no_banco(self, chat):
        """O id pedido e o id em que o wacli gravou a mesma conversa."""
        ids = {chat}
        user, _, servidor = (chat or "").partition("@")
        if servidor == "lid":
            for pn, lid in self.lids.items():
                if lid == user:
                    ids.add(pn + "@s.whatsapp.net")
        elif servidor == "s.whatsapp.net" and user in self.lids:
            ids.add(self.lids[user] + "@lid")
        return ids

    def atualizar(self, log=None):
        """Traz as mensagens novas para o espelho e só então deixa ler. Sem isso o arquivo fica parado."""
        if not self.executavel:
            raise ErroFonte("Não achei o comando `wacli` para atualizar o espelho. "
                            "Instale com `brew install openclaw/tap/wacli`.")
        if log:
            log(f"Atualizando o espelho do wacli ({self.store})...")
        try:
            r = subprocess.run([self.executavel, "--store", self.store, "sync", "--once", "--idle-exit", "20s"],
                               capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            raise ErroFonte("O wacli não terminou de atualizar o espelho em 15 minutos. Nada foi lido desse espelho.")
        if r.returncode != 0:
            detalhe = (r.stderr or r.stdout or f"código {r.returncode}").strip().splitlines()
            raise ErroFonte("Não consegui atualizar o espelho do wacli: " + (detalhe[-1] if detalhe else "sem detalhe")
                            + ". Nada foi lido desse espelho.")
        if self._con is not None:
            self._con.close()
            self._con = None
        self._lids = None

    def testar(self):
        """Devolve (conversas, data da mais recente) sem falar com o WhatsApp."""
        convs = self.conversas()
        return len(convs), max((c["ultima"] for c in convs), default=None)

    def conversas(self):
        # last_message_ts vem do estado do app e pode faltar; aí vale a data da mensagem guardada.
        # kind unknown acontece com @lid ainda sem o telefone resolvido: entra se tiver mensagem.
        linhas = self.con.execute("""
            select c.jid, c.name, c.kind,
                   max(c.last_message_ts,
                       (select max(m.ts) from messages m where m.chat_jid = c.jid and m.deleted_at is null)) as ultima
            from chats c
            where c.jid != 'status@broadcast' and c.kind != 'newsletter'
              and (c.kind in ('dm', 'group') or exists (
                   select 1 from messages m where m.chat_jid = c.jid and m.deleted_at is null))""")
        por_id = {}
        for r in linhas:
            grupo = r["kind"] == "group" or r["jid"].endswith("@g.us")
            conv = {"id": r["jid"] if grupo else self._id_exposto(r["jid"]),
                    "nome": r["name"], "grupo": grupo, "ultima": r["ultima"] or 0}
            # O telefone e o @lid da mesma pessoa não podem aparecer como duas conversas.
            anterior = por_id.get(conv["id"])
            if anterior is None or conv["ultima"] > anterior["ultima"]:
                por_id[conv["id"]] = conv
        return sorted(por_id.values(), key=lambda c: c["ultima"], reverse=True)

    def mensagens(self, chat, ini=None, fim=None, ids=None):
        no_banco = tuple(self._ids_no_banco(chat))
        linhas = self.con.execute(
            """select chat_jid, msg_id, sender_jid, sender_name, ts, from_me, text, display_text, media_type,
                      media_caption, filename, mime_type, file_length, local_path, direct_path, media_unavailable_at,
                      revoked, reaction_to_id
               from messages where chat_jid in ({}) and deleted_at is null order by ts, rowid""".format(
                   ",".join("?" * len(no_banco))), no_banco)
        msgs = []
        for r in linhas:
            if r["reaction_to_id"]:
                continue  # reação não é mensagem; o texto original continua na linha dela
            m = mensagem(r, chat)
            if (ini is not None and m["data"] < ini) or (fim is not None and m["data"] >= fim):
                continue
            msgs.append(m)
        if ids:
            msgs = [m for m in msgs if m["id"] in set(ids)]
        return msgs

    def nomes(self):
        nomes = {}
        for r in self.con.execute(
                """select c.jid, a.alias, c.full_name, c.system_name, c.business_name, c.first_name, c.push_name
                   from contacts c left join contact_aliases a on a.jid = c.jid"""):
            nome = (r["alias"] or r["full_name"] or r["system_name"] or r["business_name"] or r["first_name"]
                    or ("~" + r["push_name"] if r["push_name"] else None))
            if nome:
                nomes[r["jid"]] = nomes[self._id_exposto(r["jid"])] = nome
        return nomes

    def indice_telefones(self):
        """Telefone (só dígitos) -> jids. O wacli pode guardar a conversa como @lid ou @s.whatsapp.net."""
        indice = {}
        for r in self.con.execute("select jid, phone from contacts"):
            digitos = "".join(c for c in (r["phone"] or "") if c.isdigit()) or (
                r["jid"].split("@")[0] if r["jid"].endswith("@s.whatsapp.net") else "")
            if digitos.isdigit():
                jids = {self._id_exposto(r["jid"]), digitos + "@s.whatsapp.net"}
                for v in variantes_telefone(digitos):
                    indice.setdefault(v, set()).update(j for j in jids if j)
        for pn, lid in self.lids.items():
            for v in variantes_telefone(pn):
                indice.setdefault(v, set()).add(lid + "@lid")
        return indice

    def status_midia(self, m):
        p = self.cache.arquivo(m["id"])
        if p:
            return "baixado", p
        local = m["_fonte"]["local_path"]
        if local and os.path.isfile(local):
            return "disco", local
        if m["id"] in self.cache.indisponiveis() or m["_fonte"]["indisponivel"]:
            return "indisponivel", None
        return ("baixavel" if m["_fonte"]["baixavel"] else "indisponivel"), None

    def baixar(self, m):
        local = m["_fonte"]["local_path"]
        if local and os.path.isfile(local):
            return self._copiar(local, m)
        if not m["_fonte"]["baixavel"]:
            self.cache.marcar_indisponivel(m["id"])
            raise MidiaIndisponivel("sem arquivo no espelho do wacli")
        if not self.executavel:
            raise ErroFonte("Não achei o comando `wacli` para baixar a mídia. "
                            "Instale com `brew install openclaw/tap/wacli`.")
        destino = self.cache.destino_midia(m["id"], ext_de(m))
        # O id exposto pode ser @lid; o wacli só acha a linha pelo id gravado no espelho.
        chat = m["_fonte"].get("chat_banco") or m["chat"]
        # --read-only baixa do servidor do WhatsApp sem gravar no espelho e sem marcar como lida.
        r = subprocess.run([self.executavel, "--read-only", "--store", self.store, "media", "download",
                            "--chat", chat, "--id", m["id"], "--output", destino],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not os.path.isfile(destino):
            detalhe = (r.stderr or r.stdout or f"código {r.returncode}").strip().splitlines()
            detalhe = detalhe[-1] if detalhe else "sem arquivo"
            if any(c in detalhe for c in ("403", "404", "410")):
                self.cache.marcar_indisponivel(m["id"])
                raise MidiaIndisponivel(detalhe)
            # "no rows" é id errado ou linha ausente, não prova que o áudio saiu do servidor.
            raise RuntimeError(detalhe)
        os.chmod(destino, 0o600)
        return destino

    def _copiar(self, origem, m):
        destino = self.cache.destino_midia(m["id"], ext_de(m) if m["tipo"] in MIDIA else "bin")
        shutil.copyfile(origem, destino)
        os.chmod(destino, 0o600)
        return destino


def mensagem(r, chat):
    tipo = 14 if r["revoked"] else TIPO.get(r["media_type"] or "", 0 if (r["text"] or r["display_text"]) else 10)
    texto, legenda = r["text"] or r["display_text"], None
    if tipo in (1, 2, 11, 3, 15):
        texto, legenda = None, r["media_caption"] or r["text"]
    elif tipo == 8:
        texto = r["filename"] or r["text"] or r["display_text"]
        legenda = r["media_caption"] if r["media_caption"] and r["media_caption"] != texto else None
    ts = r["ts"]
    if ts and ts > 10 ** 11:
        ts //= 1000
    return {"id": r["msg_id"], "chat": chat, "tipo": tipo, "eu": bool(r["from_me"]), "data": ts,
            "texto": texto, "legenda": legenda, "duracao": None, "tamanho": r["file_length"],
            "mime": (r["mime_type"] or "").split(";")[0] or None,
            "autor_jid": r["sender_jid"] if chat.endswith("@g.us") else None, "nome_autor": r["sender_name"],
            "data_aproximada": False,
            "_fonte": {"local_path": r["local_path"], "chat_banco": r["chat_jid"],
                       "baixavel": bool(r["direct_path"]) and not r["media_unavailable_at"],
                       "indisponivel": bool(r["media_unavailable_at"])}}


def bases_wacli():
    """Onde o wacli guarda o config. Linux novo usa o XDG; instalação antiga e os outros sistemas usam ~/.wacli."""
    if os.environ.get("WACLI_STORE_DIR"):
        return [expandir(os.environ["WACLI_STORE_DIR"])]
    xdg = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return [os.path.join(xdg, "wacli"), os.path.expanduser(PASTA_WACLI)]


def resolver_store(conta):
    """Pasta do espelho. `store` no config vale direto; senão, a conta nomeada do wacli."""
    if conta.get("store"):
        return expandir(conta["store"])
    bases = bases_wacli()
    config = next((os.path.join(b, "config.yaml") for b in bases if os.path.exists(os.path.join(b, "config.yaml"))), None)
    base = os.path.dirname(config) if config else bases[-1]
    nome = conta.get("conta_wacli")
    if config:
        padrao, contas = ler_contas(config)
        nome = nome or padrao
        if nome:
            if nome not in contas:
                raise ErroFonte(f"Conta wacli '{nome}' não está em {config}. Contas: {', '.join(contas) or 'nenhuma'}.")
            store = contas[nome]
            return store if os.path.isabs(store) else os.path.join(os.path.dirname(config), store)
    if nome:
        onde = ", ".join(os.path.join(b, "config.yaml") for b in bases)
        raise ErroFonte(f"Conta '{conta['nome']}': não achei o config do wacli ({onde}) para a conta '{nome}'. "
                        f"Informe \"store\" com a pasta do espelho, ou rode `wacli accounts add {nome}`.")
    return base


def ler_contas(caminho):
    """Lê o config.yaml do wacli (default_account e accounts.<nome>.store). Sem dependência de YAML."""
    padrao, contas, atual = None, {}, None
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            s = linha.split("#", 1)[0].rstrip()
            if not s.strip():
                continue
            indentada = s[:1].isspace()
            chave, _, valor = s.strip().partition(":")
            valor = valor.strip().strip("'\"")
            if not indentada:
                atual = chave if chave != "accounts" and not valor else None
                if chave == "default_account":
                    padrao = valor
            elif atual and chave == "store" and valor:
                contas[atual] = valor
            elif chave and not valor:
                atual = chave
    return padrao, contas

# SPDX-FileCopyrightText: 2026 Filipe (Comunidade Ratos de IA)
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
# Baseado na primeira versão de Filipe (Comunidade Ratos de IA); alterado por Leandro Garcia.
"""Fonte desktop: o banco do WhatsApp Desktop nativo do macOS.

Só leitura: tira um snapshot do ChatStorage.sqlite e nunca escreve na pasta do
WhatsApp. Fala com o servidor do WhatsApp só pra conferir (HEAD) e baixar mídia
que o app não baixou, e isso só com o ok do usuário.
"""
import base64
import hashlib
import hmac
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .modelo import MIDIA, ErroFonte, ext_de

PASTA_APP = "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared"
APPLE_EPOCH = 978307200  # ZMESSAGEDATE conta segundos desde 2001-01-01
HKDF_INFO = {1: b"WhatsApp Image Keys", 2: b"WhatsApp Video Keys", 3: b"WhatsApp Audio Keys",
             8: b"WhatsApp Document Keys", 11: b"WhatsApp Video Keys"}


class FonteDesktop:
    tipo = "desktop"

    def __init__(self, conta, cache):
        self.conta, self.cache = conta, cache
        # "pasta_whatsapp" existe para testes; no uso normal é a pasta do app.
        self.pasta = os.path.expanduser(conta.get("pasta_whatsapp") or PASTA_APP)
        if sys.platform != "darwin" and not conta.get("pasta_whatsapp"):
            raise ErroFonte("A fonte desktop só existe no macOS (WhatsApp Desktop nativo). "
                            "No Linux, use uma conta com \"fonte\": \"waha\".")
        self.banco = os.path.join(self.pasta, "ChatStorage.sqlite")
        self.contatos = os.path.join(self.pasta, "ContactsV2.sqlite")
        self.pasta_msg = os.path.join(self.pasta, "Message")
        self._con = None
        self._pks = None

    # ---------- banco ----------

    @property
    def con(self):
        if self._con is None:
            self._con = self._abrir()
        return self._con

    def _abrir(self):
        if not os.path.exists(self.banco):
            raise ErroFonte(f"Não achei o banco do WhatsApp em {self.banco}. O WhatsApp Desktop está instalado e logado?")
        self.cache.preparar()
        snapshot = os.path.join(self.cache.pasta, "ChatStorage.snapshot.sqlite")
        try:
            src = sqlite3.connect(f"file:{urllib.parse.quote(self.banco)}?mode=ro", uri=True)
            dst = sqlite3.connect(snapshot)
            src.backup(dst)
            src.close()
            dst.close()
            os.chmod(snapshot, 0o600)
        except sqlite3.Error as e:
            if not os.path.exists(snapshot):
                raise ErroFonte(f"Não consegui ler o banco do WhatsApp: {e}\n"
                                "Se for permissão, libere o app do terminal em Ajustes > Privacidade e "
                                "Segurança (Acesso Total ao Disco).")
            print(f"[aviso] não consegui atualizar o snapshot ({e}); usando o anterior.", file=sys.stderr)
        con = sqlite3.connect(snapshot)
        con.row_factory = sqlite3.Row
        return con

    def conversas(self):
        # Algumas conversas (fixadas, parece) guardam uma data-sentinela no futuro; aí vale a da última mensagem.
        agora = time.time() - APPLE_EPOCH + 86400
        rows = self.con.execute(
            """select s.Z_PK, s.ZCONTACTJID, s.ZPARTNERNAME, s.ZSESSIONTYPE,
                      case when s.ZLASTMESSAGEDATE > ?
                           then (select max(m.ZMESSAGEDATE) from ZWAMESSAGE m where m.ZCHATSESSION = s.Z_PK)
                           else s.ZLASTMESSAGEDATE end as ultima
               from ZWACHATSESSION s
               where s.ZCONTACTJID is not null and s.ZCONTACTJID != 'status@broadcast'
               order by ultima desc""", (agora,)).fetchall()
        self._pks = {r["ZCONTACTJID"]: r["Z_PK"] for r in rows}
        return [{"id": r["ZCONTACTJID"], "nome": r["ZPARTNERNAME"], "grupo": r["ZSESSIONTYPE"] == 1,
                 "ultima": r["ultima"] + APPLE_EPOCH} for r in rows if r["ultima"]]

    def mensagens(self, chat, ini=None, fim=None, ids=None):
        if self._pks is None:
            self.conversas()
        if chat not in self._pks:
            raise ErroFonte(f"Conversa {chat} não existe no app do Mac.")
        sql = """select m.Z_PK pk, m.ZSTANZAID wid, m.ZMESSAGETYPE tipo, m.ZISFROMME eu, m.ZMESSAGEDATE data,
                        m.ZTEXT texto, g.ZCONTACTNAME gnome, g.ZFIRSTNAME gfirst, g.ZMEMBERJID gjid,
                        i.ZMEDIALOCALPATH caminho, i.ZMEDIAURL url, i.ZMEDIAKEY chave, i.ZTITLE titulo,
                        i.ZMOVIEDURATION duracao, i.ZFILESIZE tamanho
                 from ZWAMESSAGE m
                 left join ZWAMEDIAITEM i on i.Z_PK = m.ZMEDIAITEM
                 left join ZWAGROUPMEMBER g on g.Z_PK = m.ZGROUPMEMBER
                 where m.ZCHATSESSION = ?"""
        par = [self._pks[chat]]
        if ini is not None:
            sql += " and m.ZMESSAGEDATE >= ?"
            par.append(ini - APPLE_EPOCH)
        if fim is not None:
            sql += " and m.ZMESSAGEDATE < ?"
            par.append(fim - APPLE_EPOCH)
        msgs = [self._mensagem(r, chat) for r in self.con.execute(sql + " order by m.ZMESSAGEDATE", par)]
        if ids:
            msgs = [m for m in msgs if m["id"] in set(ids)]
        return msgs

    @staticmethod
    def _mensagem(r, chat):
        return {"id": r["wid"] or f"pk{r['pk']}", "chat": chat, "tipo": r["tipo"], "eu": bool(r["eu"]),
                "data": r["data"] + APPLE_EPOCH, "texto": r["texto"], "legenda": r["titulo"],
                "duracao": r["duracao"], "tamanho": r["tamanho"], "mime": None,
                "autor_jid": r["gjid"], "nome_autor": r["gnome"] or decodificar_nome(r["gfirst"]),
                "data_aproximada": False,
                "_fonte": {"pk": r["pk"], "caminho": r["caminho"], "url": r["url"], "chave": r["chave"]}}

    def nomes(self):
        """jid -> nome: agenda do WhatsApp primeiro, depois o nome de perfil (~nome)."""
        nomes = {}
        try:
            for jid, nome in self.con.execute("select ZJID, ZPUSHNAME from ZWAPROFILEPUSHNAME"):
                if jid and nome:
                    nomes[jid] = "~" + nome
        except sqlite3.Error:
            pass
        for lid, wid, nome, _ in self._agenda():
            if nome:
                for jid in (lid, wid):
                    if jid:
                        nomes[jid] = nome
        return nomes

    def _agenda(self):
        try:
            src = sqlite3.connect(f"file:{urllib.parse.quote(self.contatos)}?mode=ro", uri=True)
            linhas = src.execute("select ZLID, ZWHATSAPPID, ZFULLNAME, ZPHONENUMBER from ZWAADDRESSBOOKCONTACT").fetchall()
            src.close()
            return linhas
        except sqlite3.Error:
            return []

    def indice_telefones(self):
        """Telefone (só dígitos) -> jids que a agenda associa a ele."""
        indice = {}
        for lid, wid, _, telefone in self._agenda():
            for n in {"".join(c for c in (telefone or "") if c.isdigit()), (wid or "").split("@")[0]}:
                if n.isdigit():
                    indice.setdefault(n, set()).update(j for j in (wid, lid) if j and "@" in j)
        return indice

    # ---------- mídia ----------

    def status_midia(self, m):
        """(status, caminho). status: disco | baixado | baixavel | expirado | indisponivel"""
        f = m["_fonte"]
        if f["caminho"]:
            p = os.path.join(self.pasta_msg, f["caminho"])
            if os.path.exists(p):
                return "disco", p
        p = self.cache.arquivo(m["id"])
        if p:
            return "baixado", p
        if m["id"] in self.cache.indisponiveis():
            return "indisponivel", None
        if f["url"] and f["chave"]:
            return ("baixavel" if link_valido(f["url"]) else "expirado"), None
        return "indisponivel", None

    def verificar(self, msgs):
        """Pergunta ao servidor (HEAD, sem baixar) quais mídias ainda existem. Devolve os ids vivos."""
        with ThreadPoolExecutor(8) as ex:
            vivos = ex.map(lambda m: no_servidor(m["_fonte"]["url"]), msgs)
        return {m["id"] for m, vivo in zip(msgs, vivos) if vivo}

    def baixar(self, m):
        """Baixa do servidor do WhatsApp, confere e decifra (HKDF + AES-256-CBC + HMAC)."""
        f = m["_fonte"]
        chave, sha_enc = media_key(f["chave"])
        if not chave or len(chave) != 32:
            raise RuntimeError("chave da mídia em formato desconhecido")
        exp = hkdf(chave, HKDF_INFO[m["tipo"]])
        iv, ck, mk = exp[:16], exp[16:48], exp[48:80]
        req = urllib.request.Request(f["url"], headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                enc = r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                self.cache.marcar_indisponivel(m["id"])
                from .modelo import MidiaIndisponivel
                raise MidiaIndisponivel("saiu do servidor")
            raise
        if sha_enc and len(sha_enc) == 32 and hashlib.sha256(enc).digest() != sha_enc:
            raise RuntimeError("SHA-256 do arquivo baixado não confere")
        corpo, mac = enc[:-10], enc[-10:]
        if hmac.new(mk, iv + corpo, hashlib.sha256).digest()[:10] != mac:
            raise RuntimeError("assinatura (HMAC) não confere")
        destino = self.cache.destino_midia(m["id"], ext_de(m))
        with tempfile.NamedTemporaryFile(delete=False, dir=self.cache.midia) as tmp:
            tmp.write(corpo)
        try:
            subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-K", ck.hex(), "-iv", iv.hex(),
                            "-in", tmp.name, "-out", destino], check=True, capture_output=True)
        finally:
            os.unlink(tmp.name)
        if m["tamanho"] and os.path.getsize(destino) != m["tamanho"]:
            os.unlink(destino)
            raise RuntimeError("tamanho do arquivo decifrado não confere")
        os.chmod(destino, 0o600)
        return destino


def decodificar_nome(v):
    """Alguns ZFIRSTNAME vêm como '+' + base64 de um protobuf cujo campo 1 é o nome."""
    if not v or not v.startswith("+"):
        return v
    try:
        b = base64.b64decode(v[1:] + "==")
        if b[0] == 0x0A and b[1] < 0x80:
            return b[2:2 + b[1]].decode("utf-8")
    except (ValueError, IndexError, UnicodeDecodeError):
        pass
    return None


def link_valido(url):
    try:
        oe = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("oe", [None])[0]
        return oe is not None and int(oe, 16) > time.time()
    except ValueError:
        return False


def no_servidor(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def media_key(blob):
    """O ZMEDIAKEY é um protobuf; o campo 1 (32 bytes) é a chave da mídia, o 2 é o SHA-256 do arquivo criptografado."""
    i, campos = 0, {}
    b = bytes(blob)

    def varint():
        nonlocal i
        v = s = 0
        while True:
            x = b[i]
            i += 1
            v |= (x & 0x7F) << s
            s += 7
            if x < 0x80:
                return v

    while i < len(b):
        k = varint()
        f, w = k >> 3, k & 7
        if w == 2:
            n = varint()
            campos[f] = b[i:i + n]
            i += n
        elif w == 0:
            campos[f] = varint()
        else:
            break
    return campos.get(1), campos.get(2)


def hkdf(chave, info, n=112):
    prk = hmac.new(b"\0" * 32, chave, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < n:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:n]

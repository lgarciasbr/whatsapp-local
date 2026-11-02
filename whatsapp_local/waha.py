# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Fonte waha: a API HTTP de um servidor WAHA (https://waha.devlike.pro), só com GET.

O WAHA é um aparelho vinculado ao WhatsApp rodando num servidor. Ele baixa a mídia
do WhatsApp quando pedida; a transcrição continua nesta máquina.
"""
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from .modelo import ErroFonte, MidiaIndisponivel, ext_de, variantes_telefone

# _data.type do WAHA (engine WEBJS) -> código de tipo; o resto vira evento de sistema (10)
TIPO_WAHA = {"chat": 0, "image": 1, "video": 2, "ptt": 3, "audio": 3, "vcard": 4, "multi_vcard": 4,
             "location": 5, "document": 8, "sticker": 15, "revoked": 14}


class FonteWaha:
    tipo = "waha"

    def __init__(self, conta, cache, chave):
        self.conta, self.cache = conta, cache
        if not conta.get("url"):
            raise ErroFonte(f"Conta '{conta['nome']}': falta \"url\" do servidor WAHA.")
        if not chave:
            raise ErroFonte(f"Conta '{conta['nome']}': falta a API key do WAHA. Defina "
                            f"{conta.get('api_key_env') or 'WAHA_API_KEY_' + conta['nome'].upper()} "
                            "no ambiente ou no segredos.env ao lado do config.json.")
        self.url = conta["url"].rstrip("/")
        self.chave = chave
        self.sessao = conta.get("sessao", "default")
        self.sem_data = {}  # chat -> ids que o WAHA devolveu sem data nenhuma (ficam de fora)

    # ---------- HTTP ----------

    def abrir(self, caminho_ou_url, params=None, timeout=120):
        if caminho_ou_url.startswith("http"):
            # O WAHA monta media.url com o WAHA_BASE_URL dele (às vezes localhost); vale só o caminho.
            p = urllib.parse.urlparse(caminho_ou_url)
            caminho_ou_url = p.path + ("?" + p.query if p.query else "")
        url = self.url + caminho_ou_url
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"X-Api-Key": self.chave, "Accept": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise ErroFonte(f"O WAHA em {self.url} recusou a API key (401).")
            raise
        except urllib.error.URLError as e:
            raise ErroFonte(f"Não consegui falar com o WAHA em {self.url}: {e.reason}")

    def get(self, caminho, **params):
        with self.abrir(caminho, params) as r:
            return json.load(r)

    def _chat(self, jid):
        return f"/api/{self.sessao}/chats/{urllib.parse.quote(jid, safe='')}"

    def testar(self):
        """Devolve (status da sessão, número) ou levanta ErroFonte."""
        try:
            s = self.get(f"/api/sessions/{self.sessao}")
        except urllib.error.HTTPError as e:
            raise ErroFonte(f"Sessão '{self.sessao}' não encontrada no WAHA (HTTP {e.code}).")
        return s.get("status"), ((s.get("me") or {}).get("id") or "").split("@")[0]

    # ---------- leitura ----------

    def conversas(self):
        convs, offset = [], 0
        while True:
            pagina = self.get(f"/api/{self.sessao}/chats/overview", limit=100, offset=offset)
            for c in pagina:
                ts = (c.get("lastMessage") or {}).get("timestamp")
                if c["id"] != "status@broadcast" and ts:
                    convs.append({"id": c["id"], "nome": c.get("name"), "grupo": c["id"].endswith("@g.us"), "ultima": ts})
            if len(pagina) < 100:
                break
            offset += 100
        return sorted(convs, key=lambda c: c["ultima"], reverse=True)

    def mensagens(self, chat, ini=None, fim=None, ids=None):
        brutas = self._recentes(chat, ini)
        msgs, sem_data = {}, []
        for x in brutas:
            m = mensagem(x, chat)
            if m is None:
                sem_data.append(x["id"])
                continue
            if (ini is not None and m["data"] < ini) or (fim is not None and m["data"] >= fim):
                continue  # data aproximada pode cair fora do período pedido
            msgs[m["id"]] = m
        if sem_data:
            # O engine WEBJS às vezes não sabe a data de uma mensagem, e a posição na lista também não
            # serve (pode estar meses fora do lugar). Melhor deixar de fora e avisar do que inventar.
            self.sem_data[chat] = sem_data
            qtd = "1 mensagem" if len(sem_data) == 1 else f"{len(sem_data)} mensagens"
            print(f"[aviso] o WAHA devolveu {qtd} sem data em {chat}; ficaram de fora: "
                  + ", ".join(sem_data), file=sys.stderr)
        msgs = sorted(msgs.values(), key=lambda m: m["data"])
        if ids:
            msgs = [m for m in msgs if m["id"] in set(ids)]
        return msgs

    def _recentes(self, chat, ini):
        """Mensagens da conversa até cobrir o período. O filtro de data do WAHA (WEBJS) para na
        primeira mensagem sem data e pula as anteriores, então a data é filtrada aqui. Cada página
        com offset recarrega a conversa desde o início; por isso o lote cresce em vez de paginar."""
        limite = 200
        while True:
            brutas = self.get(self._chat(chat) + "/messages", limit=limite, downloadMedia="false")
            if len(brutas) < limite or limite >= 100000:
                return brutas
            datas = [data_de(x) for x in brutas]
            if ini is not None and min((d for d in datas if d), default=ini) < ini:
                return brutas  # já passou do início do período
            limite *= 5

    def lids(self):
        """Pares {lid, pn} que o WAHA conhece (pn = telefone@c.us)."""
        return self.get(f"/api/{self.sessao}/lids", limit=100000)

    def nomes(self):
        """jid -> nome. Contato da agenda, senão ~nome de perfil; participante @lid passa pelo telefone."""
        nomes = {}
        for c in self.get("/api/contacts/all", session=self.sessao):
            nome = c.get("name") or ("~" + c["pushname"] if c.get("pushname") else None)
            if nome:
                nomes[c["id"]] = nome
        for par in self.lids():
            if par.get("pn") in nomes:
                nomes[par["lid"]] = nomes[par["pn"]]
        return nomes

    def indice_telefones(self):
        """Telefone (só dígitos) -> jids. Inclui a forma com o nono dígito."""
        indice = {}
        for par in self.lids():
            n = (par.get("pn") or "").split("@")[0]
            if n.isdigit():
                for v in variantes_telefone(n):
                    indice.setdefault(v, set()).update(j for j in (par.get("pn"), par.get("lid")) if j)
        return indice

    # ---------- mídia ----------

    def status_midia(self, m):
        p = self.cache.arquivo(m["id"])
        if p:
            return "baixado", p
        return ("indisponivel" if m["id"] in self.cache.indisponiveis() else "baixavel"), None

    def baixar(self, m):
        """Pede ao WAHA a mídia da mensagem (ele baixa do WhatsApp na hora) e grava no cache."""
        caminho = self._chat(m["chat"]) + "/messages/" + urllib.parse.quote(m["_fonte"]["waha_id"], safe="")
        midia = self.get(caminho, downloadMedia="true").get("media") or {}
        if not midia.get("url"):
            self.cache.marcar_indisponivel(m["id"])  # não pede de novo a cada sincronização
            raise MidiaIndisponivel((midia.get("error") or {}).get("details", "sem arquivo").splitlines()[0])
        destino = self.cache.destino_midia(m["id"], ext_de(m))
        with self.abrir(midia["url"]) as r, tempfile.NamedTemporaryFile(delete=False, dir=self.cache.midia) as tmp:
            shutil.copyfileobj(r, tmp)
        os.replace(tmp.name, destino)
        os.chmod(destino, 0o600)
        return destino


def data_de(x):
    """Timestamp da mensagem. Algumas mídias vêm sem data do WEBJS; aí vale a da chave da mídia,
    gerada ~1 min antes do envio. Algumas mensagens não têm data nenhuma (None). Às vezes a data
    vem em milissegundos: sempre devolve segundos."""
    d = x.get("_data") or {}
    ts = x.get("timestamp") or d.get("t") or d.get("mediaKeyTimestamp")
    return int(ts) // 1000 if ts and int(ts) > 10 ** 11 else ts


def mensagem(x, chat):
    d = x.get("_data") or {}
    tipo = TIPO_WAHA.get(d.get("type"), 10)
    if tipo == 2 and d.get("isGif"):
        tipo = 11
    corpo = x.get("body") or None
    texto, legenda = corpo, None
    if tipo in (1, 2, 11):  # como no app do Mac, legenda de imagem e vídeo não é texto
        texto, legenda = None, d.get("caption") or corpo
    elif tipo == 8:
        texto = d.get("filename") or corpo
        legenda = d.get("caption") if d.get("caption") != texto else None
    elif tipo == 3:
        texto = None
    # id: {fromMe}_{chat}_{id da mensagem}[_{participante}]; o do meio é o mesmo ZSTANZAID do Mac
    partes = x["id"].split("_")
    wid = partes[2] if len(partes) > 2 else x["id"]
    try:
        duracao = int(float(d.get("duration") or 0)) or None
    except ValueError:
        duracao = None
    ts = data_de(x)
    if not ts:
        return None
    aproximada = not (x.get("timestamp") or d.get("t"))
    mime = ((x.get("media") or {}).get("mimetype") or d.get("mimetype") or "").split(";")[0]
    return {"id": wid, "chat": chat, "tipo": tipo, "eu": bool(x.get("fromMe")), "data": ts,
            "texto": texto, "legenda": legenda, "duracao": duracao, "tamanho": d.get("size"), "mime": mime,
            "autor_jid": x.get("participant") if chat.endswith("@g.us") else None, "nome_autor": None,
            "data_aproximada": aproximada, "_fonte": {"waha_id": x["id"]}}

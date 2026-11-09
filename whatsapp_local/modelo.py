# SPDX-FileCopyrightText: 2026 Filipe (Comunidade Ratos de IA)
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
# Baseado na primeira versão de Filipe (Comunidade Ratos de IA); alterado por Leandro Garcia.
"""Tipos de mensagem e funções comuns às fontes.

As fontes (app do Mac, WAHA e wacli) devolvem mensagens no mesmo formato:

    {"id": id da mensagem no WhatsApp (igual nas duas fontes), "chat": id da conversa,
     "tipo": código abaixo, "eu": bool, "data": timestamp Unix, "texto", "legenda",
     "duracao", "tamanho", "mime", "autor_jid", "nome_autor", "data_aproximada", "_fonte": {...}}

e conversas como {"id", "nome", "grupo": bool, "ultima": timestamp Unix}.
"""
import unicodedata
from datetime import datetime

# Código do tipo (o ZMESSAGETYPE do app do Mac) -> (categoria, rótulo, extensão padrão)
MIDIA = {
    1: ("imagem", "imagem", "jpg"),
    2: ("video", "vídeo", "mp4"),
    3: ("audio", "áudio", "opus"),
    8: ("documento", "documento", "bin"),
    11: ("video", "gif", "mp4"),
}
TEXTO = {0, 7}  # texto e link
CONTATO, LOCALIZACAO, FIGURINHA, APAGADA = 4, 5, 15, 14
SISTEMA = {6, 10, 14, 66}  # eventos de grupo, avisos e mensagens apagadas
CATEGORIAS = ["audio", "video", "imagem", "documento"]
ROTULO_CAT = {"audio": "áudios", "video": "vídeos", "imagem": "imagens", "documento": "documentos"}
EXT_MIME = {"audio/ogg": "opus", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
            "video/mp4": "mp4", "application/pdf": "pdf"}


class ErroFonte(Exception):
    """Problema que o usuário precisa resolver (configuração, permissão, servidor fora)."""


class Ambigua(ErroFonte):
    def __init__(self, alvo, opcoes):
        self.opcoes = opcoes
        linhas = "\n".join(f"  {fmt_data(c['ultima'])}  {c['nome'] or '?'}  {c['id']}" for c in opcoes[:20])
        super().__init__(f"Mais de uma conversa bate com '{alvo}'. Use o id:\n{linhas}")


class MidiaIndisponivel(Exception):
    """A mídia saiu do servidor do WhatsApp; só volta se o contato reenviar."""


def sem_acento(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def fmt_data(ts, com_hora=False):
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M" if com_hora else "%Y-%m-%d")


def mmss(s):
    s = int(s or 0)
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def numero(jid):
    return (jid or "?").split("@")[0]


def variantes_telefone(digitos):
    """O mesmo celular brasileiro com e sem o nono dígito: o WhatsApp de contas antigas
    guarda sem o 9 e a agenda (ou o CRM) costuma guardar com ele."""
    if not digitos:
        return set()
    v = {digitos}
    if len(digitos) == 13 and digitos.startswith("55") and digitos[4] == "9":
        v.add(digitos[:4] + digitos[5:])
    elif len(digitos) == 12 and digitos.startswith("55"):
        v.add(digitos[:4] + "9" + digitos[4:])
    return v


def normalizar_telefone(texto, ddi="55"):
    """Só dígitos, com o código do país. Sem "+" e com 10 ou 11 dígitos (DDD + número), vale o
    país padrão; com "+" o país já está explícito e o número fica como está."""
    digitos = "".join(c for c in (texto or "") if c.isdigit())
    if digitos and not (texto or "").strip().startswith("+") and len(digitos) in (10, 11):
        return (ddi or "") + digitos
    return digitos


def formatar_telefone(digitos):
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        return f"+55 {digitos[2:4]} {digitos[4:-4]}-{digitos[-4:]}"
    return "+" + digitos if digitos else ""


def resolver_conversa(convs, alvo, ddi="55"):
    """Acha uma conversa por id, número ou nome. Nome só vale se for inequívoco."""
    if "@" in alvo:
        achou = [c for c in convs if c["id"] == alvo]
    elif alvo.lstrip("+").isdigit():
        dig = variantes_telefone(normalizar_telefone(alvo, ddi)) | {alvo.lstrip("+")}
        achou = [c for c in convs if not c["grupo"] and numero(c["id"]) in dig]
        if not achou:  # número parcial
            achou = [c for c in convs if any(d in c["id"] for d in dig)]
    else:
        q = sem_acento(alvo)
        achou = [c for c in convs if q in sem_acento(c["nome"])]
        exatos = [c for c in achou if sem_acento(c["nome"]) == q]
        if len(exatos) == 1:
            achou = exatos
    if not achou:
        raise ErroFonte(f"Nenhuma conversa bate com '{alvo}'. Use `wa conversas --busca` pra procurar.")
    if len(achou) > 1:
        raise Ambigua(alvo, achou)
    return achou[0]


def autor(m, conv, nomes):
    if m["eu"]:
        return "Eu"
    if conv["grupo"]:
        return nomes.get(m["autor_jid"]) or m.get("nome_autor") or numero(m["autor_jid"])
    return conv["nome"] or numero(conv["id"])


def ext_de(m):
    cat, _, ext = MIDIA[m["tipo"]]
    if cat == "documento":
        nome = m["texto"] or m["legenda"] or ""
        if "." in nome[-6:]:
            return nome.rsplit(".", 1)[1].lower()
    return EXT_MIME.get(m.get("mime"), ext)

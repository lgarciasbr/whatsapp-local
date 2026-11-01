# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Exporta uma conversa para uma pasta: transcript em Markdown, Anexos/ e Mensagens.json.

O Mensagens.json guarda tudo o que já foi exportado. Cada exportação junta as mensagens
novas com as anteriores pelo id da mensagem no WhatsApp, sem apagar o histórico, mesmo
que ele tenha sumido da fonte. Por isso basta exportar uma janela recente.
"""
import datetime
import json
import os
import re
import shutil

from .modelo import CONTATO, LOCALIZACAO, SISTEMA

ROTULO = {"audio": "áudio", "video": "vídeo", "imagem": "imagem", "documento": "documento"}


class ErroExportacao(Exception):
    pass


def limpa_nome(t):
    return re.sub(r'[\\/:*?"<>|#^\[\]]', "-", t).strip()


def pasta_padrao(nome, grupo):
    return ("Grupo " if grupo else "Privado - ") + nome


def titulo_padrao(nome, grupo):
    return ("Grupo " if grupo else "Conversa privada com ") + nome


def _dur(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


def _br(data):
    d, h = data.split(" ")
    a, m, dia = d.split("-")
    return f"{dia}/{m}/{a}", h


def _citar(texto):
    return "\n".join("> " + l if l else ">" for l in texto.strip().splitlines())


def _chave(m):
    # Registros antigos (versões anteriores) podem ter só o id local do app do Mac.
    return m.get("wid") or m["id"]


def exportar(registros, jid, base, pasta, titulo):
    """registros: saída de operacoes.registros(). Devolve um resumo ou None se não houve mensagens."""
    msgs = [m for m in registros if m["tipo"] not in SISTEMA]
    pasta, titulo = limpa_nome(pasta), limpa_nome(titulo)
    destino = os.path.join(os.path.abspath(os.path.expanduser(base)), pasta)
    anexos = os.path.join(destino, "Anexos")
    arquivo_dados = os.path.join(destino, "Mensagens.json")
    arquivo_md = os.path.join(destino, f"Transcript - {titulo}.md")
    if os.path.exists(arquivo_md) and not os.path.exists(arquivo_dados):
        raise ErroExportacao(f"{arquivo_md} existe sem Mensagens.json: migre e confira o histórico antes "
                             "de atualizar. Nada foi sobrescrito.")
    anteriores = []
    if os.path.exists(arquivo_dados):
        with open(arquivo_dados, encoding="utf-8") as f:
            anteriores = json.load(f)
    if anteriores and any(m.get("conversa_jid") != jid for m in anteriores):
        raise ErroExportacao(f"{destino} pertence a outra conversa. Confira o id e o nome.")

    por_id = {_chave(m): m for m in anteriores}
    for m in msgs:
        antigo = por_id.get(_chave(m), {})
        for campo in ("transcricao", "arquivo", "anexo_exportado"):
            if not m.get(campo) and antigo.get(campo):
                m[campo] = antigo[campo]
        m.pop("data_aproximada", None)
        if antigo.get("data"):
            # Mantém a data já exportada: as fontes divergem por segundos (às vezes viram 1 minuto)
            # e o WAHA às vezes só tem a hora aproximada.
            m["data"] = antigo["data"]
        m["conversa_jid"] = jid
        por_id[_chave(m)] = m
    msgs = sorted(por_id.values(), key=lambda m: m["data"])
    if not msgs:
        return None
    os.makedirs(destino, exist_ok=True)

    cont = {"mensagens": len(msgs), "audios": 0, "transcritos": 0, "indisponiveis": 0, "anexos": 0}
    linhas, dia_atual = [], None
    for m in msgs:
        dia, hora = _br(m["data"])
        if dia != dia_atual:
            linhas.append(f"\n## {dia}\n")
            dia_atual = dia
        cab = f"**{hora} · {m['autor']}:**"
        midia = m.get("midia")
        if not midia:
            if m["tipo"] == CONTATO:
                corpo = "_[contato compartilhado]_"
            elif m["tipo"] == LOCALIZACAO:
                corpo = "_[localização]_"
            else:
                corpo = (m.get("texto") or "").strip() or "_[mensagem sem texto]_"
            linhas.append(f"{cab} {corpo}\n")
            continue

        rot = ROTULO.get(midia, midia)
        info = f"{rot}, {_dur(m['duracao'])}" if midia in ("audio", "video") else rot
        if midia == "audio":
            cont["audios"] += 1
        partes = [f"{cab} 📎 _[{info}]_"]
        if midia == "documento" and m.get("texto"):
            partes[0] += f" {m['texto']}"

        arq = m.get("arquivo")
        if m.get("anexo_exportado") and os.path.isfile(os.path.join(anexos, m["anexo_exportado"])):
            # Já exportado (talvez com o nome de uma versão anterior): não duplica o arquivo.
            partes.append(f"![[{m['anexo_exportado']}]]")
            cont["anexos"] += 1
        elif arq and os.path.exists(arq):
            ext = os.path.splitext(arq)[1].lower()
            if ext == ".opus":
                ext = ".ogg"  # opus do WhatsApp é ogg; o Obsidian toca .ogg
            if midia == "documento" and m.get("texto"):
                nome = f"{m['data'][:10]} - {m['id']} - {limpa_nome(m['texto'])}"
                if not nome.lower().endswith(ext):
                    nome += ext
            else:
                nome = f"{m['data'][:10]} - {m['id']}{ext}"
            os.makedirs(anexos, exist_ok=True)
            shutil.copy2(arq, os.path.join(anexos, nome))
            cont["anexos"] += 1
            m["anexo_exportado"] = nome
            partes.append(f"![[{nome}]]")
        elif midia in ("audio", "video"):
            partes.append("_(arquivo indisponível nesta exportação)_")
            if midia == "audio":
                cont["indisponiveis"] += 1
        else:
            partes.append("_(arquivo indisponível)_")

        if m.get("legenda"):
            partes.append(f"Legenda: {m['legenda'].strip()}")
        if m.get("transcricao"):
            partes.append("Transcrição automática:\n" + _citar(m["transcricao"]))
            if midia == "audio":
                cont["transcritos"] += 1
        linhas.append("\n".join(partes) + "\n")

    inicio, fim = _br(msgs[0]["data"])[0], _br(msgs[-1]["data"])[0]
    topo = [f"# {titulo}", "",
            f"Transcript do WhatsApp de {inicio} a {fim}, gerado em {datetime.date.today():%d/%m/%Y}: {len(msgs)} mensagens."]
    if cont["audios"]:
        topo.append(f"Áudios: {cont['audios']} no total, {cont['transcritos']} transcritos e "
                    f"{cont['indisponiveis']} indisponíveis nesta exportação.")
    topo += ["",
             "As transcrições são automáticas (whisper.cpp, local) e podem errar nomes próprios e números: "
             "confira no áudio antes de usar um valor.",
             "O WhatsApp só tem o histórico sincronizado quando o aparelho foi vinculado; mensagens mais antigas podem faltar."]
    for caminho, conteudo in [(arquivo_dados, json.dumps(msgs, ensure_ascii=False, indent=2)),
                              (arquivo_md, "\n".join(topo) + "\n" + "\n".join(linhas))]:
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                anterior = f.read()
            # A data de geração não é mudança na conversa.
            normalizar = lambda s: re.sub(r"gerado em \d{2}/\d{2}/\d{4}:", "gerado em:", s)
            if normalizar(anterior) == normalizar(conteudo):
                continue
            shutil.copy2(caminho, caminho + ".bak")
        temporario = caminho + ".tmp"
        with open(temporario, "w", encoding="utf-8") as f:
            f.write(conteudo)
        os.replace(temporario, caminho)
    cont["pasta"] = destino
    return cont

# SPDX-FileCopyrightText: 2026 Filipe (Comunidade Ratos de IA)
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
# Baseado na primeira versão de Filipe (Comunidade Ratos de IA); alterado por Leandro Garcia.
"""Operações sobre mensagens, comuns ao comando `wa` e ao sync."""
import time
import urllib.error

from . import transcricao
from .modelo import MIDIA, MidiaIndisponivel, autor, fmt_data, mmss


def com_midia(msgs, tipos=None):
    return [m for m in msgs if m["tipo"] in MIDIA and (not tipos or MIDIA[m["tipo"]][0] in tipos)]


def baixar(fonte, msgs, log=print):
    """Baixa o que falta. Devolve (baixados, já existiam, sem como baixar)."""
    ok = pulou = falhou = 0
    for m in msgs:
        st, _ = fonte.status_midia(m)
        rot = MIDIA[m["tipo"]][1]
        quando = fmt_data(m["data"], True)
        if st in ("disco", "baixado"):
            pulou += 1
            continue
        if st != "baixavel":
            log(f"#{m['id']} {rot} {quando}: " + ("link vencido" if st == "expirado" else "saiu do servidor")
                + ", só pedindo reenvio pelo app")
            falhou += 1
            continue
        try:
            log(f"#{m['id']} {rot} {quando}: ok -> {fonte.baixar(m)}")
            ok += 1
        except MidiaIndisponivel:
            log(f"#{m['id']} {rot} {quando}: saiu do servidor, só pedindo reenvio pelo app")
            falhou += 1
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, OSError) as e:
            log(f"#{m['id']} {rot} {quando}: falhou ({e})")
            falhou += 1
    return ok, pulou, falhou


def transcrever(fonte, msgs, conf, idioma=None, refazer=False, log=print):
    """Transcreve áudio e vídeo. Pelo WAHA, baixar faz parte de transcrever (o arquivo vem do
    servidor do próprio usuário); no app do Mac, só o que já está no disco ou no cache."""
    feitos = cache = sem_arquivo = falhas = 0
    for m in com_midia(msgs, ("audio", "video")):
        if fonte.cache.transcricao(m["id"]) is not None and not refazer:
            cache += 1
            continue
        st, p = fonte.status_midia(m)
        if not p and st == "baixavel" and fonte.tipo == "waha":
            try:
                p = fonte.baixar(m)
            except (MidiaIndisponivel, urllib.error.HTTPError, urllib.error.URLError, OSError):
                p = None
        if not p:
            sem_arquivo += 1
            continue
        try:
            t0 = time.time()
            texto = transcricao.transcrever(p, conf, idioma)
            fonte.cache.salvar_transcricao(m["id"], texto)
            feitos += 1
            log(f"#{m['id']} {MIDIA[m['tipo']][1]} {mmss(m['duracao'])} ({time.time() - t0:.0f}s): {texto[:120]}")
        except Exception as e:
            falhas += 1
            log(f"#{m['id']} {MIDIA[m['tipo']][1]}: falhou ({e})")
    return feitos, cache, sem_arquivo, falhas


def registros(fonte, conv, msgs, nomes):
    """Mensagens no formato do `wa mensagens --json` e do Mensagens.json exportado."""
    out = []
    for m in msgs:
        d = {"id": m["id"], "wid": m["id"], "data": fmt_data(m["data"], True), "autor": autor(m, conv, nomes),
             "tipo": m["tipo"], "texto": m["texto"]}
        if m.get("data_aproximada"):
            d["data_aproximada"] = True
        if m["tipo"] in MIDIA:
            st, p = fonte.status_midia(m)
            d.update({"midia": MIDIA[m["tipo"]][0], "status": st, "arquivo": p, "legenda": m["legenda"],
                      "duracao": m["duracao"], "transcricao": fonte.cache.transcricao(m["id"])})
        out.append(d)
    return out

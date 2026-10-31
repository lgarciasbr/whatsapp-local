# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Sincronização: mantém conversas escolhidas exportadas e transcritas numa pasta.

No config.json:

    "sync": {
      "dias": 30,                        janela lida a cada execução (o histórico fica no Mensagens.json)
      "destino": "~/WhatsApp",           pasta padrão das exportações
      "baixar_midia_desktop": false,     no app do Mac, baixar do servidor o que o app não baixou
      "conversas": [
        {"conversa": "Maria Silva"},                       nome, número, id ou nome do grupo
        {"conversa": "Equipe Projeto X", "conta": "trabalho", "destino": "~/Notas/Projeto X"}
      ],
      "obsidian_crm": {...}              ver obsidian_crm.py
    }

Um nome só é aceito se bater com uma única conversa; o id encontrado fica gravado em
<dados>/sync-estado.json e passa a ser usado nas próximas vezes, mesmo que o nome mude.
"""
import json
import os
import time

from . import exportar, obsidian_crm, operacoes
from .cache import pasta_privada
from .config import abrir_fonte, expandir
from .modelo import ErroFonte, resolver_conversa
from .trava import trava


class Contexto:
    """Abre cada conta uma vez e guarda conversas e nomes durante a sincronização."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._fontes, self._convs, self._nomes = {}, {}, {}

    def fonte(self, conta):
        conta = conta or self.cfg.conta_padrao
        if conta not in self._fontes:
            self._fontes[conta] = abrir_fonte(self.cfg, conta)
        return self._fontes[conta]

    def conversas(self, conta):
        conta = conta or self.cfg.conta_padrao
        if conta not in self._convs:
            self._convs[conta] = self.fonte(conta).conversas()
        return self._convs[conta]

    def nomes(self, conta):
        conta = conta or self.cfg.conta_padrao
        if conta not in self._nomes:
            self._nomes[conta] = self.fonte(conta).nomes()
        return self._nomes[conta]


class Estado:
    def __init__(self, pasta):
        self.arquivo = os.path.join(pasta, "sync-estado.json")
        self.ids = {}
        if os.path.exists(self.arquivo):
            with open(self.arquivo, encoding="utf-8") as f:
                self.ids = json.load(f).get("ids", {})

    def salvar(self):
        pasta_privada(os.path.dirname(self.arquivo))
        fd = os.open(self.arquivo + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"ids": self.ids}, f, ensure_ascii=False, indent=2)
        os.replace(self.arquivo + ".tmp", self.arquivo)


def resolver(ctx, estado, conta, alvo):
    convs = ctx.conversas(conta)
    chave = f"{conta or ctx.cfg.conta_padrao}|{alvo}"
    fixado = estado.ids.get(chave)
    if fixado:
        achou = [c for c in convs if c["id"] == fixado]
        if achou:
            return achou[0]
        return {"id": fixado, "nome": alvo, "grupo": fixado.endswith("@g.us"), "ultima": None}
    conv = resolver_conversa(convs, alvo)
    if "@" not in alvo:
        estado.ids[chave] = conv["id"]
    return conv


def processar(ctx, conta, conv, base, pasta, nome, dias, log=print):
    """Baixa (WAHA), transcreve e exporta uma conversa. Na primeira exportação (pasta sem
    Mensagens.json), lê o histórico inteiro; depois, só a janela de `dias`."""
    cfg = ctx.cfg
    fonte = ctx.fonte(conta)
    nome = nome or conv["nome"] or conv["id"].split("@")[0]
    pasta = pasta or exportar.pasta_padrao(nome, conv["grupo"])
    primeira = not os.path.exists(os.path.join(base, exportar.limpa_nome(pasta), "Mensagens.json"))
    msgs = fonte.mensagens(conv["id"], None if primeira else time.time() - dias * 86400)
    if fonte.tipo == "waha" or cfg.sync.get("baixar_midia_desktop"):
        operacoes.baixar(fonte, operacoes.com_midia(msgs), log=lambda *_: None)
    operacoes.transcrever(fonte, msgs, cfg.whisper, log=lambda *_: None)
    regs = operacoes.registros(fonte, conv, msgs, ctx.nomes(conta))
    r = exportar.exportar(regs, conv["id"], base, pasta, exportar.titulo_padrao(nome, conv["grupo"]))
    if r is not None:
        r["sem_data"] = len(getattr(fonte, "sem_data", {}).get(conv["id"], []))
        r["primeira"] = primeira
    return r


def plural(n, um, varios):
    return f"{n} {um if n == 1 else varios}"


def aviso_sem_data(r):
    if r and r.get("sem_data"):
        n = r["sem_data"]
        return (f" {n} {'mensagem veio' if n == 1 else 'mensagens vieram'} do WAHA sem data e "
                f"{'ficou' if n == 1 else 'ficaram'} de fora (limitação do engine WEBJS; o app do Mac tem a data).")
    return ""


def executar(cfg, log=print):
    with trava(os.path.join(cfg.pasta_dados, "sync.lock")):
        return _executar(cfg, log)


def _executar(cfg, log):
    conf = cfg.sync
    dias = int(conf.get("dias") or 30)
    ctx, estado = Contexto(cfg), Estado(cfg.pasta_dados)
    resultados = []

    for item in conf.get("conversas") or []:
        alvo, conta = item["conversa"], item.get("conta")
        rotulo = f"{alvo} ({conta or cfg.conta_padrao})"
        try:
            conv = resolver(ctx, estado, conta, alvo)
            base = expandir(item.get("destino") or conf.get("destino") or os.path.join(cfg.pasta_dados, "exportacoes"))
            r = processar(ctx, conta, conv, base, item.get("pasta"), item.get("nome"), dias, log)
            resultados.append(("ok", rotulo, (f"{plural(r['mensagens'], 'mensagem', 'mensagens')} em {r['pasta']}."
                                              if r else "sem mensagens.")
                               + aviso_sem_data(r)))
        except (ErroFonte, exportar.ErroExportacao) as e:
            resultados.append(("erro", rotulo, str(e)))
        except Exception as e:  # uma conversa com problema não para as outras
            resultados.append(("erro", rotulo, f"{type(e).__name__}: {e}"))

    if conf.get("obsidian_crm"):
        try:
            resultados += obsidian_crm.sincronizar(ctx, estado, conf["obsidian_crm"], dias, resolver, processar,
                                                   aviso_sem_data, log)
        except ErroFonte as e:
            resultados.append(("erro", "Obsidian CRM", str(e)))

    estado.salvar()
    rotulos = {"ok": "OK", "erro": "ERRO", "pendente": "Pendente"}
    for tipo, rotulo, msg in resultados:
        log(f"{rotulos[tipo]} · {rotulo}: {msg}")
    return resultados

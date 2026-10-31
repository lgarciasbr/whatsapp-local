# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Integração com o plugin Obsidian CRM: https://github.com/lgarciasbr/obsidian-crm

Para cada pessoa do CRM (nota com `type: crm/person`, conforme o contrato de dados do
plugin), acha a conversa pelo `phone` e exporta para <pasta do CRM>/WhatsApp/People/<nome>/.
Grupos escolhidos vão para <pasta do CRM>/WhatsApp/Group/<nome>/. A pasta do CRM vem das
configurações do plugin (`crmRoot`).

Só lê as notas do CRM: escreve apenas dentro de <pasta do CRM>/WhatsApp/.

No config.json, dentro de "sync":

    "obsidian_crm": {
      "vault": "~/Obsidian/Meu Vault",
      "conta": "trabalho",                     opcional; senão, a conta padrão
      "pasta_crm": "CRM",                      opcional; senão, a do plugin
      "pessoas": {"Maria Silva": "5511999999999@c.us"},   confirmações quando o telefone não basta
      "grupos": [{"conversa": "Equipe Projeto X", "nome": "Projeto X"}]
    }

Uma pessoa só é associada por telefone quando ele leva a uma única conversa. Nunca por nome.
"""
import datetime
import json
import os
import re

from .config import expandir
from .modelo import ErroFonte, numero, variantes_telefone

PLUGIN = "https://github.com/lgarciasbr/obsidian-crm"


def pasta_crm(conf):
    vault = expandir(conf["vault"])
    if not os.path.isdir(vault):
        raise ErroFonte(f"Vault do Obsidian não encontrado: {vault}")
    raiz = conf.get("pasta_crm")
    if not raiz:
        dados = os.path.join(vault, ".obsidian", "plugins", "crm", "data.json")
        if os.path.exists(dados):
            with open(dados, encoding="utf-8") as f:
                raiz = json.load(f).get("crmRoot")
    return os.path.join(vault, raiz or "CRM")  # "CRM" é o padrão do plugin


def campo(texto, chave):
    """Valor de um campo simples do frontmatter YAML."""
    partes = texto.split("---", 2)
    if len(partes) < 3 or partes[0].strip():
        return ""
    m = re.search(r"^" + re.escape(chave) + r":\s*(.*?)\s*$", partes[1], re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def pessoas(crm):
    pasta = os.path.join(crm, "People")
    if not os.path.isdir(pasta):
        raise ErroFonte(f"Pasta People/ do CRM não encontrada em {crm}. O vault está sincronizado? ({PLUGIN})")
    for nome in sorted(os.listdir(pasta)):
        if nome.endswith(".md"):
            with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                texto = f.read()
            if campo(texto, "type") == "crm/person":
                yield nome[:-3], re.sub(r"\D", "", campo(texto, "phone"))


def conversa_da_pessoa(convs, indice, telefone):
    """Conversas privadas ligadas ao telefone (com e sem o nono dígito)."""
    jids = set()
    variantes = variantes_telefone(telefone)
    for v in variantes:
        jids |= indice.get(v, set())
    return [c for c in convs if not c["grupo"] and (c["id"] in jids or numero(c["id"]) in variantes)]


def sincronizar(ctx, estado, conf, dias, resolver, processar, aviso, log=print):
    conta = conf.get("conta")
    crm = pasta_crm(conf)
    destino = os.path.join(crm, "WhatsApp")
    fonte = ctx.fonte(conta)
    convs = ctx.conversas(conta)
    indice = fonte.indice_telefones()
    confirmadas = conf.get("pessoas") or {}
    resultados, usados = [], set()

    for nome, telefone in pessoas(crm):
        vinculo = confirmadas.get(nome)
        if isinstance(vinculo, dict):  # formato antigo: {"jid": ..., "nome_whatsapp": ...}
            vinculo = vinculo.get("jid")
        rotulo = f"People/{nome}"
        if vinculo:
            conv = next((c for c in convs if c["id"] == vinculo), None) or \
                {"id": vinculo, "nome": nome, "grupo": False, "ultima": None}
        else:
            achou = conversa_da_pessoa(convs, indice, telefone)
            if len(achou) != 1:
                motivo = ("telefone não preenchido no CRM" if not telefone else
                          "mais de uma conversa associada ao telefone" if achou else
                          "nenhuma conversa associada ao telefone do CRM")
                resultados.append(("pendente", rotulo, motivo + ". Nenhuma associação por nome foi feita."))
                continue
            conv = achou[0]
        if conv["id"] in usados:
            resultados.append(("pendente", rotulo, "conversa já associada a outra pessoa; conferir duplicidade."))
            continue
        usados.add(conv["id"])
        resultados.append(_processar(ctx, conta, conv, destino, "People", nome, dias, processar, aviso, log, rotulo))

    for grupo in conf.get("grupos") or []:
        alvo = grupo.get("conversa") or grupo.get("jid")
        nome = grupo.get("nome") or alvo
        rotulo = f"Group/{nome}"
        try:
            conv = resolver(ctx, estado, conta, alvo)
        except ErroFonte as e:
            resultados.append(("erro", rotulo, str(e)))
            continue
        resultados.append(_processar(ctx, conta, conv, destino, "Group", nome, dias, processar, aviso, log, rotulo))

    _nota_status(destino, ctx.fonte(conta), resultados)
    return resultados


def _processar(ctx, conta, conv, destino, tipo, pasta, dias, processar, aviso, log, rotulo):
    try:
        r = processar(ctx, conta, conv, os.path.join(destino, tipo), pasta, conv.get("nome") or pasta, dias, log)
        return ("ok", rotulo, "atualizado." + aviso(r))
    except Exception as e:  # uma conversa com problema não para as outras
        return ("erro", rotulo, str(e)[:1000])


def _nota_status(destino, fonte, resultados):
    os.makedirs(destino, exist_ok=True)
    origem = (f"WAHA (sessão {fonte.sessao})" if fonte.tipo == "waha" else "WhatsApp Desktop do Mac")
    rotulos = {"ok": "OK", "erro": "Erro", "pendente": "Pendente"}
    ordem = {"pendente": 0, "erro": 1, "ok": 2}
    linhas = [f"- {rotulos[t]} · {r}: {m}" for t, r, m in sorted(resultados, key=lambda x: (ordem[x[0]], x[1]))]
    conteudo = (f"# Status da sincronização do WhatsApp\n\nÚltima execução: "
                f"{datetime.datetime.now():%d/%m/%Y %H:%M:%S}\n\nFonte: {origem}. Transcrição local (whisper.cpp). "
                f"Gerado por whatsapp-local para o Obsidian CRM ({PLUGIN}).\n\n" + "\n".join(linhas) + "\n")
    nota = os.path.join(destino, "Status da sincronização.md")
    with open(nota + ".tmp", "w", encoding="utf-8") as f:
        f.write(conteudo)
    os.replace(nota + ".tmp", nota)

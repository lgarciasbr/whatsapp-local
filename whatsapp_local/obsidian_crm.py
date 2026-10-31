# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Integração com o plugin Obsidian CRM: https://github.com/lgarciasbr/obsidian-crm

Para cada pessoa do CRM (nota com `type: crm/person`, conforme o contrato de dados do
plugin), procura a conversa pelo `phone` em cada conta configurada e exporta para
<pasta do CRM>/WhatsApp/People/<nome>/. Grupos escolhidos vão para Group/<nome>/. A pasta
do CRM vem das configurações do plugin (`crmRoot`).

Telefone sem "+" e com 10 ou 11 dígitos ganha o país padrão (55). Uma conversa por pasta:
na primeira conta, a pasta é <nome>; nas outras, <nome> (<conta>). Se a mesma conta tiver
outra conversa da pessoa (um número antigo confirmado e o do CRM, por exemplo), a extra
leva o número: <nome> (+55 11 91234-5678).

Só lê as notas do CRM: escreve apenas dentro de <pasta do CRM>/WhatsApp/.

No config.json, dentro de "sync":

    "obsidian_crm": {
      "vault": "~/Obsidian/Meu Vault",
      "contas": ["trabalho", "pessoal"],       onde procurar, a primeira é a principal (padrão: a conta padrão)
      "ddi_padrao": "55",                      país de telefones sem "+" (padrão: 55)
      "pasta_crm": "CRM",                      opcional; senão, a do plugin
      "pessoas": {"Maria Silva": "5511999999999@c.us"},   confirmações quando o telefone não basta
      "grupos": [{"conversa": "Equipe Projeto X", "nome": "Projeto X"}]
    }

Numa conta, uma pessoa só é associada por telefone quando ele leva a uma única conversa.
Nunca por nome.
"""
import datetime
import json
import os
import re

from .config import expandir
from .modelo import ErroFonte, formatar_telefone, normalizar_telefone, numero, variantes_telefone

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


def pessoas(crm, ddi="55"):
    pasta = os.path.join(crm, "People")
    if not os.path.isdir(pasta):
        raise ErroFonte(f"Pasta People/ do CRM não encontrada em {crm}. O vault está sincronizado? ({PLUGIN})")
    for nome in sorted(os.listdir(pasta)):
        if nome.endswith(".md"):
            with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                texto = f.read()
            if campo(texto, "type") == "crm/person":
                yield nome[:-3], normalizar_telefone(campo(texto, "phone"), ddi)


def conversa_da_pessoa(convs, indice, telefone):
    """Conversas privadas ligadas ao telefone (com e sem o nono dígito)."""
    jids = set()
    variantes = variantes_telefone(telefone)
    for v in variantes:
        jids |= indice.get(v, set())
    return [c for c in convs if not c["grupo"] and (c["id"] in jids or numero(c["id"]) in variantes)]


def contas_crm(ctx, conf):
    contas = conf.get("contas") or [conf.get("conta") or ctx.cfg.conta_padrao]
    return [c for c in contas if c]


def sincronizar(ctx, estado, conf, dias, resolver, processar, aviso, log=print):
    contas = contas_crm(ctx, conf)
    crm = pasta_crm(conf)
    destino = os.path.join(crm, "WhatsApp")
    dados = {}
    for conta in contas:
        try:
            dados[conta] = (ctx.conversas(conta), ctx.fonte(conta).indice_telefones())
        except ErroFonte as e:
            log(f"[aviso] conta {conta} indisponível: {e}")
    confirmadas = conf.get("pessoas") or {}
    resultados, usados = [], set()

    for nome, telefone in pessoas(crm, conf.get("ddi_padrao", "55")):
        vinculo = confirmadas.get(nome)
        if isinstance(vinculo, dict):  # formato antigo: {"jid": ..., "nome_whatsapp": ...}
            vinculo = vinculo.get("jid")
        achadas, avisos = [], []
        for conta in contas:
            if conta not in dados:
                continue
            convs, indice = dados[conta]
            na_conta = []
            if vinculo:
                na_conta += [c for c in convs if c["id"] == vinculo]
            if telefone:
                por_tel = conversa_da_pessoa(convs, indice, telefone)
                if len(por_tel) > 1:
                    avisos.append(f"mais de uma conversa associada ao telefone na conta {conta}")
                else:
                    na_conta += [c for c in por_tel if c["id"] not in {x["id"] for x in na_conta}]
            for i, conv in enumerate(na_conta):
                partes = ([] if conta == contas[0] else [conta]) + ([] if i == 0 else [formatar_telefone(numero_de(conv, telefone))])
                achadas.append((conta, conv, nome + (f" ({', '.join(partes)})" if partes else "")))
        if not achadas:
            motivo = ("; ".join(avisos) if avisos else "telefone não preenchido no CRM" if not telefone
                      else f"nenhuma conversa com o telefone do CRM em {', '.join(contas)}")
            resultados.append(("pendente", f"People/{nome}", motivo + ". Nenhuma associação por nome foi feita."))
            continue
        for conta, conv, pasta in achadas:
            rotulo = f"People/{pasta}"
            if (conta, conv["id"]) in usados:
                resultados.append(("pendente", rotulo, "conversa já associada a outra pessoa; conferir duplicidade."))
                continue
            usados.add((conta, conv["id"]))
            resultados.append(_processar(ctx, conta, conv, destino, "People", pasta, dias, processar, aviso, log, rotulo,
                                         titulo=titulo_pessoa(conv, nome)))

    for grupo in conf.get("grupos") or []:
        alvo = grupo.get("conversa") or grupo.get("jid")
        conta = grupo.get("conta") or contas[0]
        nome = grupo.get("nome") or alvo
        rotulo = f"Group/{nome}"
        try:
            conv = resolver(ctx, estado, conta, alvo)
        except ErroFonte as e:
            resultados.append(("erro", rotulo, str(e)))
            continue
        resultados.append(_processar(ctx, conta, conv, destino, "Group", nome, dias, processar, aviso, log, rotulo))

    _nota_status(destino, contas, ctx, resultados)
    return resultados


def titulo_pessoa(conv, nome_crm):
    """Nome no título do transcript: o do WhatsApp; se o contato não está salvo (o nome é só
    o número), o do CRM."""
    nome = (conv.get("nome") or "").strip()
    return nome if nome and not nome.lstrip("+").replace(" ", "").replace("-", "").isdigit() else nome_crm


def numero_de(conv, telefone):
    n = numero(conv["id"])
    return n if conv["id"].endswith(("@c.us", "@s.whatsapp.net")) else telefone or n


def _processar(ctx, conta, conv, destino, tipo, pasta, dias, processar, aviso, log, rotulo, titulo=None):
    try:
        r = processar(ctx, conta, conv, os.path.join(destino, tipo), pasta, titulo or conv.get("nome") or pasta, dias, log)
        if r is None:
            return ("ok", rotulo, "nada para exportar: a conversa só tem eventos (ligações, avisos do WhatsApp).")
        inicio = f"criado com o histórico completo ({r['mensagens']} mensagens)." if r.get("primeira") else "atualizado."
        return ("ok", rotulo, inicio + aviso(r))
    except Exception as e:  # uma conversa com problema não para as outras
        return ("erro", rotulo, str(e)[:1000])


def _nota_status(destino, contas, ctx, resultados):
    os.makedirs(destino, exist_ok=True)
    origens = []
    for conta in contas:
        try:
            fonte = ctx.fonte(conta)
        except ErroFonte:
            origens.append(f"{conta} (indisponível)")
            continue
        origens.append(f"{conta} (WAHA, sessão {fonte.sessao})" if fonte.tipo == "waha" else f"{conta} (WhatsApp Desktop do Mac)")
    origem = ", ".join(origens)
    rotulos = {"ok": "OK", "erro": "Erro", "pendente": "Pendente"}
    ordem = {"pendente": 0, "erro": 1, "ok": 2}
    linhas = [f"- {rotulos[t]} · {r}: {m}" for t, r, m in sorted(resultados, key=lambda x: (ordem[x[0]], x[1]))]
    conteudo = (f"# Status da sincronização do WhatsApp\n\nÚltima execução: "
                f"{datetime.datetime.now():%d/%m/%Y %H:%M:%S}\n\nContas: {origem}. Transcrição local (whisper.cpp). "
                f"Gerado por whatsapp-local para o Obsidian CRM ({PLUGIN}).\n\n" + "\n".join(linhas) + "\n")
    nota = os.path.join(destino, "Status da sincronização.md")
    with open(nota + ".tmp", "w", encoding="utf-8") as f:
        f.write(conteudo)
    os.replace(nota + ".tmp", nota)

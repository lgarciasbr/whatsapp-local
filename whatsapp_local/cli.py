# SPDX-FileCopyrightText: 2026 Filipe
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
# Baseado na primeira versão de Filipe; alterado por Leandro Garcia.
"""Comando `wa`. Rode `wa --help` ou `wa <comando> --help`."""
import argparse
import json
import signal
import sys
import time
from datetime import datetime

from . import __version__, agendar, exportar, operacoes, sync, transcricao
from .config import Config, abrir_fonte
from .modelo import (CATEGORIAS, CONTATO, LOCALIZACAO, MIDIA, ROTULO_CAT, SISTEMA, TEXTO, Ambigua, ErroFonte,
                     autor, fmt_data, mmss, resolver_conversa, sem_acento)
from .trava import Ocupado


def periodo(args):
    """(início, fim) em timestamp Unix; None = sem limite."""
    ini = fim = None
    if getattr(args, "dias", None):
        ini = time.time() - args.dias * 86400
    if getattr(args, "desde", None):
        ini = time.mktime(datetime.strptime(args.desde, "%Y-%m-%d").timetuple())
    if getattr(args, "ate", None):
        fim = time.mktime(datetime.strptime(args.ate, "%Y-%m-%d").timetuple()) + 86400
    return ini, fim


def conversa_e_mensagens(fonte, args, ids=None):
    if not args.com:
        raise ErroFonte("Informe --com <conversa> (nome, número ou id).")
    conv = resolver_conversa(fonte.conversas(), args.com)
    ini, fim = periodo(args)
    return conv, fonte.mensagens(conv["id"], ini, fim, ids)


# ---------- comandos ----------

def cmd_contas(cfg, args):
    print(f"Config: {cfg.caminho}" + ("" if cfg.existe else " (não existe)"))
    print(f"Dados:  {cfg.pasta_dados}\n")
    for nome, conta in cfg.contas.items():
        padrao = " (padrão)" if nome == cfg.conta_padrao else ""
        desc = conta.get("fonte")
        if desc == "waha":
            desc += f" {conta.get('url')} sessão {conta.get('sessao', 'default')}"
        print(f"{nome}{padrao}: {desc}")
        if args.testar:
            try:
                fonte = abrir_fonte(cfg, nome)
                if fonte.tipo == "waha":
                    status, num = fonte.testar()
                    print(f"  sessão {status}, número {num}")
                else:
                    print(f"  {len(fonte.conversas())} conversas no app do Mac")
            except ErroFonte as e:
                print(f"  ERRO: {e}")


def cmd_conversas(cfg, args):
    fonte = abrir_fonte(cfg, args.conta)
    convs = fonte.conversas()
    if args.busca:
        q = sem_acento(args.busca)
        convs = [c for c in convs if q in sem_acento(c["nome"]) or q in c["id"]]
    for c in convs[: args.limite]:
        print(f"{fmt_data(c['ultima'])}  {'grupo' if c['grupo'] else '     '}  {c['nome'] or '?'}  {c['id']}")


def cmd_inventario(cfg, args):
    fonte = abrir_fonte(cfg, args.conta)
    conv, msgs = conversa_e_mensagens(fonte, args)
    cont = {c: {"total": 0, "disco": 0, "baixado": 0, "baixavel": 0, "expirado": 0, "indisponivel": 0,
                "segundos": 0, "segundos_faltando": 0, "transcritos": 0} for c in CATEGORIAS}
    midias = [(m, fonte.status_midia(m)[0]) for m in operacoes.com_midia(msgs)]
    checou = args.checar and fonte.tipo == "desktop"
    if checou:  # pelo WAHA, só tentando baixar dá pra saber
        vivos = fonte.verificar([m for m, st in midias if st == "baixavel"])
        midias = [(m, "expirado" if st == "baixavel" and m["id"] not in vivos else st) for m, st in midias]
    for m, st in midias:
        cat = MIDIA[m["tipo"]][0]
        c = cont[cat]
        c["total"] += 1
        c[st] += 1
        c["segundos"] += int(m["duracao"] or 0)
        if st in ("baixavel", "expirado", "indisponivel"):
            c["segundos_faltando"] += int(m["duracao"] or 0)
        if cat in ("audio", "video") and fonte.cache.transcricao(m["id"]) is not None:
            c["transcritos"] += 1
    if args.json:
        print(json.dumps({"conversa": conv["nome"], "id": conv["id"], "mensagens": len(msgs), "midia": cont},
                         ensure_ascii=False, indent=2))
        return
    print(f"Conversa: {conv['nome']} ({conv['id']})")
    if not msgs:
        print("Nenhuma mensagem no período.")
        return
    print(f"Período: {fmt_data(msgs[0]['data'])} a {fmt_data(msgs[-1]['data'])} · {len(msgs)} mensagens\n")
    print(f"{'tipo':<11}{'total':>6}{'aqui':>8}{'faltam':>8}{'baixáveis':>11}{'fora do ar':>12}{'transcritos':>13}")
    for cat in CATEGORIAS:
        c = cont[cat]
        if c["total"]:
            tr = str(c["transcritos"]) if cat in ("audio", "video") else "-"
            print(f"{ROTULO_CAT[cat]:<11}{c['total']:>6}{c['disco'] + c['baixado']:>8}"
                  f"{c['baixavel'] + c['expirado'] + c['indisponivel']:>8}{c['baixavel']:>11}"
                  f"{c['expirado'] + c['indisponivel']:>12}{tr:>13}")
    for cat in ("audio", "video"):
        if cont[cat]["total"]:
            print(f"\nDuração de {ROTULO_CAT[cat]}: {mmss(cont[cat]['segundos'])} no total, "
                  f"{mmss(cont[cat]['segundos_faltando'])} nos que faltam.", end="")
    print()
    if any(cont[c]["baixavel"] for c in CATEGORIAS):
        if fonte.tipo == "waha":
            print("\n'baixáveis' = ainda não pedidos ao WAHA. Áudio e vídeo costumam sumir do servidor do "
                  "WhatsApp em ~2 semanas; o que sumiu passa a 'fora do ar' depois da primeira tentativa.")
        elif not checou:
            print("\n'baixáveis' = só link ainda válido (rodou com --sem-checar).")


def cmd_mensagens(cfg, args):
    fonte = abrir_fonte(cfg, args.conta)
    conv, msgs = conversa_e_mensagens(fonte, args)
    if args.limite:
        msgs = msgs[-args.limite:]
    nomes = fonte.nomes()
    if args.json:
        print(json.dumps(operacoes.registros(fonte, conv, msgs, nomes), ensure_ascii=False, indent=1))
        return
    print(f"# {conv['nome']} ({conv['id']}) · {len(msgs)} mensagens")
    for m in msgs:
        quando, quem = fmt_data(m["data"], True), autor(m, conv, nomes)
        if m["tipo"] in TEXTO:
            if m["texto"]:
                print(f"{quando}  {quem}: {m['texto']}")
        elif m["tipo"] in MIDIA:
            cat, rot, _ = MIDIA[m["tipo"]]
            st, _ = fonte.status_midia(m)
            partes = [rot] + ([mmss(m["duracao"])] if m["duracao"] else [])
            if cat == "documento" and m["texto"]:
                partes.append(m["texto"])
            partes.append(f"#{m['id']}")
            if st in ("baixavel", "expirado", "indisponivel"):
                partes.append({"baixavel": "não baixado", "expirado": "não baixado, link vencido",
                               "indisponivel": "não baixado, indisponível"}[st])
            linha = f"{quando}  {quem}: [{', '.join(partes)}]"
            if m["legenda"] and cat != "documento":
                linha += f" {m['legenda']}"
            tr = fonte.cache.transcricao(m["id"]) if cat in ("audio", "video") else None
            if tr:
                linha += f'\n    transcrição: "{tr}"'
            print(linha)
        elif m["tipo"] == LOCALIZACAO:
            print(f"{quando}  {quem}: [localização]")
        elif m["tipo"] == CONTATO:
            print(f"{quando}  {quem}: [contato]")
        elif m["texto"] and m["tipo"] not in SISTEMA:
            print(f"{quando}  {quem}: {m['texto']}")


def cmd_baixar(cfg, args):
    fonte = abrir_fonte(cfg, args.conta)
    _, msgs = conversa_e_mensagens(fonte, args, args.ids)
    ok, pulou, falhou = operacoes.baixar(fonte, operacoes.com_midia(msgs, args.tipos and args.tipos.split(",")))
    print(f"\nBaixados: {ok} · já existiam: {pulou} · sem como baixar/falharam: {falhou}")


def cmd_transcrever(cfg, args):
    falta = transcricao.faltando(cfg.whisper)
    if falta:
        raise ErroFonte(f"Falta instalar: {', '.join(falta)}. Rode o instalador para ver como.")
    transcricao.modelo(cfg.whisper)  # falha cedo (código 3) se não houver modelo
    fonte = abrir_fonte(cfg, args.conta)
    _, msgs = conversa_e_mensagens(fonte, args, args.ids)
    msgs = operacoes.com_midia(msgs, (args.tipos or "audio,video").split(","))
    feitos, cache, sem_arquivo, falhas = operacoes.transcrever(fonte, msgs, cfg.whisper, args.idioma, args.refazer,
                                                                log=lambda s: print(s, flush=True))
    print(f"\nTranscritos agora: {feitos} · já estavam em cache: {cache} · sem arquivo: {sem_arquivo} · falhas: {falhas}")
    if sem_arquivo and fonte.tipo == "waha":
        print("Os sem arquivo saíram do servidor do WhatsApp; só voltam se o contato reenviar.")
    elif sem_arquivo:
        print("Os sem arquivo não foram baixados pelo app. Rode `wa inventario` e, se o usuário quiser, `wa baixar`.")


def cmd_exportar(cfg, args):
    fonte = abrir_fonte(cfg, args.conta)
    conv, msgs = conversa_e_mensagens(fonte, args)
    nome = args.nome or conv["nome"] or conv["id"].split("@")[0]
    r = exportar.exportar(operacoes.registros(fonte, conv, msgs, fonte.nomes()), conv["id"], args.destino,
                          args.pasta or exportar.pasta_padrao(nome, conv["grupo"]),
                          exportar.titulo_padrao(nome, conv["grupo"]))
    if r is None:
        print("Nenhuma mensagem no período; nada foi escrito.")
    else:
        print(f"{r['pasta']}: {r['mensagens']} mensagens, {r['anexos']} anexos, "
              f"{r['transcritos']} de {r['audios']} áudios transcritos.")


def cmd_sync(cfg, args):
    if not cfg.sync.get("conversas") and not cfg.sync.get("obsidian_crm"):
        raise ErroFonte(f"Nada para sincronizar: configure \"sync\" em {cfg.caminho}.")
    resultados = sync.executar(cfg)
    if any(t == "erro" for t, _, _ in resultados):
        sys.exit(1)


def cmd_modelo(cfg, args):
    for p in transcricao.faltando(cfg.whisper):
        print(f"{p}: não instalado")
    print(f"Modelo que será usado: {transcricao.modelo(cfg.whisper)}")


def cmd_baixar_modelo(cfg, args):
    transcricao.baixar_modelo(args.qual, args.confirmado)


def cmd_agendar(cfg, args):
    agendar.agendar(cfg, args.minutos, args.instalar, args.remover)


def main(argv=None):
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `| head` não deve dar traceback
    p = argparse.ArgumentParser(prog="wa", description="Lê, transcreve (localmente) e exporta conversas do WhatsApp. Só leitura.")
    p.add_argument("--version", action="version", version=f"whatsapp-local {__version__}")
    p.add_argument("--conta", help="conta do config.json (padrão: conta_padrao)")
    p.add_argument("--config", help="caminho do config.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_periodo(sp):
        sp.add_argument("--com", help="nome, número ou id da conversa")
        sp.add_argument("--desde", help="AAAA-MM-DD")
        sp.add_argument("--ate", help="AAAA-MM-DD (inclusive)")
        sp.add_argument("--dias", type=int, help="últimos N dias")

    sp = sub.add_parser("contas", help="lista as contas configuradas")
    sp.add_argument("--testar", action="store_true", help="testa a conexão de cada conta")
    sp.set_defaults(fn=cmd_contas)

    sp = sub.add_parser("conversas", help="lista conversas")
    sp.add_argument("--busca")
    sp.add_argument("--limite", type=int, default=30)
    sp.set_defaults(fn=cmd_conversas)

    sp = sub.add_parser("inventario", help="mídia do período: o que tem aqui e o que falta")
    add_periodo(sp)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--sem-checar", dest="checar", action="store_false", help="app do Mac: não consulta o servidor")
    sp.set_defaults(fn=cmd_inventario)

    sp = sub.add_parser("mensagens", help="conversa em ordem, com transcrições")
    add_periodo(sp)
    sp.add_argument("--limite", type=int)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_mensagens)

    sp = sub.add_parser("baixar", help="baixa a mídia que falta")
    add_periodo(sp)
    sp.add_argument("--tipos", help="audio,video,imagem,documento (padrão: todos)")
    sp.add_argument("--ids", nargs="+", help="ids que aparecem como #id em `wa mensagens`")
    sp.set_defaults(fn=cmd_baixar)

    sp = sub.add_parser("transcrever", help="transcreve áudio e vídeo localmente")
    add_periodo(sp)
    sp.add_argument("--tipos", help="audio,video (padrão: os dois)")
    sp.add_argument("--ids", nargs="+")
    sp.add_argument("--idioma", help="ex.: pt (padrão: o do config, senão auto)")
    sp.add_argument("--refazer", action="store_true", help="ignora o cache de transcrição")
    sp.set_defaults(fn=cmd_transcrever)

    sp = sub.add_parser("exportar", help="exporta para Markdown + Anexos + Mensagens.json")
    add_periodo(sp)
    sp.add_argument("--destino", required=True, help="pasta onde fica a pasta da conversa")
    sp.add_argument("--pasta", help="nome da pasta da conversa (padrão: 'Privado - Nome' ou 'Grupo Nome')")
    sp.add_argument("--nome", help="nome exibido (padrão: o da conversa)")
    sp.set_defaults(fn=cmd_exportar)

    sp = sub.add_parser("sync", help="atualiza as conversas configuradas em \"sync\"")
    sp.set_defaults(fn=cmd_sync)

    sp = sub.add_parser("modelo", help="qual modelo do whisper será usado (código 3 = nenhum)")
    sp.set_defaults(fn=cmd_modelo)

    sp = sub.add_parser("baixar-modelo", help="baixa um modelo do whisper.cpp (só com --confirmado)")
    sp.add_argument("qual", nargs="?", default="turbo", choices=list(transcricao.MODELOS_BAIXAVEIS))
    sp.add_argument("--confirmado", action="store_true", help="o usuário autorizou o download")
    sp.set_defaults(fn=cmd_baixar_modelo)

    sp = sub.add_parser("agendar", help="roda `wa sync` periodicamente (launchd no macOS, systemd/cron no Linux)")
    sp.add_argument("--minutos", type=int, default=30)
    sp.add_argument("--instalar", action="store_true", help="instala o agendamento (senão só mostra)")
    sp.add_argument("--remover", action="store_true")
    sp.set_defaults(fn=cmd_agendar)

    args = p.parse_args(argv)
    try:
        args.fn(Config(args.config), args)
    except Ambigua as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    except transcricao.SemModelo as e:
        print(e, file=sys.stderr)
        sys.exit(transcricao.SEM_MODELO)
    except (ErroFonte, exportar.ErroExportacao, Ocupado) as e:
        print(e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Instalador do whatsapp-local (macOS e Linux; Windows não testado).

    python3 instalar.py

Confere as dependências, cria o comando `wa`, configura as contas (app do Mac e/ou WAHA)
e instala a skill para os agentes (Claude Code, Pi, Codex). Pode rodar de novo: o que já
existe é mantido, a menos que você peça para trocar.
"""
import getpass
import json
import os
import shutil
import subprocess
import sys

AQUI = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, AQUI)

from whatsapp_local.config import DADOS_PADRAO, PASTA_CONFIG, nome_variavel  # noqa: E402

AGENTES = {"Claude Code": "~/.claude/skills", "Pi": "~/.pi/agent/skills", "Codex": "~/.codex/skills"}


def perguntar(texto, padrao=""):
    r = input(f"{texto}" + (f" [{padrao}]" if padrao else "") + ": ").strip()
    return r or padrao


def sim(texto, padrao=True):
    r = input(f"{texto} [{'S/n' if padrao else 's/N'}]: ").strip().lower()
    return padrao if not r else r.startswith("s") or r.startswith("y")


def titulo(t):
    print(f"\n== {t} ==")


def dependencias():
    titulo("Dependências")
    if sys.version_info < (3, 9):
        sys.exit("Precisa do Python 3.9 ou mais novo.")
    if sys.platform not in ("darwin",) and not sys.platform.startswith("linux"):
        print("Aviso: o whatsapp-local não foi testado neste sistema. Só a fonte WAHA pode funcionar.")
    falta = [p for p in ("ffmpeg", "ffprobe", "whisper-cli") if not shutil.which(p)]
    if not falta:
        print("ffmpeg e whisper-cli: ok")
        return
    print("Falta: " + ", ".join(falta) + " (necessários para transcrever).")
    if sys.platform == "darwin":
        print("  brew install ffmpeg whisper-cpp")
    else:
        print("  ffmpeg: sudo apt install ffmpeg (ou o gerenciador da sua distribuição)")
        print("  whisper-cli: compile o whisper.cpp (https://github.com/ggml-org/whisper.cpp):")
        print("    git clone https://github.com/ggml-org/whisper.cpp && cd whisper.cpp")
        print("    cmake -B build && cmake --build build -j --config Release")
        print("    e ponha build/bin/whisper-cli no PATH, ou aponte em \"whisper\": {\"executavel\": ...}")
    print("Dá para seguir a instalação e instalar isso depois.")


def comando():
    titulo("Comando wa")
    pasta = os.path.expanduser("~/.local/bin")
    destino = os.path.join(pasta, "wa")
    origem = os.path.join(AQUI, "wa")
    if os.path.islink(destino) and os.path.realpath(destino) == os.path.realpath(origem):
        print(f"{destino}: ok")
    elif os.path.exists(destino) or os.path.islink(destino):
        print(f"{destino} já existe e aponta para outro lugar; não mexi. Remova se quiser trocar.")
    else:
        os.makedirs(pasta, exist_ok=True)
        os.symlink(origem, destino)
        print(f"Criado: {destino} -> {origem}")
    if pasta not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Aviso: {pasta} não está no PATH. Acrescente no seu shell: export PATH=\"$HOME/.local/bin:$PATH\"")


def configurar():
    titulo("Configuração")
    caminho = os.environ.get("WA_CONFIG") or os.path.join(PASTA_CONFIG, "config.json")
    if os.path.exists(caminho) and not sim(f"{caminho} já existe. Refazer?", False):
        return
    os.makedirs(os.path.dirname(caminho), mode=0o700, exist_ok=True)
    dados = perguntar("Pasta dos dados (mídia baixada e transcrições)", DADOS_PADRAO)
    contas, segredos = {}, {}
    if sys.platform == "darwin" and sim("Ler o WhatsApp Desktop deste Mac?"):
        contas[perguntar("Nome da conta", "mac")] = {"fonte": "desktop"}
    while sim("Adicionar um servidor WAHA?", not contas):
        nome = perguntar("Nome da conta (ex.: trabalho)", "waha")
        url = perguntar("URL do WAHA (ex.: https://waha.exemplo.com)")
        sessao = perguntar("Sessão", "default")
        chave = getpass.getpass("API key do WAHA (não aparece ao digitar): ").strip()
        contas[nome] = {"fonte": "waha", "url": url.rstrip("/"), "sessao": sessao}
        if chave:
            segredos[nome_variavel(nome)] = chave
    if not contas:
        print("Nenhuma conta configurada; rode de novo quando quiser.")
        return
    config = {"dados": dados, "conta_padrao": next(iter(contas)), "contas": contas,
              "whisper": {"idioma": perguntar("Idioma das transcrições (pt, en, auto...)", "pt")}}
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.chmod(caminho, 0o600)
    print(f"Gravado: {caminho}")
    if segredos:
        arquivo = os.path.join(os.path.dirname(caminho), "segredos.env")
        antigos = {}
        if os.path.exists(arquivo):
            with open(arquivo, encoding="utf-8") as f:
                antigos = dict(l.strip().split("=", 1) for l in f if "=" in l and not l.startswith("#"))
        antigos.update(segredos)
        fd = os.open(arquivo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(f"{k}={v}\n" for k, v in antigos.items()))
        print(f"API keys em {arquivo} (só o seu usuário lê).")


def skill():
    titulo("Skill para agentes")
    origem = os.path.join(AQUI, "skill", "SKILL.md")
    for agente, pasta in AGENTES.items():
        pasta = os.path.expanduser(pasta)
        if not os.path.isdir(os.path.dirname(pasta)):
            continue  # agente não instalado
        destino = os.path.join(pasta, "whatsapp-local", "SKILL.md")
        if os.path.islink(destino) and os.path.realpath(destino) == os.path.realpath(origem):
            print(f"{agente}: ok")
            continue
        if os.path.exists(destino) or not sim(f"Instalar a skill no {agente} ({pasta})?"):
            print(f"{agente}: não mexi" + (f" ({destino} já existe)" if os.path.exists(destino) else ""))
            continue
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        os.symlink(origem, destino)
        print(f"{agente}: {destino}")


def conferir():
    titulo("Conferência")
    wa = [sys.executable, os.path.join(AQUI, "wa")]
    subprocess.run(wa + ["contas", "--testar"])
    print()
    if subprocess.run(wa + ["modelo"]).returncode == 3:
        print("Sem modelo do whisper. Para ver as opções: wa baixar-modelo turbo (só baixa com --confirmado).")
    print("\nPróximos passos: `wa conversas`, e para manter conversas atualizadas, a seção \"sync\" do\n"
          "config (veja o README) e `wa agendar --instalar`.")


if __name__ == "__main__":
    try:
        dependencias()
        comando()
        configurar()
        skill()
        conferir()
    except (KeyboardInterrupt, EOFError):
        print("\nInterrompido.")

# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""App mínimo que o launchd abre no macOS para rodar `wa sync`.

O macOS protege pastas como Documentos, iCloud Drive e OneDrive. Um Python iniciado direto pelo
launchd não tem a quem pedir permissão e é bloqueado. Aberto por um app, o pedido aparece uma vez,
em nome do app, e a permissão vale só para ele. O app não tem lógica: só chama o `wa`.
"""
import hashlib
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import tempfile

from .modelo import ErroFonte

NOME = "WhatsApp Local Sync"
BUNDLE_ID = "io.github.whatsapp-local.sync"
ICONE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "macos", "icone.icns")
RECEITA = "whatsapp-local.json"  # em Contents/Resources: o que gerou o app, para não recriá-lo à toa
FORMATO = 2  # muda quando a montagem do app muda, para recriar apps feitos por versões anteriores


def caminho_app():
    return os.path.expanduser(f"~/Applications/{NOME}.app")


def comando_shell(comando, ambiente, logs):
    """Linha de shell que o app executa: roda o comando e grava a saída nos logs, sem nunca falhar
    (um erro no `do shell script` abriria uma janela de erro a cada execução agendada)."""
    q = shlex.quote
    sync_log, erros = q(os.path.join(logs, "sync.log")), q(os.path.join(logs, "erros.log"))
    exports = "".join(f"export {k}={q(v)}; " for k, v in ambiente.items())
    return (f"{exports}mkdir -p {q(logs)}; echo \"== $(date '+%Y-%m-%d %H:%M:%S')\" >> {sync_log}; "
            f"{' '.join(q(a) for a in comando)} >> {sync_log} 2>> {erros} "
            f"|| echo \"wa sync terminou com código $?\" >> {erros}")


def applescript(linha_shell):
    texto = linha_shell.replace("\\", "\\\\").replace('"', '\\"')
    return f'on run\n\tdo shell script "{texto}"\nend run\n'


def criar(linha_shell, destino=None, icone=ICONE):
    """Cria (ou atualiza) o app. Devolve False quando o app existente já é o mesmo: recriá-lo muda a
    assinatura e faria o macOS pedir a permissão de novo."""
    destino = destino or caminho_app()
    fonte = applescript(linha_shell)
    receita = {"formato": FORMATO, "script": fonte, "icone": _sha256(icone)}
    if _receita(destino) == receita and _assinatura_valida(destino):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        script, app = os.path.join(tmp, "sync.applescript"), os.path.join(tmp, f"{NOME}.app")
        with open(script, "w", encoding="utf-8") as f:
            f.write(fonte)
        _rodar(["osacompile", "-o", app, script])
        recursos = os.path.join(app, "Contents", "Resources")
        shutil.copyfile(icone, os.path.join(recursos, "applet.icns"))
        # O ícone padrão do osacompile fica em Assets.car e, via CFBundleIconName, teria prioridade.
        if os.path.exists(os.path.join(recursos, "Assets.car")):
            os.unlink(os.path.join(recursos, "Assets.car"))
        info = os.path.join(app, "Contents", "Info.plist")
        with open(info, "rb") as f:
            dados = plistlib.load(f)
        dados.pop("CFBundleIconName", None)
        dados.update({"CFBundleIdentifier": BUNDLE_ID, "CFBundleName": NOME, "CFBundleIconFile": "applet",
                      "LSUIElement": True})  # sem ícone no Dock
        with open(info, "wb") as f:
            plistlib.dump(dados, f)
        with open(os.path.join(recursos, RECEITA), "w", encoding="utf-8") as f:
            json.dump(receita, f, ensure_ascii=False, indent=1)
        _rodar(["codesign", "--force", "--deep", "--sign", "-", app])  # assinatura local (ad-hoc)
        remover(destino)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        shutil.move(app, destino)
    return True


def remover(destino=None):
    destino = destino or caminho_app()
    if os.path.exists(destino):
        shutil.rmtree(destino)
        return True
    return False


def _receita(app):
    try:
        with open(os.path.join(app, "Contents", "Resources", RECEITA), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _assinatura_valida(app):
    return subprocess.run(["codesign", "--verify", app], capture_output=True).returncode == 0


def _sha256(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _rodar(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise ErroFonte(f"`{cmd[0]}` não encontrado: o app de agendamento só pode ser criado no macOS.")
    if r.returncode:
        raise ErroFonte(f"`{cmd[0]}` falhou: {(r.stderr or r.stdout).strip()}")

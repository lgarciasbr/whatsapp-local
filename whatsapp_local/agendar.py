# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Agenda `wa sync`: launchd no macOS, timer do systemd (ou cron) no Linux."""
import os
import shutil
import subprocess
import sys

from .modelo import ErroFonte

ROTULO = "io.github.whatsapp-local.sync"
SYSTEMD = "whatsapp-local-sync"


def comando():
    wa = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wa")
    return [sys.executable, wa, "sync"]


def agendar(cfg, minutos, instalar, remover):
    logs = os.path.join(cfg.pasta_dados, "logs")
    if sys.platform == "darwin":
        _launchd(cfg, minutos, instalar, remover, logs)
    elif sys.platform.startswith("linux"):
        _linux(cfg, minutos, instalar, remover, logs)
    else:
        raise ErroFonte("Agendamento automático só no macOS e no Linux. No Windows (não testado), "
                        "use o Agendador de Tarefas com: " + " ".join(comando()))


def _ambiente(cfg):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if cfg.caminho:
        env["WA_CONFIG"] = cfg.caminho
    return env


def _launchd(cfg, minutos, instalar, remover, logs):
    plist = os.path.expanduser(f"~/Library/LaunchAgents/{ROTULO}.plist")
    if remover:
        subprocess.run(["launchctl", "unload", plist], capture_output=True)
        if os.path.exists(plist):
            os.unlink(plist)
        print(f"Removido: {plist}")
        return
    env = "".join(f"\t\t<key>{k}</key>\n\t\t<string>{_xml(v)}</string>\n" for k, v in _ambiente(cfg).items())
    args = "".join(f"\t\t<string>{_xml(a)}</string>\n" for a in comando())
    conteudo = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>{ROTULO}</string>
	<key>EnvironmentVariables</key>
	<dict>
{env}	</dict>
	<key>ProgramArguments</key>
	<array>
{args}	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StartInterval</key>
	<integer>{minutos * 60}</integer>
	<key>StandardOutPath</key>
	<string>{_xml(os.path.join(logs, "sync.log"))}</string>
	<key>StandardErrorPath</key>
	<string>{_xml(os.path.join(logs, "erros.log"))}</string>
</dict>
</plist>
"""
    if not instalar:
        print(f"# {plist}\n{conteudo}\nPara instalar: wa agendar --instalar")
        return
    os.makedirs(logs, mode=0o700, exist_ok=True)
    os.makedirs(os.path.dirname(plist), exist_ok=True)
    with open(plist, "w", encoding="utf-8") as f:
        f.write(conteudo)
    subprocess.run(["launchctl", "unload", plist], capture_output=True)
    subprocess.run(["launchctl", "load", "-w", plist], check=True)
    print(f"Instalado: {plist} (a cada {minutos} min e no login). Logs em {logs}.")
    print("Se a exportação for para uma pasta protegida do macOS (OneDrive, iCloud, Documentos), o launchd\n"
          f"pode ser bloqueado: dê Acesso Total ao Disco a {sys.executable} em Ajustes > Privacidade e Segurança.")


def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _linux(cfg, minutos, instalar, remover, logs):
    pasta = os.path.expanduser("~/.config/systemd/user")
    servico, timer = os.path.join(pasta, f"{SYSTEMD}.service"), os.path.join(pasta, f"{SYSTEMD}.timer")
    tem_systemd = shutil.which("systemctl") and subprocess.run(
        ["systemctl", "--user", "is-system-running"], capture_output=True).returncode in (0, 1)
    if remover:
        if tem_systemd:
            subprocess.run(["systemctl", "--user", "disable", "--now", f"{SYSTEMD}.timer"], capture_output=True)
        for p in (servico, timer):
            if os.path.exists(p):
                os.unlink(p)
        print("Removido. Se você usou cron, apague a linha com `crontab -e`.")
        return
    cmd = " ".join(f"'{a}'" for a in comando())
    env = " ".join(f"{k}='{v}'" for k, v in _ambiente(cfg).items())
    if not tem_systemd:
        print("systemd de usuário não disponível. Acrescente com `crontab -e`:\n"
              f"*/{minutos} * * * * {env} {cmd} >> '{logs}/sync.log' 2>&1")
        return
    unit = (f"[Unit]\nDescription=whatsapp-local sync\n\n[Service]\nType=oneshot\n"
            + "".join(f"Environment={k}={v}\n" for k, v in _ambiente(cfg).items())
            + f"ExecStart={cmd}\n")
    tmr = (f"[Unit]\nDescription=whatsapp-local sync a cada {minutos} min\n\n[Timer]\nOnBootSec=2min\n"
           f"OnUnitActiveSec={minutos}min\n\n[Install]\nWantedBy=timers.target\n")
    if not instalar:
        print(f"# {servico}\n{unit}\n# {timer}\n{tmr}\nPara instalar: wa agendar --instalar")
        return
    os.makedirs(pasta, exist_ok=True)
    for p, c in ((servico, unit), (timer, tmr)):
        with open(p, "w", encoding="utf-8") as f:
            f.write(c)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{SYSTEMD}.timer"], check=True)
    print(f"Instalado: {timer} (a cada {minutos} min). Logs: journalctl --user -u {SYSTEMD}")

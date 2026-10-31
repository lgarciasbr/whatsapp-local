"""Cache de uma conta: mídia baixada, transcrições e mídia que já saiu do servidor.

Tudo indexado pelo id da mensagem no WhatsApp, igual nas duas fontes. É conversa
privada (muitas vezes de cliente): a pasta é criada só com permissão do usuário.
"""
import json
import os
from datetime import datetime


class Cache:
    def __init__(self, pasta):
        self.pasta = pasta
        self.midia = os.path.join(pasta, "midia")
        self.transcricoes = os.path.join(pasta, "transcricoes")
        self.sem_midia = os.path.join(pasta, "midia-indisponivel.json")
        self._arquivos = None

    def preparar(self, *subpastas):
        os.makedirs(self.pasta, mode=0o700, exist_ok=True)
        for p in subpastas:
            os.makedirs(p, mode=0o700, exist_ok=True)

    def arquivo(self, wid):
        if self._arquivos is None:
            nomes = os.listdir(self.midia) if os.path.isdir(self.midia) else []
            self._arquivos = {n.split(".", 1)[0]: os.path.join(self.midia, n) for n in nomes if not n.startswith(".")}
        return self._arquivos.get(str(wid))

    def destino_midia(self, wid, ext):
        self.preparar(self.midia)
        self._arquivos = None
        return os.path.join(self.midia, f"{wid}.{ext}")

    def transcricao(self, wid):
        p = os.path.join(self.transcricoes, f"{wid}.txt")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()
        return None

    def salvar_transcricao(self, wid, texto):
        self.preparar(self.transcricoes)
        with open(os.path.join(self.transcricoes, f"{wid}.txt"), "w", encoding="utf-8") as f:
            f.write(texto + "\n")

    def indisponiveis(self):
        if os.path.exists(self.sem_midia):
            with open(self.sem_midia, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def marcar_indisponivel(self, wid):
        self.preparar()
        sem = self.indisponiveis()
        sem[str(wid)] = datetime.now().isoformat(timespec="seconds")
        with open(self.sem_midia + ".tmp", "w", encoding="utf-8") as f:
            json.dump(sem, f)
        os.replace(self.sem_midia + ".tmp", self.sem_midia)

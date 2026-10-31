# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.fakes import CHAVE, WahaFalso  # noqa: E402
from whatsapp_local.config import Config  # noqa: E402

AGORA = 1790000000  # um instante fixo; as mensagens ficam dias antes disso
DIA = 86400


class Caso(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wa-teste-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.waha = WahaFalso()
        self.addCleanup(self.waha.parar)
        env = mock.patch.dict(os.environ, {"WAHA_API_KEY_TRABALHO": CHAVE})
        env.start()
        self.addCleanup(env.stop)
        # O whisper de verdade não roda nos testes: cada arquivo vira "transcrição de <nome>".
        tr = mock.patch("whatsapp_local.transcricao.transcrever",
                        side_effect=lambda origem, conf, idioma=None: f"transcrição de {os.path.basename(origem)}")
        tr.start()
        self.addCleanup(tr.stop)
        relogio = mock.patch("time.time", return_value=AGORA)
        relogio.start()
        self.addCleanup(relogio.stop)

    def config(self, **extra):
        dados = {"dados": os.path.join(self.tmp, "dados"), "conta_padrao": "trabalho",
                 "contas": {"trabalho": {"fonte": "waha", "url": self.waha.url, "sessao": "default"}}}
        dados.update(extra)
        caminho = os.path.join(self.tmp, "config.json")
        with open(caminho, "w") as f:
            json.dump(dados, f)
        return Config(caminho)

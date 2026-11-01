# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whatsapp_local import agendar, app_macos  # noqa: E402

NO_MAC = sys.platform == "darwin" and shutil.which("osacompile")


class AgendamentoMacOS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wa-agendar-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = os.path.join(self.tmp, "Dados com espaço", "logs")
        # Caminho com acento, espaço e aspas: tudo precisa sobreviver ao shell e ao AppleScript.
        self.pasta = os.path.join(self.tmp, 'Código "wa"')
        os.makedirs(self.pasta)
        self.marca = os.path.join(self.pasta, "rodou.txt")
        self.comando = [sys.executable, "-c", "import sys; open(sys.argv[1], 'w').write('ok'); print('sync ok')",
                        self.marca]

    def linha(self, comando=None):
        return app_macos.comando_shell(comando or self.comando, {"WA_CONFIG": os.path.join(self.pasta, "c.json")},
                                       self.logs)

    def ler_log(self, nome):
        with open(os.path.join(self.logs, nome), encoding="utf-8") as f:
            return f.read()

    def test_plist_abre_o_app_e_nao_o_python(self):
        app = "/Users/fulana/Applications/WhatsApp Local Sync.app"
        dados = plistlib.loads(agendar.plist_launchd(app, 30, self.logs).encode())
        self.assertEqual(dados["ProgramArguments"], ["/usr/bin/open", "-g", "-j", app])
        self.assertEqual(dados["StartInterval"], 1800)
        self.assertTrue(dados["RunAtLoad"])

    def test_linha_do_shell_roda_e_grava_os_logs(self):
        subprocess.run(["/bin/sh", "-c", self.linha()], check=True)
        self.assertTrue(os.path.exists(self.marca))
        self.assertIn("sync ok", self.ler_log("sync.log"))

    def test_falha_vai_para_o_log_sem_erro_no_shell(self):
        r = subprocess.run(["/bin/sh", "-c", self.linha([sys.executable, "-c", "raise SystemExit(3)"])])
        self.assertEqual(r.returncode, 0)  # senão o app mostraria uma janela de erro a cada execução
        self.assertIn("terminou com código 3", self.ler_log("erros.log"))

    @unittest.skipUnless(NO_MAC, "só no macOS")
    def test_app_roda_tem_icone_e_nao_e_recriado_sem_mudanca(self):
        app = os.path.join(self.tmp, "Apps", f"{app_macos.NOME}.app")
        self.assertTrue(app_macos.criar(self.linha(), app))
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            info = plistlib.load(f)
        self.assertEqual(info["CFBundleIdentifier"], app_macos.BUNDLE_ID)
        self.assertTrue(info["LSUIElement"])
        with open(app_macos.ICONE, "rb") as a, open(os.path.join(app, "Contents", "Resources", "applet.icns"), "rb") as b:
            self.assertEqual(a.read(), b.read())
        subprocess.run(["codesign", "--verify", app], check=True)

        script = os.path.join(app, "Contents", "Resources", "Scripts", "main.scpt")
        subprocess.run(["osascript", script], check=True)  # o mesmo script que o app executa ao abrir
        self.assertTrue(os.path.exists(self.marca))

        self.assertFalse(app_macos.criar(self.linha(), app))  # igual: preserva a assinatura e a permissão
        self.assertTrue(app_macos.criar(self.linha(self.comando + ["outro"]), app))

    @unittest.skipUnless(NO_MAC, "só no macOS")
    def test_remover(self):
        app = os.path.join(self.tmp, "Apps", f"{app_macos.NOME}.app")
        app_macos.criar(self.linha(), app)
        self.assertTrue(app_macos.remover(app))
        self.assertFalse(os.path.exists(app))
        self.assertFalse(app_macos.remover(app))


if __name__ == "__main__":
    unittest.main()

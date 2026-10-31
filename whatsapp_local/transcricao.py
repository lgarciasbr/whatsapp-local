# SPDX-FileCopyrightText: 2026 Filipe (Comunidade Ratos de IA)
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
# Baseado na primeira versão de Filipe (Comunidade Ratos de IA); alterado por Leandro Garcia.
"""Transcrição local com whisper.cpp. Nenhum áudio vai para serviço de transcrição."""
import hashlib
import os
import shutil
import subprocess
import tempfile

from .modelo import ErroFonte

# Pastas onde costuma haver modelo do whisper.cpp. O Meetily (app de reunião) traz o large-v3.
PASTAS_MODELO = ["~/.cache/whisper",
                 "~/whisper.cpp/models",
                 "~/.local/share/whisper.cpp",
                 "/opt/homebrew/share/whisper-cpp",
                 "/usr/local/share/whisper-cpp",
                 "/usr/share/whisper.cpp",
                 "~/Library/Application Support/com.meetily.ai/models"]
# Do mais preciso pro mais leve. Quantizado (q5_0, q8_0...) conta como o modelo base.
ORDEM_MODELO = ["large-v3", "large-v3-turbo", "large-v2", "large-v1", "large", "medium", "small", "base", "tiny"]
SEM_MODELO = 3  # código de saída quando não há modelo: o agente pergunta ao usuário o que fazer
SEM_AUDIO = "(vídeo sem áudio)"

# Modelos que o comando sabe baixar, do repositório oficial do whisper.cpp no Hugging Face.
# Tamanho e SHA-256 conferidos em 2026-10-15 (cabeçalhos x-linked-size e x-linked-etag do HF).
HF_MODELOS = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
MODELOS_BAIXAVEIS = {
    "turbo": ("ggml-large-v3-turbo.bin", 1624555275,
              "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"),
    "turbo-leve": ("ggml-large-v3-turbo-q5_0.bin", 574041195,
                   "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"),
    "large-v3": ("ggml-large-v3.bin", 3095033483,
                 "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"),
}
PASTA_DOWNLOAD = os.path.expanduser("~/.cache/whisper")


class SemModelo(ErroFonte):
    pass


def executavel(conf):
    return conf.get("executavel") or "whisper-cli"


def faltando(conf):
    """Programas que faltam para transcrever."""
    return [p for p in (executavel(conf), "ffmpeg", "ffprobe") if not shutil.which(p)]


def rank_modelo(nome):
    base = nome[len("ggml-"):-len(".bin")]
    for p in sorted(ORDEM_MODELO, key=len, reverse=True):
        if base == p or base.startswith(p + "-"):
            return ORDEM_MODELO.index(p)
    return len(ORDEM_MODELO)


def modelos_encontrados():
    """ggml-*.bin multilíngues nas pastas conhecidas, do preferido pro último."""
    achados = []
    for pasta in PASTAS_MODELO:
        pasta = os.path.expanduser(pasta)
        if not os.path.isdir(pasta):
            continue
        for nome in os.listdir(pasta):
            # .en só reconhece inglês; silero é modelo de detecção de voz, não de transcrição
            if nome.startswith("ggml-") and nome.endswith(".bin") and ".en" not in nome and "silero" not in nome:
                achados.append(os.path.join(pasta, nome))
    # mesmo modelo: o completo antes do quantizado (nome mais curto)
    return sorted(achados, key=lambda p: (rank_modelo(os.path.basename(p)), len(os.path.basename(p))))


def modelo(conf):
    escolhido = os.environ.get("WA_WHISPER_MODEL") or conf.get("modelo")
    if escolhido:
        escolhido = os.path.expanduser(escolhido)
        if os.path.exists(escolhido):
            return escolhido
        raise SemModelo(f"O modelo configurado não existe: {escolhido}")
    achados = modelos_encontrados()
    if achados:
        return achados[0]
    raise SemModelo("Não achei modelo do whisper.cpp (ggml-*.bin) em:\n"
                    + "\n".join(f"  {p}" for p in PASTAS_MODELO)
                    + "\nAponte um em \"whisper\": {\"modelo\": ...} ou baixe com `wa baixar-modelo`.")


def tem_audio(origem):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", origem], capture_output=True, text=True)
    return bool(r.stdout.strip())


def transcrever(origem, conf, idioma=None):
    if not tem_audio(origem):
        return SEM_AUDIO
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "a.wav")
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", origem,
                            "-vn", "-ar", "16000", "-ac", "1", wav], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(wav) or os.path.getsize(wav) < 1000:
            raise RuntimeError("sem trilha de áudio ou arquivo ilegível")
        r = subprocess.run([executavel(conf), "-m", modelo(conf), "-l", idioma or conf.get("idioma") or "auto",
                            "-f", wav, "-np", "-nt"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"whisper falhou: {r.stderr.strip()[-300:]}")
        return " ".join(l.strip() for l in r.stdout.splitlines() if l.strip())


def gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def sha256_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def baixar_modelo(qual, confirmado):
    nome, tamanho, sha = MODELOS_BAIXAVEIS[qual]
    destino = os.path.join(PASTA_DOWNLOAD, nome)
    parcial = destino + ".part"
    if os.path.exists(destino):
        print(f"Já existe: {destino}")
        return
    ja_tem = os.path.getsize(parcial) if os.path.exists(parcial) else 0
    livre = shutil.disk_usage(PASTA_DOWNLOAD if os.path.isdir(PASTA_DOWNLOAD) else os.path.expanduser("~")).free
    print(f"Modelo: {nome} ({gb(tamanho)})")
    print(f"Origem: {HF_MODELOS}{nome}")
    print(f"Destino: {destino}")
    print(f"Espaço livre: {gb(livre)}" + (f" · download anterior pela metade: {gb(ja_tem)}" if ja_tem else ""))
    if livre < tamanho - ja_tem + 500e6:
        raise ErroFonte("Espaço em disco insuficiente (precisa do tamanho do modelo mais uns 500 MB).")
    if not confirmado:
        print("\nNada baixado. Com o ok do usuário, repita com --confirmado.")
        return
    os.makedirs(PASTA_DOWNLOAD, exist_ok=True)
    # curl mostra progresso e retoma (-C -) se a conexão cair e o comando for repetido
    r = subprocess.run(["curl", "-L", "--fail", "-C", "-", "-o", parcial, HF_MODELOS + nome])
    if r.returncode != 0:
        raise ErroFonte(f"Download interrompido (curl {r.returncode}). Repita o comando pra continuar de onde parou.")
    if os.path.getsize(parcial) != tamanho or sha256_arquivo(parcial) != sha:
        os.unlink(parcial)
        raise ErroFonte("O arquivo baixado não confere com o tamanho/SHA-256 esperado; apaguei. Tente de novo.")
    os.replace(parcial, destino)
    print(f"\nOk, conferido (SHA-256): {destino}")

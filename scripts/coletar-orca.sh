#!/bin/sh
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
# Entrada opcional para agendadores. Não contém conta, segredo nem caminho pessoal.
set -u
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
umask 077
pasta="${XDG_STATE_HOME:-$HOME/.local/state}/whatsapp-local"
mkdir -p "$pasta" || exit 1
log="$pasta/coleta.log"
printf '\n== %s coleta wacli\n' "$(date '+%F %T')" >> "$log"
python3 -u ./wa coletar >> "$log" 2>&1
codigo=$?
printf 'codigo=%s\n' "$codigo" >> "$log"
exit "$codigo"

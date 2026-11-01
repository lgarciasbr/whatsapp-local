#!/bin/sh
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
# Regera icone.icns a partir de ../assets/logo.svg (só no macOS: qlmanage, sips e iconutil vêm com o sistema).
set -eu
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# O macOS aplica a própria máscara (cantos e acabamento) e põe numa moldura os ícones que não
# preenchem o quadro. Por isso o .icns usa só o quadrado do logo, sem margem e sem cantos arredondados.
sed -e 's|viewBox="0 0 1024 1024"|viewBox="100 100 824 824"|' -e 's| rx="185" fill="url(#fundo)"| fill="url(#fundo)"|' \
  ../assets/logo.svg > "$tmp/logo.svg"
grep -q 'viewBox="100 100 824 824"' "$tmp/logo.svg" && ! grep -q 'rx="185"' "$tmp/logo.svg" ||
  { echo "logo.svg mudou: ajuste o recorte em gerar_icone.sh" >&2; exit 1; }
qlmanage -t -s 1024 -o "$tmp" "$tmp/logo.svg" >/dev/null
mkdir "$tmp/icone.iconset"
for n in 16 32 128 256 512; do
  sips -z $n $n "$tmp/logo.svg.png" --out "$tmp/icone.iconset/icon_${n}x${n}.png" >/dev/null
  d=$((n * 2))
  sips -z $d $d "$tmp/logo.svg.png" --out "$tmp/icone.iconset/icon_${n}x${n}@2x.png" >/dev/null
done
iconutil -c icns -o icone.icns "$tmp/icone.iconset"
echo "Gerado: $(pwd)/icone.icns"

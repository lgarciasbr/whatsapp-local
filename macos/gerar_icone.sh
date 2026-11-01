#!/bin/sh
# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
# Regera icone.icns a partir de ../assets/logo.svg (só no macOS: qlmanage, sips e iconutil vêm com o sistema).
set -eu
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
qlmanage -t -s 1024 -o "$tmp" ../assets/logo.svg >/dev/null
mkdir "$tmp/icone.iconset"
for n in 16 32 128 256 512; do
  sips -z $n $n "$tmp/logo.svg.png" --out "$tmp/icone.iconset/icon_${n}x${n}.png" >/dev/null
  d=$((n * 2))
  sips -z $d $d "$tmp/logo.svg.png" --out "$tmp/icone.iconset/icon_${n}x${n}@2x.png" >/dev/null
done
iconutil -c icns -o icone.icns "$tmp/icone.iconset"
echo "Gerado: $(pwd)/icone.icns"

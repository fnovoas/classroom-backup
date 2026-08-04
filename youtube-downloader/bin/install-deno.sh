#!/usr/bin/env bash
# Download a portable Deno binary into this folder (required by yt-dlp for YouTube).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="${DENO_VERSION:-v2.3.1}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ASSET="deno-x86_64-unknown-linux-gnu.zip" ;;
  aarch64|arm64) ASSET="deno-aarch64-unknown-linux-gnu.zip" ;;
  *)
    echo "Arquitectura no soportada: $ARCH" >&2
    exit 1
    ;;
esac

URL="https://github.com/denoland/deno/releases/download/${VERSION}/${ASSET}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Descargando Deno ${VERSION}..."
curl -fsSL -o "$TMP/deno.zip" "$URL"
unzip -o "$TMP/deno.zip" -d "$DIR"
chmod +x "$DIR/deno"
"$DIR/deno" --version
echo "Listo: $DIR/deno"

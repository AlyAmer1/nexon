#!/usr/bin/env bash
set -euo pipefail

# Config (override via env if needed)
OWNER="${OWNER:-AlyAmer1}"
REPO="${REPO:-nexon}"
TAG="${TAG:-presets-v1.0}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
DEST_DIR="${DEST_DIR:-$REPO_ROOT/server/tests/assets/presets}"
BASE_URL="${BASE_URL:-https://github.com/$OWNER/$REPO/releases/download/$TAG}"

ASSETS=("sigmoid.onnx" "medium_sized_model.onnx" "gpt2_dynamic.onnx")
MANIFEST="$REPO_ROOT/server/tests/assets/models/manifest.sha256"

mkdir -p "$DEST_DIR"

# sha tool
if command -v sha256sum >/dev/null 2>&1; then
  SHA_TOOL="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  SHA_TOOL="shasum -a 256"
else
  echo "No sha256 tool found (need sha256sum or shasum)." >&2
  exit 1
fi

echo "Downloading models to: $DEST_DIR"
echo "From release: $BASE_URL"
echo

for file in "${ASSETS[@]}"; do
  url="$BASE_URL/$file"
  out="$DEST_DIR/$file"

  if [[ -f "$out" ]]; then
    echo "✓ Exists: $file (skipping download)"
  else
    echo "↓ Fetching: $file"
    curl -fL --retry 3 -o "$out" "$url"
  fi

  if [[ -f "$MANIFEST" ]]; then
    expect="$(awk -v f="$file" '$2==f{print $1}' "$MANIFEST")"
    if [[ -n "$expect" ]]; then
      got="$($SHA_TOOL "$out" | awk '{print $1}')"
      if [[ "$got" != "$expect" ]]; then
        echo "✗ SHA256 mismatch for $file" >&2
        echo "  expected: $expect" >&2
        echo "  got:      $got" >&2
        exit 1
      else
        echo "✓ Verified: $file"
      fi
    else
      echo "• No manifest entry for $file (skipping verify)"
    fi
  else
    echo "• No manifest file found (skipping verify)"
  fi
done

echo
echo "MODELS_DIR=$DEST_DIR"

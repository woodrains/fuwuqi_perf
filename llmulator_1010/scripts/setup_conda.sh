#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE"

echo "[setup] Creating conda env llmulator from environment.yml"
conda env create -f environment.yml || echo "Env may already exist; updating..." && conda env update -f environment.yml --prune
echo "[setup] Activate with: conda activate llmulator"


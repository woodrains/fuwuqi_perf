#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[train] Starting SFT then hardware predictor training"
bash scripts/train_sft.sh
bash scripts/train_hardware.sh
echo "[train] Done. You can optionally run DPO for dynamic calibration under src/dpo/train_dpo.py"


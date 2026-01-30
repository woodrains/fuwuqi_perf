#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f ./.base_model_path ]; then
  export LLMULATOR_BASE_MODEL="$(cat ./.base_model_path)"
fi

DATA_JSON="./data/llmevaluator/data_dpo.json"
if [ ! -f "$DATA_JSON" ]; then
  echo "[warn] $DATA_JSON not found. You can create it from LLM profile data or provide a ready DPO JSON (prompt/chosen/rejected)."
fi

EPOCHS=${EPOCHS:-3}
echo "[train] DPO dynamic calibration (epochs=${EPOCHS})"
CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-} conda run -n llmulator python -m src.dpo.train_dpo --cfg configs/paths.yaml --data_path "$DATA_JSON" --epochs ${EPOCHS} || \
python -m src.dpo.train_dpo --cfg configs/paths.yaml --data_path "$DATA_JSON" --epochs ${EPOCHS}

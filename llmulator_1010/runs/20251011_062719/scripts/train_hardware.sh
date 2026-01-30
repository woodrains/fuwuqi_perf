#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f ./.base_model_path ]; then
  export LLMULATOR_BASE_MODEL="$(cat ./.base_model_path)"
fi

if ! conda run -n llmulator python -c 'import torch; print(torch.cuda.is_available())' >/dev/null 2>&1; then
  echo "[warn] conda env llmulator not detected. Please run scripts/setup_conda.sh and 'conda activate llmulator'."
fi

echo "[train] Hardware predictor training (epochs=50)"
CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-} conda run -n llmulator python -m src.train.train_hardware --epochs 50 || \
python -m src.train.train_hardware

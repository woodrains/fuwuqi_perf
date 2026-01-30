#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Prefer explicit base model path if provided
if [ -f ./.base_model_path ]; then
  export LLMULATOR_BASE_MODEL="$(cat ./.base_model_path)"
fi

EPOCHS=${EPOCHS:-15}
echo "[train] SFT numeric modeling (first-digit CE), epochs=${EPOCHS}"

# Call the training entry directly to control epochs without altering core code
RUN_SFT="from src.train.sft_digit_ce import train_with_ce; train_with_ce(epochs=${EPOCHS})"
CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-} conda run -n llmulator python -c "$RUN_SFT" || \
python -c "$RUN_SFT"

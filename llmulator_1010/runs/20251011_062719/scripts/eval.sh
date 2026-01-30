#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f ./.base_model_path ]; then
  export LLMULATOR_BASE_MODEL="$(cat ./.base_model_path)"
fi

echo "[eval] LLM numeric inference with pass@5 and MAPE"
PEFT_MODEL=""
if [ -d "./models/dpo_lora" ]; then
  PEFT_MODEL="--peft_model ./models/dpo_lora"
elif [ -d "./models/sft_lora" ]; then
  PEFT_MODEL="--peft_model ./models/sft_lora"
fi

CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-} conda run -n llmulator python -m src.eval.eval_pass5_llama $PEFT_MODEL || \
python -m src.eval.eval_pass5_llama $PEFT_MODEL

Code Organization And Cleanup Notes

Goal
- Provide a clean, minimal code path to reproduce the paper’s algorithm and evaluation without changing the original repository’s core logic. All tweaks are made on copies here.

What’s Kept (Essential)
- Dataset handling and feature extraction used by the models:
  - Copied into `src/data/json_dataset.py` from `../llmulator/train.py` (functions: `extract_features`, `process_A_matrix`, `process_B_matrix`, `process_C_matrix`, `JsonDataset`).
- Core model (Transformer‑H / HardwarePerformancePredictor) and positional encoding:
  - Copied into `src/models/hardware_predictor.py` from `../llmulator/train.py`.
- Training loop for the predictor and its evaluation utilities:
  - Copied logic (no algorithm changes) into `src/train/train_hardware.py`.
- LLM SFT for numeric tokenization (first‑digit CE) and pass@5 evaluation:
  - Based on `../llmulator/sfttrain.py`; evaluation extended to support pass@5.
- Dynamic calibration using DPO (LoRA):
  - Copied as `src/dpo/train_dpo.py` from `../llmulator/llmevaluator/dpo.py`.
- LLM inference for numeric outputs and MAPE:
  - `src/eval/eval_pass5_llama.py` based on `../llmulator/llmevaluator/inference.py` with explicit pass@5 sampling.

What’s Omitted (Non‑essential or bulky)
- Generated/temporary artifacts: `../logs`, `../obj_dir`, `../HLS_output`, `../panda-temp`, etc.
- Large datasets and archives: `../dataset`, `../hls_dataset`, `../llm_dataset`, etc. We reference them via paths instead.
- Prototype/baseline misc code not needed for the main pipeline: e.g., `train_llama.py`, various experimental benchmarks and shell wrappers.

Data And Paths
- Centralized in `configs/paths.yaml`. By default we use the local dataset copies placed under `./data`:
  - `./data/structured/hybrid/{train,test}`
  - `./data/structured/hls/{train,test}` (optional)
  - `./data/structured/{c,openacc}/{train,test}` (optional)
  - `./data/llm/{train,test}/profiledataset.json`

Evaluation Metric
- We follow the paper: report MAPE/MSE and apply pass@5 sampling for numeric generation to reduce randomness.

Dynamic Calibration
- We provide DPO scripts mirroring the paper’s “dynamic prediction‑based calibration” for inputs similar to the test prompts. LoRA is used to avoid catastrophic forgetting.

If Changes Are Needed
- Do not modify `../llmulator` core files. Make copies under `src/` here and change those, always aligning to the paper’s algorithm.

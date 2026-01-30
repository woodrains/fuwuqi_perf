LLMulator_1010: Clean Reproduction Setup

This folder contains a curated, minimal, self-contained project aligned to the LLMulator paper. It removes accumulated/dead files and preserves only the components required to reproduce the core algorithm and evaluation. The core algorithm logic was copied from the original code into this folder and is used here without altering its essence.

Highlights
- Keeps training and evaluation focused on the paper’s method.
- Uses pass@5 sampling for evaluation as described in the paper.
- Supports dynamic calibration (DPO) using test‑similar data.
- Includes local copies of the processed datasets under `./data` so training/eval can run without the original repository.
- Encourages GPU use and conda env `llmulator`.

Quick Start
- Create the conda environment and activate it:
  - `conda env create -f environment.yml`
  - `conda activate llmulator`
- Point data paths in `configs/paths.yaml` if your layout differs.
- Run SFT numeric modeling (optional) and hardware predictor training:
  - `bash scripts/train_all.sh`
- Evaluate with pass@5 sampling:
  - `bash scripts/eval.sh`

Structure
- `src/data/json_dataset.py` — JSON feature extraction and dataset wrapper (copy of the project’s loader logic).
- `src/models/hardware_predictor.py` — HardwarePerformancePredictor and supporting modules (copied, unchanged in logic).
- `src/train/train_hardware.py` — Training loop for the hardware predictor (copied logic; wrapped for CLI).
- `src/train/sft_digit_ce.py` — LoRA SFT for numeric tokenization (first‑digit CE); evaluation supports pass@5.
- `src/dpo/train_dpo.py` — Dynamic calibration using DPO (copied and lightly wrapped for paths).
- `src/eval/eval_pass5_llama.py` — LLaMA inference with pass@5 sampling and MAPE.
- `configs/paths.yaml` — Centralized data/model paths; defaults to use local copies under `./data`.
  - Base model resolution order:
    1) env `LLMULATOR_BASE_MODEL`
    2) `llm.base_model` in `configs/paths.yaml`
    3) first existing path in `llm.candidate_paths` (pre-filled with paths from the original code)
    4) `llm.fallback_model` (HF hub name; editable)
- `scripts/*` — Setup, training, and evaluation scripts.
- `data/README.md` — Notes on using preprocessed datasets from the original repo.
- `docs/REPRODUCTION_GUIDE/` — Full Markdown documentation of the reproduction process (environment, data, training, evaluation, status, troubleshooting).

Notes
- We do not duplicate large datasets or model weights to keep the repo light. Adjust paths in `configs/paths.yaml` to match your setup.
- If you must modify core algorithm code for experiments, do so only under `src/` in this folder; do not change files in `../llmulator`.
 - To force a specific base model path/name at runtime: `export LLMULATOR_BASE_MODEL=/your/model/path`.

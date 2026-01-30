Known Missing Or External Requirements

- Base LLM weights are not included (paper uses LLaMA‑3.2‑1B). Provide a local path or HF model name with access.
- `llama_recipes` utilities referenced by the original inference are not bundled; our eval path uses plain Transformers instead.
- Processed datasets are copied locally under `./data` to remove dependency on the original repository.
- Multi‑GPU training hyperparameters from the paper (8×A100 80GB) may not be feasible for all users; expect variance without equivalent compute.
- Some prototype files (e.g., `train_llama.py`) are exploratory and not part of the curated pipeline.

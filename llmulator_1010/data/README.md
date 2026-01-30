Local Dataset Copies

- This folder contains local copies of the processed datasets needed for training and evaluation so the project can run independently.
- Structure:
  - `structured/hybrid/{train,test}` — general structured JSONs (A/B/C matrices and loop metadata)
  - `structured/hls/{train,test}` — HLS‑specific subsets (optional)
  - `structured/{c,openacc}/{train,test}` — language‑specific subsets (optional)
  - `llm/{train,test}/profiledataset.json` — LLM SFT/DPO style textual data
  - `llmevaluator/*.json` — auxiliary evaluator and DPO datasets

If you add or relocate data, update `configs/paths.yaml` accordingly.

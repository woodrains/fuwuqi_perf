# 环境说明

- Conda 环境：`llmulator`（由 `environment.yml` 创建）。
- GPU：推荐 A100 80GB；通过 `CUDA_VISIBLE_DEVICES` 选择使用的 GPU。
- 基础模型：LLaMA‑3.2‑1B‑Instruct（优先使用本地路径）。

检查与准备：
- `source ~/miniconda3/etc/profile.d/conda.sh && conda env list`
- `conda run -n llmulator python -c "import torch; print(torch.cuda.is_available())"`
- `nvidia-smi -L` 查看可用 GPU。

基础模型路径解析（避免硬编码）：
- 首选：项目根目录 `.base_model_path` 文件，内容为本地模型路径。
- 次选：环境变量 `LLMULATOR_BASE_MODEL`。
- 兜底：`configs/paths.yaml` 中的候选路径或 `fallback_model`（如 TinyLlama，用于 CPU/调试）。

相关文件：
- `environment.yml` —— 依赖清单
- `configs/paths.yaml` —— 数据与模型路径、计算配置
- `src/utils/path_resolver.py` —— 按优先级解析基础模型路径

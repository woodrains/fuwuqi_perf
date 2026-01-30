# LLMulator 复现指南（精简项目：`llmulator_1010`）

本文件夹以 Markdown 形式，完整说明如何仅依赖精简后的 `llmulator_1010` 项目，复现论文中的训练与评估流程。

目录结构与内容说明：
- ENV.md —— 环境、GPU、基础模型与依赖
- DATA.md —— 使用的数据集与 `data/` 目录布局
- TRAINING.md —— 两阶段训练（SFT → DPO）指令与说明
- EVALUATION.md —— pass@5 + MAPE 的评估流程与解读
- STATUS.md —— 本次复现实验的指标、产物与可复现性说明
- TROUBLESHOOTING.md —— 常见问题与排查建议

快速上手：
1) 配置基础模型路径
   - `echo "/public/Llama-3.2-1B-Instruct" > .base_model_path`
   - 或 `export LLMULATOR_BASE_MODEL=/public/Llama-3.2-1B-Instruct`
2) 选择空闲 GPU：`export CUDA_VISIBLE_DEVICES=0`
3) 阶段一 SFT：`EPOCHS=15 bash scripts/train_sft.sh`
4) 阶段二 DPO：`EPOCHS=3 bash scripts/run_dpo.sh`
5) 评估：`bash scripts/eval.sh`

所有路径均相对于 `llmulator_1010/`，运行时不依赖原始项目仓库中的文件。

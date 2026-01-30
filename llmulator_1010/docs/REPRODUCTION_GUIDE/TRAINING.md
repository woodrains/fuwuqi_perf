# 训练流程（两阶段）

概览
- 阶段一：基于 LoRA 的 SFT，使用“首数字交叉熵”（与原始 `sfttrain.py` 思想一致）。
- 阶段二：基于 TRL 的 DPO，针对接近测试分布的数据进行动态校准。

GPU 与基础模型
- 选择 GPU：`export CUDA_VISIBLE_DEVICES=0`
- 设置基础模型：`echo "/public/Llama-3.2-1B-Instruct" > .base_model_path`

阶段一 — SFT
- 脚本：`scripts/train_sft.sh`
- 入口：`src/train/sft_digit_ce.py`（使用 `src/data/json_dataset.py`）
- 建议训练轮数：`EPOCHS=15`
- 运行指令：
```
EPOCHS=15 bash scripts/train_sft.sh
```
- 产物：`models/sft_lora`；日志：`logs_ce/`

阶段二 — DPO（动态校准）
- 脚本：`scripts/run_dpo.sh`
- 入口：`src/dpo/train_dpo.py`
- 数据：`data/llmevaluator/data_dpo.json`（建议扩充以增强校准效果）
- 建议训练轮数：`EPOCHS=3`
- 运行指令：
```
EPOCHS=3 bash scripts/run_dpo.sh
```
- 产物：`models/dpo_lora`

可选 — 硬件预测器
- 脚本：`scripts/train_hardware.sh`
- 入口：`src/train/train_hardware.py`
- 默认参数：`--epochs 50`
- 运行指令：`bash scripts/train_hardware.sh`

说明
- 训练代码无需硬改：优先读取 `LLMULATOR_BASE_MODEL` 或 `.base_model_path`。
- 通过 LoRA 冻结基础权重，节省算力并减轻遗忘。
- 论文使用 8×A100；此处为单卡配方，可通过增加有效 batch/累计步数获得更接近的结果。

# 复现状态（本次实验）

环境
- Conda：`llmulator`（已启用 GPU）
- GPU：本次使用 `CUDA_VISIBLE_DEVICES=0`；可通过 `nvidia-smi` 查看详情。
- 基础模型：`/public/Llama-3.2-1B-Instruct`

数据
- 训练集：`data/llm/train/profiledataset.json`（10,000）
- 测试集：`data/llm/test/profiledataset.json`（100）
- DPO 数据：`data/llmevaluator/data_dpo.json`（28）

训练
- 阶段一 SFT：15 个 epoch → `models/sft_lora`
- 阶段二 DPO：3 个 epoch → `models/dpo_lora`

评估
- 指令：`bash scripts/eval.sh`
- 结果：
  - 样本数：100
  - MAPE（median-of-5）：14.540480
  - pass@5（10% 阈值）：6.00%

与论文（MAPE 12.2%）的差距
- 未采用“渐进数值编码”（当前仅做“首数字 CE”）。
- DPO 偏好数据较少（28 对），弱于论文中的动态校准配置。
- 单卡轻量训练 vs. 论文 8×A100 训练规模。

下一步建议
- 扩充 DPO 数据并适度延长训练；重新评估。
- 补充“渐进数值编码”（遵循论文方法，不另起炉灶）。
- 增加有效 batch/累计步数或采用多卡训练，提升稳定性与泛化。

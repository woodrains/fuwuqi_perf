# 评估

指标（与论文一致）
- MAPE —— 平均绝对百分比误差（Mean Absolute Percentage Error）。
- MSE —— 可选（当前文本推理脚本以 MAPE 为主）。
- pass@5 采样 —— 对同一提示多次生成，降低随机性。

脚本与入口
- 脚本：`scripts/eval.sh`
- 入口：`src/eval/eval_pass5_llama.py`
- 依赖：`configs/paths.yaml` 与 `src/utils/path_resolver.py`（解析模型与数据路径）。

使用方法
```
# 若存在 DPO LoRA，则优先使用；否则回退到 SFT LoRA（若存在）
bash scripts/eval.sh

# 或显式指定
python -m src.eval.eval_pass5_llama --cfg configs/paths.yaml --k 5 --peft_model models/dpo_lora
```

结果解读
- `Samples evaluated` —— 实际参与评测的样本数量。
- `MAPE (median-of-5)` —— 对每个样本做 5 次采样后取中位数计算 MAPE。
- `pass@5 within 10%` —— 若任一次采样的相对误差 ≤ 10% 则记为通过（用于 sanity check，并非论文主指标）。

本次复现结果
- 样本数：100
- MAPE（median-of-5）：14.540480
- pass@5（10% 阈值）：6.00%

逼近论文 12.2% 的建议
- 扩充 DPO 偏好数据（着重覆盖与评估集接近的分布）。
- 采用论文中的“渐进数值编码”，而非仅“首数字 CE”。
- 增加训练时长/有效 batch，或使用多卡训练以稳定泛化。

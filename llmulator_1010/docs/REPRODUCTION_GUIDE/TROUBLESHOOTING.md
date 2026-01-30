# 故障排查

基础模型缺失
- 现象：HuggingFace 加载报错或回退到较慢的默认模型。
- 解决：`echo "/public/Llama-3.2-1B-Instruct" > .base_model_path` 或设置 `export LLMULATOR_BASE_MODEL=...`。

Conda 环境问题
- 现象：`conda run -n llmulator ...` 执行失败。
- 解决：运行 `bash scripts/setup_conda.sh` 或手动激活环境。

GPU 显存/设备选择
- 现象：显存不足（OOM）或落到 CPU 运行。
- 解决：本项目 batch=1 已较小；请确认 `CUDA_VISIBLE_DEVICES` 指向空闲 GPU。

生成时的 pad/eos 警告
- 现象：提示 attention mask 或 pad token 设置相关警告。
- 影响：可忽略；若缺省，tokenizer 会将 `pad_token` 设为 `eos_token`。

数据未找到
- 现象：加载数据集时报错找不到文件。
- 解决：核对 `configs/paths.yaml` 的路径配置，以及 `data/` 下是否存在对应文件（参见 DATA.md）。

DPO 效果不明显
- 现象：评价指标提升有限。
- 解决：扩充 `data/llmevaluator/data_dpo.json` 的偏好样本对（覆盖接近测试分布的数据），并适当提高 `scripts/run_dpo.sh` 中的 `EPOCHS`。

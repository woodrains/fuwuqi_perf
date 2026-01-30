# 数据说明

我们使用从原项目整理出的“已处理、轻量级”数据集，统一放在 `data/` 目录下：

- LLM 的 SFT/DPO 文本数据
  - 训练集：`data/llm/train/profiledataset.json`（10,000 条）
  - 测试集：`data/llm/test/profiledataset.json`（100 条）
  - DPO 数据：`data/llmevaluator/data_dpo.json`（28 对，可扩充）

- 结构化程序特征（用于硬件预测器）
  - 混合数据：`data/structured/hybrid/{train,test}`
  - HLS 数据：`data/structured/hls/{train,test}`
  - C/OpenACC 数据：`data/structured/{c,openacc}/{train,test}`

数据路径由 `configs/paths.yaml` 配置；数据加载器 `JsonDataset` 位于 `src/data/json_dataset.py`，支持训练脚本使用的特征张量（A/B/C 矩阵）与文本字段。

快速核对样本量：

```
python - << 'PY'
import json
print('train size', len(json.load(open('data/llm/train/profiledataset.json'))))
print('test size', len(json.load(open('data/llm/test/profiledataset.json'))))
PY
```

说明：
- 为保持仓库精简，未包含庞大原始数据，只提供处理后的 JSON。
- 为提升 DPO 动态校准效果，建议扩充 `data_dpo.json`，重点覆盖与测试集分布相近的偏好样本对。

#!/usr/bin/env python3
"""
将 LLVM 生成的 bbtrace_ordered.txt 与 QEMU externbb 的补充块合并。

做法：
1. 原样拷贝 LLVM 的 ordered 文本；
2. 读取 merge_pcmap.py 产生的 JSONL（每行一个 qemu 补块）；
3. 按顺序追加到输出文件中，便于统一查阅。
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Iterable


def load_external_blocks(path: pathlib.Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def format_external_block(idx: int, block: dict) -> str:
    symbol = block.get("symbol") or "<external>"
    header = (
        f"=== qemu seq={idx} func={block['func_id']} "
        f"bb={block['bb_id']} ==="
    )
    lines = [
        header,
        f"# source: qemu symbol: {symbol}",
        f"bb_qemu_{block['func_id']}_{block['bb_id']}:",
    ]
    for asm in block.get("asm", []):
        lines.append(f"    {asm}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-ordered", type=pathlib.Path, required=True,
                        help="原始 LLVM bbtrace_ordered.txt")
    parser.add_argument("--external-jsonl", type=pathlib.Path, required=True,
                        help="merge_pcmap.py 输出的 JSONL")
    parser.add_argument("--output", type=pathlib.Path, required=True,
                        help="合并后的 ordered 输出路径")
    args = parser.parse_args()

    base_text = args.llvm_ordered.read_text(encoding="utf-8")
    blocks_text = [
        format_external_block(idx, record)
        for idx, record in enumerate(load_external_blocks(args.external_jsonl), start=1)
    ]

    joined = base_text.rstrip() + "\n\n" + "\n\n".join(blocks_text) + "\n"
    args.output.write_text(joined, encoding="utf-8")


if __name__ == "__main__":
    main()


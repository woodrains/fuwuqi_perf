#!/usr/bin/env python3
"""
合并 LLVM pcmap 与 QEMU externbb dump：
1. 读取 LLVM 生成的 pcmap，作为优先生效的 basic block 区间；
2. 解析 externbb 输出的所有 TB（推荐开启 include_pcmap 模式），
   将其中不在 LLVM pcmap 覆盖范围内的指令段切分出来；
3. 为这些“缺失块”分配新的 func_id/bb_id，并生成新的 pcmap 以及
   JSONL 描述（包含反汇编文本，便于审阅或下游处理）。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple


@dataclasses.dataclass
class PcMapEntry:
    func_id: int
    bb_id: int
    start: int
    end: int


class IntervalCoverage:
    """简单的闭区间集合，支持插入与包含查询。"""

    def __init__(self, intervals: Iterable[Tuple[int, int]] = ()):
        self._intervals: List[Tuple[int, int]] = []
        for start, end in intervals:
            self.add(start, end)

    def add(self, start: int, end: int) -> None:
        if start > end:
            return
        new_start, new_end = start, end
        merged: List[Tuple[int, int]] = []
        inserted = False
        for cur_start, cur_end in self._intervals:
            if cur_end + 1 < new_start:
                merged.append((cur_start, cur_end))
                continue
            if new_end + 1 < cur_start:
                if not inserted:
                    merged.append((new_start, new_end))
                    inserted = True
                merged.append((cur_start, cur_end))
                continue
            new_start = min(new_start, cur_start)
            new_end = max(new_end, cur_end)
        if not inserted:
            merged.append((new_start, new_end))
        self._intervals = merged

    def contains(self, addr: int) -> bool:
        for start, end in self._intervals:
            if start <= addr <= end:
                return True
            if addr < start:
                break
        return False

    def range_covered(self, start: int, end: int) -> bool:
        for cur_start, cur_end in self._intervals:
            if start < cur_start:
                break
            if cur_start <= start and end <= cur_end:
                return True
        return False


def parse_pcmap(path: pathlib.Path) -> Tuple[List[PcMapEntry], IntervalCoverage, Dict[int, int]]:
    entries: List[PcMapEntry] = []
    func_bb_max: Dict[int, int] = defaultdict(int)
    intervals: List[Tuple[int, int]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = dict(item.split("=", 1) for item in line.split("\t"))
            func_id = int(parts["func_id"])
            bb_id = int(parts["bb_id"])
            start = int(parts["start_pc"], 16)
            end = int(parts["end_pc"], 16)
            entries.append(PcMapEntry(func_id, bb_id, start, end))
            func_bb_max[func_id] = max(func_bb_max[func_id], bb_id)
            intervals.append((start, end))
    coverage = IntervalCoverage(intervals)
    return entries, coverage, func_bb_max


_BB_HEADER_RE = re.compile(
    r"^bb start=0x([0-9a-fA-F]+) end=0x([0-9a-fA-F]+) vcpu=(\d+)(?: source=([a-zA-Z]+))?$"
)


def parse_qemu_dump(path: pathlib.Path) -> List[dict]:
    blocks: List[dict] = []
    current: Optional[dict] = None

    def flush_current():
        nonlocal current
        if current:
            blocks.append(current)
            current = None

    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            if line.startswith("bb start="):
                flush_current()
                match = _BB_HEADER_RE.match(line)
                if not match:
                    raise ValueError(f"无法解析 BB 头: {line}")
                start = int(match.group(1), 16)
                end = int(match.group(2), 16)
                source = match.group(4) or "qemu"
                current = {
                    "start": start,
                    "end": end,
                    "source": source,
                    "symbol": None,
                    "instructions": [],
                }
                continue
            if line.startswith("# symbol:"):
                if current:
                    current["symbol"] = line.split(":", 1)[1].strip()
                continue
            if line.startswith("  0x"):
                if not current:
                    raise ValueError("在 BB 之外解析到指令行")
                addr_part, text_part = line.strip().split(":", 1)
                pc = int(addr_part, 16)
                current["instructions"].append(
                    {"pc": pc, "text": text_part.strip(), "notes": []}
                )
                continue
            if line.startswith("    "):
                if current and current["instructions"]:
                    current["instructions"][-1]["notes"].append(line.strip())
                continue
        flush_current()
    return blocks


def split_block_by_coverage(
    block: dict, coverage: IntervalCoverage
) -> List[dict]:
    instrs = block["instructions"]
    if not instrs:
        return []
    segments: List[dict] = []
    current: Optional[dict] = None

    for idx, inst in enumerate(instrs):
        inst_start = inst["pc"]
        next_start = (
            instrs[idx + 1]["pc"] if idx + 1 < len(instrs) else block["end"] + 1
        )
        inst_end = next_start - 1
        covered = coverage.range_covered(inst_start, inst_end)
        if covered:
            if current:
                segments.append(current)
                current = None
            continue
        if not current:
            current = {
                "start": inst_start,
                "instructions": [],
                "symbol": block.get("symbol"),
            }
        current["instructions"].append(inst)
        current["end"] = inst_end

    if current:
        segments.append(current)
    return segments


def allocate_func(func_name: Optional[str], state: dict, func_bb_max: Dict[int, int]) -> Tuple[int, int]:
    if func_name is None or not func_name:
        func_name = "<extern>"
    if func_name not in state["func_ids"]:
        state["max_func_id"] += 1
        state["func_ids"][func_name] = state["max_func_id"]
        func_bb_max[state["max_func_id"]] = 0
    func_id = state["func_ids"][func_name]
    func_bb_max[func_id] += 1
    bb_id = func_bb_max[func_id]
    return func_id, bb_id


def write_pcmap(path: pathlib.Path, entries: List[PcMapEntry]) -> None:
    lines = [
        f"func_id={entry.func_id}\tbb_id={entry.bb_id}\t"
        f"start_pc=0x{entry.start:016x}\tend_pc=0x{entry.end:016x}"
        for entry in sorted(entries, key=lambda e: e.start)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcmap", type=pathlib.Path, required=True, help="LLVM 原始 pcmap")
    parser.add_argument("--qemu-log", type=pathlib.Path, required=True, help="externbb 输出")
    parser.add_argument(
        "--output-pcmap",
        type=pathlib.Path,
        required=True,
        help="合并后的 pcmap 输出路径",
    )
    parser.add_argument(
        "--external-info",
        type=pathlib.Path,
        required=True,
        help="保存 QEMU 补充块的 JSONL 描述（func/bb/asm）",
    )
    args = parser.parse_args()

    llvm_entries, coverage, func_bb_max = parse_pcmap(args.pcmap)
    qemu_blocks = parse_qemu_dump(args.qemu_log)

    allocator_state = {"func_ids": {}, "max_func_id": max(func_bb_max.keys() or [0])}
    new_entries: List[PcMapEntry] = []
    jsonl_lines: List[str] = []

    for block in qemu_blocks:
        segments = split_block_by_coverage(block, coverage)
        for seg in segments:
            func_id, bb_id = allocate_func(seg["symbol"], allocator_state, func_bb_max)
            start = seg["start"]
            end = seg["end"]
            coverage.add(start, end)
            new_entries.append(PcMapEntry(func_id, bb_id, start, end))

            asm_lines: List[str] = []
            for inst in seg["instructions"]:
                asm_lines.append(f"0x{inst['pc']:016x}: {inst['text']}")
                for note in inst["notes"]:
                    asm_lines.append(f"    {note}")

            jsonl_lines.append(
                json.dumps(
                    {
                        "func_id": func_id,
                        "bb_id": bb_id,
                        "symbol": seg.get("symbol"),
                        "start_pc": f"0x{start:016x}",
                        "end_pc": f"0x{end:016x}",
                        "asm": asm_lines,
                    },
                    ensure_ascii=False,
                )
            )

    write_pcmap(args.output_pcmap, llvm_entries + new_entries)
    args.external_info.write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""), encoding="utf-8")


if __name__ == "__main__":
    main()


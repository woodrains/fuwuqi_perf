#!/usr/bin/env python3
"""
按 PC 顺序对 μOP JSONL trace 重排序，默认键：
  pc(升序) -> micro_pc(升序) -> enter_tick -> commit_tick -> fetch_seq -> commit_seq

采用分块 + 归并，避免一次性占用大量内存。
"""
import argparse
import heapq
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# 记录 PC 在执行轨迹中的首次出现顺序，避免简单按数值排序打乱分支轨迹。
pc_order: Dict[int, int] = {}
next_pc_order = 0


def parse_hex(value: Any) -> int:
    if isinstance(value, str) and value.startswith("0x"):
        try:
            return int(value, 16)
        except ValueError:
            return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def parse_key(obj: Dict[str, Any]) -> Tuple[int, int, int, int, int, int]:
    global next_pc_order
    pc = parse_hex(obj.get("pc"))
    if pc not in pc_order:
        pc_order[pc] = next_pc_order
        next_pc_order += 1
    pc_rank = pc_order[pc]
    micro_pc = int(obj.get("micro_pc") or 0)
    enter_tick = int(obj.get("enter_tick") or 0)
    commit_tick = int(obj.get("commit_tick") or 0)
    fetch_seq = int(obj.get("fetch_seq") or 0)
    commit_seq = int(obj.get("commit_seq") or 0)
    return pc_rank, micro_pc, enter_tick, commit_tick, fetch_seq, commit_seq


def load_chunk(fp, chunk_size: int) -> List[Tuple[Tuple[int, ...], str]]:
    chunk: List[Tuple[Tuple[int, ...], str]] = []
    for _ in range(chunk_size):
        line = fp.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            # Disassembly字符串里可能包含制表符，先做简易转义。
            sanitized = line.replace("\t", "\\t")
            obj = json.loads(sanitized)
        except json.JSONDecodeError:
            continue
        chunk.append(
            (parse_key(obj), json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        )
    return chunk


def write_sorted_chunk(chunk: List[Tuple[Tuple[int, ...], str]], tmp_dir: Path, idx: int) -> Path:
    chunk.sort(key=lambda x: x[0])
    path = tmp_dir / f"chunk_{idx:04d}.jsonl"
    with path.open("w") as fp:
        for key, line in chunk:
            key_str = ",".join(str(v) for v in key)
            fp.write(key_str)
            fp.write("\t")
            fp.write(line)
            fp.write("\n")
    return path


def iter_sorted_files(files: List[Path]) -> Iterable[str]:
    """k 路归并多个已排序分块。"""
    # (key, line, file_index)
    heap: List[Tuple[Tuple[int, ...], str, int]] = []
    fps = [f.open() for f in files]

    def push(i: int):
        line = fps[i].readline()
        if not line:
            return
        line = line.rstrip("\n")
        if "\t" not in line:
            return push(i)
        key_part, json_part = line.split("\t", 1)
        try:
            key_tuple = tuple(int(x) for x in key_part.split(","))
        except ValueError:
            return push(i)
        heapq.heappush(heap, (key_tuple, json_part, i))

    for i in range(len(fps)):
        push(i)

    while heap:
        key, line, idx = heapq.heappop(heap)
        yield line
        push(idx)

    for fp in fps:
        fp.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path, help="输入 μOP JSONL")
    ap.add_argument("--output", required=True, type=Path, help="输出排序后 JSONL")
    ap.add_argument("--chunk-size", type=int, default=200000, help="分块大小（行），默认 200k")
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="uop_sort_") as tmp:
        tmp_dir = Path(tmp)
        chunk_files: List[Path] = []

        with args.input.open() as fp:
            idx = 0
            while True:
                chunk = load_chunk(fp, args.chunk_size)
                if not chunk:
                    break
                chunk_path = write_sorted_chunk(chunk, tmp_dir, idx)
                chunk_files.append(chunk_path)
                idx += 1

        # 没有有效行也要输出空文件
        with args.output.open("w") as out_fp:
            if chunk_files:
                for line in iter_sorted_files(chunk_files):
                    out_fp.write(line)
                    out_fp.write("\n")


if __name__ == "__main__":
    main()

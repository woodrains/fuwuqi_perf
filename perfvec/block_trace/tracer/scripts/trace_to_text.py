#!/usr/bin/env python3
"""
将bbtrace JSONL与静态bb信息拼接成按执行顺序展开的文本。
"""
import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

BBKey = Tuple[int, int]


def load_bbinfo(path: Path) -> Dict[BBKey, dict]:
    mapping: Dict[BBKey, dict] = {}
    with path.open() as fp:
        for line in fp:
            if not line.strip():
                continue
            data = json.loads(line)
            key = (data["func_id"], data["bb_id"])
            mapping[key] = data
    return mapping


def load_addr_map(path: Optional[Path]) -> Dict[BBKey, Dict[str, int]]:
    if not path:
        return {}
    mapping: Dict[BBKey, Dict[str, int]] = {}
    pattern = re.compile(
        r"func_id=(?P<func>\d+)\s+bb_id=(?P<bb>\d+)\s+start_pc=0x(?P<start>[0-9a-fA-F]+)\s+end_pc=0x(?P<end>[0-9a-fA-F]+)"
    )
    with path.open() as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if not match:
                continue
            func_id = int(match.group("func"))
            bb_id = int(match.group("bb"))
            start_pc = int(match.group("start"), 16)
            end_pc = int(match.group("end"), 16)
            mapping[(func_id, bb_id)] = {"start": start_pc, "end": end_pc}
    return mapping


def load_inst_map(path: Optional[Path]) -> Dict[Tuple[int, int, int], int]:
    if not path:
        return {}
    mapping: Dict[Tuple[int, int, int], int] = {}
    pattern = re.compile(
        r"func_id=(?P<func>\d+)\s+bb_id=(?P<bb>\d+)\s+inst_id=(?P<inst>\d+)\s+pc=0x(?P<pc>[0-9a-fA-F]+)"
    )
    with path.open() as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if not match:
                continue
            func = int(match.group("func"))
            bb = int(match.group("bb"))
            inst = int(match.group("inst"))
            pc = int(match.group("pc"), 16)
            mapping[(func, bb, inst)] = pc
    return mapping


def parse_hex(value) -> Optional[int]:
    if isinstance(value, str) and value.startswith("0x"):
        try:
            return int(value, 16)
        except ValueError:
            return None
    return None


class UopAligner:
    def __init__(self, path: Optional[Path], inst_map: Dict[Tuple[int, int, int], int]):
        self.fp = path.open() if path else None
        self.inst_map = inst_map
        self.eof = False
        self.queues: Dict[int, Deque[dict]] = defaultdict(deque)
        self.pc_filter = set(inst_map.values())
        self.present_pcs: Dict[int, bool] = {}
        if self.fp:
            self._build_index()

    @staticmethod
    def _classify_mem(data: dict) -> str:
        text = data.get("uop", "").lower()
        if ": st" in text or " st " in text:
            return "store"
        return "load"

    @staticmethod
    def _parse_hex(value: Optional[str]) -> Optional[int]:
        if not isinstance(value, str):
            return None
        try:
            return int(value, 16)
        except ValueError:
            return None

    def _read_next(self) -> Optional[dict]:
        if not self.fp or self.eof:
            return None
        while True:
            line = self.fp.readline()
            if not line:
                self.eof = True
                return None
            sanitized = line.replace("\t", "\\t")
            try:
                data = json.loads(sanitized)
            except json.JSONDecodeError:
                continue
            if "mem_addr" not in data:
                continue
            pc = self._parse_hex(data.get("pc"))
            addr = self._parse_hex(data.get("mem_addr"))
            if pc is None or addr is None:
                continue
            entry = {
                "pc": pc,
                "addr": addr,
                "size": data.get("mem_size") or 0,
                "kind": self._classify_mem(data),
            }
            return entry

    def _build_index(self) -> None:
        while True:
            entry = self._read_next()
            if entry is None:
                break
            pc = entry["pc"]
            if pc in self.pc_filter:
                self.queues[pc].append(entry)
                self.present_pcs[pc] = True
        self.eof = True
        if self.fp:
            self.fp.close()
            self.fp = None

    def consume(
        self,
        inst_key: Tuple[int, int, int],
        is_store: bool,
        size_hint: Optional[int],
    ) -> Optional[List[str]]:
        target_pc = self.inst_map.get(inst_key)
        if target_pc is None:
            raise RuntimeError(f"missing inst map entry for {inst_key}")
        expected = "store" if is_store else "load"
        total = 0
        addresses: List[str] = []
        dq = self.queues.get(target_pc)
        if not dq:
            return None
        while dq and (not size_hint or total < size_hint or not addresses):
            chunk = dq.popleft()
            if chunk["kind"] != expected:
                continue
            addr = chunk["addr"]
            addresses.append(f"0x{addr:x}")
            size = chunk.get("size") or 0
            if size_hint:
                total += size
            else:
                total = size
            if size == 0:
                break
        if not addresses:
            return None
        return addresses


def convert(trace_path: Path, bbinfo_path: Path, out_path: Path, addr_map_path: Optional[Path],
            inst_map_path: Optional[Path], uop_trace_path: Optional[Path]) -> None:
    bbinfo = load_bbinfo(bbinfo_path)
    addr_map = load_addr_map(addr_map_path)
    inst_map = load_inst_map(inst_map_path)
    if uop_trace_path and not inst_map:
        raise RuntimeError("inst map is required when using μOP trace")
    uop_aligner = UopAligner(uop_trace_path, inst_map) if uop_trace_path else None

    def fmt_addr(value) -> str:
        if value is None:
            return "null"
        if isinstance(value, str):
            return value
        return f"0x{int(value):x}"

    def flush_block(bb_evt: dict, events: List[dict], out_fp) -> None:
        key = (bb_evt.get("func"), bb_evt.get("bb"))
        info = bbinfo.get(key)
        mapped_addr = addr_map.get(key)
        addr = mapped_addr["start"] if mapped_addr else bb_evt.get("bb_addr")
        header = (
            f"=== seq={bb_evt.get('seq')} ts={bb_evt.get('ts_ns')}ns func={key[0]} "
            f"bb={key[1]} loop_hint={bb_evt.get('loop_hint')} addr={fmt_addr(addr)} ==="
        )
        out_fp.write(header + "\n")
        if not info:
            out_fp.write("(missing bb info)\n\n")
            return

        out_fp.write(f"# func_name: {info.get('func_name')} bb_name: {info.get('bb_name')}\n")

        insts = info.get("insts")
        if not insts:
            out_fp.write(info.get("ir", "").rstrip() + "\n\n")
            return

        out_fp.write(info.get("header", f"bb_{key[1]}:") + "\n")

        mem_events: Dict[int, Deque[dict]] = defaultdict(deque)
        branch_events: Dict[int, Deque[dict]] = defaultdict(deque)
        call_events: Dict[int, Deque[dict]] = defaultdict(deque)
        for evt in events:
            if evt.get("event") == "mem":
                mem_events[evt["inst"]].append(evt)
            elif evt.get("event") == "branch":
                branch_events[evt["inst"]].append(evt)
            elif evt.get("event") == "call":
                call_events[evt["inst"]].append(evt)

        for inst in insts:
            line = inst.get("text", "").rstrip()
            comments = []
            kind = inst.get("kind")
            inst_id = inst.get("inst_id")
            if kind in ("load", "store") and inst_id is not None:
                queue = mem_events.get(inst_id)
                if queue:
                    ev = queue.popleft()
                    resolved_addr = ev.get("addr")
                    if uop_aligner:
                        size_hint = ev.get("size")
                        inst_key = (key[0], key[1], inst_id)
                        aligned = uop_aligner.consume(inst_key, ev.get("is_store", False), size_hint)
                        if aligned:
                            if len(aligned) == 1:
                                resolved_addr = aligned[0]
                            else:
                                resolved_addr = "[" + ",".join(aligned) + "]"
                    comments.append(
                        f"addr={resolved_addr} size={ev.get('size')} "
                        f"type={'store' if ev.get('is_store') else 'load'}"
                    )
            if kind == "branch" and inst_id is not None:
                queue = branch_events.get(inst_id)
                if queue:
                    ev = queue.popleft()
                    target_bb = ev.get("target_bb")
                    mapped = None
                    if mapped_addr and target_bb is not None:
                        mapped = addr_map.get((key[0], target_bb))
                    if mapped:
                        comments.append(
                            f"taken_bb={target_bb} taken_addr={fmt_addr(mapped['start'])}"
                        )
                    else:
                        addr = ev.get("target_addr")
                        if addr:
                            comments.append(f"taken_bb={target_bb} taken_addr={addr}")
                        else:
                            comments.append(f"taken_bb={target_bb}")
            if inst.get("targets"):
                comments.append(
                    "targets=[" + ",".join(str(t) for t in inst.get("targets", [])) + "]"
                )
            if kind == "call" and inst_id is not None:
                queue = call_events.get(inst_id)
                if queue:
                    ev = queue.popleft()
                    call_addr = ev.get("call_addr")
                    if call_addr:
                        comments.append(f"call_addr={call_addr}")
                    target = ev.get("target_addr")
                    if target:
                        comments.append(f"call_target={target}")
                    args = ev.get("args") or []
                    if args:
                        arg_parts = []
                        for arg in args:
                            arg_idx = arg.get("idx")
                            arg_kind = arg.get("kind")
                            arg_bits = arg.get("bits")
                            arg_value = arg.get("value")
                            arg_parts.append(
                                f"{arg_idx}:{arg_kind}({arg_bits})={arg_value}"
                            )
                        comments.append("args=[" + ", ".join(arg_parts) + "]")
            if comments:
                line = f"{line}  ; " + ", ".join(comments)
            out_fp.write(line + "\n")

        out_fp.write("\n")

    with trace_path.open() as trace_fp, out_path.open("w") as out_fp:
        current_bb = None
        buffered_events: List[dict] = []
        for line in trace_fp:
            if not line.strip():
                continue
            evt = json.loads(line)
            kind = evt.get("event")
            if kind == "bb":
                if current_bb is not None:
                    flush_block(current_bb, buffered_events, out_fp)
                current_bb = evt
                buffered_events = []
            else:
                if current_bb is not None:
                    buffered_events.append(evt)
        if current_bb is not None:
            flush_block(current_bb, buffered_events, out_fp)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path, help="bbtrace JSONL 路径")
    parser.add_argument("--bbinfo", required=True, type=Path, help="bbinfo jsonl 路径")
    parser.add_argument("--output", required=True, type=Path, help="输出文本")
    parser.add_argument(
        "--addr-map",
        type=Path,
        default=None,
        help="可选：plain 可执行生成的地址映射（extract_pcmap 输出）",
    )
    parser.add_argument(
        "--inst-map",
        type=Path,
        default=None,
        help="可选：plain 可执行的指令 PC 映射（extract_inst_map 输出）",
    )
    parser.add_argument(
        "--uop-trace",
        type=Path,
        default=None,
        help="可选：μOP trace JSONL，用于覆盖 load/store 地址",
    )
    args = parser.parse_args()
    convert(
        args.trace,
        args.bbinfo,
        args.output,
        args.addr_map,
        args.inst_map,
        args.uop_trace,
    )


if __name__ == "__main__":
    main()


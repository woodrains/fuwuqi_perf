#!/usr/bin/env python3
"""
Quick summary utility for bbtrace JSONL files.
"""
import argparse
import collections
import json
from pathlib import Path


def summarize(trace_path: Path) -> None:
    counters = collections.Counter()
    loop_iters = collections.Counter()
    mem_events = collections.Counter()

    with trace_path.open() as fp:
        for line in fp:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("event", "unknown")
            counters[kind] += 1
            if kind == "loop":
                loop_iters[(event.get("func"), event.get("loop"))] = event.get("iter", 0)
            elif kind == "mem":
                mem_events[event.get("is_store", False)] += 1

    print(f"Trace: {trace_path}")
    for kind, count in counters.items():
        print(f"  {kind:>4}: {count}")
    if loop_iters:
        print("  loop iterations (func, loop_id -> last iter index):")
        for key, value in sorted(loop_iters.items()):
            print(f"    {key}: {value}")
    if mem_events:
        print("  memory ops:")
        for is_store, count in mem_events.items():
            label = "store" if is_store else "load"
            print(f"    {label}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="Path to bbtrace-*.jsonl")
    args = parser.parse_args()
    summarize(args.trace)


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""
从最终可执行文件中提取 .bbtrace_map 区段，解析 func_id/bb_id/PC 映射。
当前实现假定目标为 little-endian 64-bit（X86-64/AArch64）。
"""
import argparse
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile


def dump_section(binary: pathlib.Path, llvm_objcopy: pathlib.Path) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = pathlib.Path(tmpdir) / "bbtrace_map.bin"
        cmd = [
            str(llvm_objcopy),
            f"--dump-section",
            f".bbtrace_map={out_path}",
            str(binary),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(exc.stderr.decode("utf-8", errors="ignore"))
            raise
        return out_path.read_bytes()


def parse_entries(blob: bytes):
    entry_size = 16  # 4 bytes func, 4 bytes bb, 8 bytes addr
    if len(blob) % entry_size != 0:
        raise ValueError(f"section size {len(blob)} is not a multiple of {entry_size}")
    fmt = "<IIQ"
    for func_id, bb_id, addr in struct.iter_unpack(fmt, blob):
        yield func_id, bb_id, addr


def get_text_bounds(binary: pathlib.Path, llvm_readelf: pathlib.Path):
    cmd = [
        str(llvm_readelf),
        "--sections",
        "--wide",
        str(binary),
    ]
    proc = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("[") or ".text" not in line:
            continue
        parts = line.split()
        if len(parts) < 6 or parts[1] != ".text":
            continue
        addr = int(parts[3], 16)
        size = int(parts[5], 16)
        return addr, addr + size
    raise RuntimeError("Failed to locate .text section via llvm-readelf")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=pathlib.Path, help="含 .bbtrace_map 的可执行文件/对象")
    parser.add_argument(
        "--llvm-objcopy",
        type=pathlib.Path,
        default=pathlib.Path(shutil.which("llvm-objcopy") or "llvm-objcopy"),
        help="llvm-objcopy 路径",
    )
    parser.add_argument(
        "--llvm-readelf",
        type=pathlib.Path,
        default=pathlib.Path(
            shutil.which("llvm-readelf")
            or shutil.which("llvm-readelf-22")
            or "llvm-readelf"
        ),
        help="llvm-readelf 路径",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=None,
        help="输出文件（默认stdout）",
    )
    args = parser.parse_args()

    blob = dump_section(args.binary, args.llvm_objcopy)
    entries = sorted(parse_entries(blob), key=lambda item: item[2])
    _, text_end = get_text_bounds(args.binary, args.llvm_readelf)

    lines = []
    for idx, (func_id, bb_id, addr) in enumerate(entries):
        if idx + 1 < len(entries):
            end_pc = entries[idx + 1][2]
        else:
            end_pc = text_end
        lines.append(
            f"func_id={func_id}\tbb_id={bb_id}\tstart_pc=0x{addr:016x}\tend_pc=0x{end_pc - 1:016x}"
        )

    if args.output:
        args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main()

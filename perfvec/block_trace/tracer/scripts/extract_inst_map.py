#!/usr/bin/env python3
import argparse
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile


ENTRY_SIZE = 24  # 3 x uint32 + padding + uint64
FMT = "<IIIIQ"


def dump_section(binary: pathlib.Path, llvm_objcopy: pathlib.Path) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = pathlib.Path(tmpdir) / "bbtrace_inst.bin"
        cmd = [
            str(llvm_objcopy),
            "--dump-section",
            f".bbtrace_inst={out_path}",
            str(binary),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(exc.stderr.decode("utf-8", errors="ignore"))
            raise
        return out_path.read_bytes()


def parse_entries(blob: bytes):
    if len(blob) % ENTRY_SIZE != 0:
        raise ValueError(
            f".bbtrace_inst size {len(blob)} is not a multiple of {ENTRY_SIZE}"
        )
    for offset in range(0, len(blob), ENTRY_SIZE):
        func_id, bb_id, inst_id, _reserved, pc = struct.unpack_from(FMT, blob, offset)
        yield func_id, bb_id, inst_id, pc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract (func, bb, inst) -> PC mapping from .bbtrace_inst section"
    )
    parser.add_argument("binary", type=pathlib.Path, help="input executable/object file")
    parser.add_argument(
        "--llvm-objcopy",
        type=pathlib.Path,
        default=pathlib.Path(shutil.which("llvm-objcopy") or "llvm-objcopy"),
        help="path to llvm-objcopy",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=None,
        help="output text file (default stdout)",
    )
    args = parser.parse_args()

    blob = dump_section(args.binary, args.llvm_objcopy)
    if not blob:
        raise SystemExit("missing .bbtrace_inst section")

    lines = []
    for func_id, bb_id, inst_id, pc in parse_entries(blob):
        lines.append(
            f"func_id={func_id}\tbb_id={bb_id}\tinst_id={inst_id}\tpc=0x{pc:016x}"
        )
    text = "\n".join(lines) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()




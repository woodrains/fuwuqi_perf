#!/usr/bin/env python3
"""
使用 QEMU externbb 插件，在用户态模拟阶段捕获不在 pcmap 中的基本块，
并输出它们的反汇编、分支目的地以及首批 load/store 地址。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import shutil
from typing import List
def disable_aslr_prefix() -> List[str]:
    setarch = shutil.which("setarch")
    if not setarch:
        print("externbb: WARNING: 未找到 setarch，无法关闭宿主 ASLR", file=sys.stderr)
        return []
    arch = os.uname().machine
    return [setarch, arch, "-R"]



SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
TRACER_ROOT = SCRIPT_DIR.parent
BLOCK_TRACE_ROOT = TRACER_ROOT.parent
QEMU_ROOT = BLOCK_TRACE_ROOT / "qemu"


def default_qemu_binary() -> pathlib.Path:
    return QEMU_ROOT / "build" / "qemu-x86_64"


def default_plugin_path() -> pathlib.Path:
    return QEMU_ROOT / "build" / "contrib" / "plugins" / "libexternbb.so"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("binary", type=pathlib.Path, help="待运行的可执行文件")
    parser.add_argument(
        "--pcmap",
        type=pathlib.Path,
        required=True,
        help="extract_pcmap.py 导出的 pcmap 文件",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        required=True,
        help="externbb 插件输出日志，使用 - 表示 stdout",
    )
    parser.add_argument(
        "--qemu",
        type=pathlib.Path,
        default=default_qemu_binary(),
        help="带插件支持的 qemu-user 可执行文件",
    )
    parser.add_argument(
        "--plugin",
        type=pathlib.Path,
        default=default_plugin_path(),
        help="libexternbb.so 绝对路径",
    )
    parser.add_argument(
        "--mem-limit",
        type=int,
        default=4,
        help="每条指令记录的 load/store 地址数量；0 表示不记录",
    )
    parser.add_argument(
        "--include-pcmap",
        action="store_true",
        help="让 externbb 也导出 pcmap 覆盖区域（用于拆分 / 合并）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="启用 externbb 的 verbose 模式，输出完整指令",
    )
    parser.add_argument(
        "program_args",
        nargs=argparse.REMAINDER,
        help="传给目标程序的参数（在命令行中以 -- 分隔）",
    )
    return parser


def ensure_exists(path: pathlib.Path, kind: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{kind} 不存在: {path}")


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    binary = args.binary.resolve()
    pcmap = args.pcmap.resolve()
    qemu = args.qemu.resolve()
    plugin = args.plugin.resolve()
    output = args.output if args.output == pathlib.Path("-") else args.output.resolve()

    ensure_exists(binary, "binary")
    ensure_exists(pcmap, "pcmap")
    ensure_exists(qemu, "qemu")
    ensure_exists(plugin, "plugin")

    if output != pathlib.Path("-"):
        output.parent.mkdir(parents=True, exist_ok=True)

    program_args = list(args.program_args)
    if program_args and program_args[0] == "--":
        program_args = program_args[1:]

    include_flag = "on" if args.include_pcmap else "off"
    verbose_flag = "on" if args.verbose else "off"
    plugin_arg = (
        f"{plugin},pcmap={pcmap},out={output},"
        f"mem_limit={max(args.mem_limit, 0)},include_pcmap={include_flag},"
        f"verbose={verbose_flag}"
    )
    prefix = disable_aslr_prefix()
    cmd = [*(prefix or []), str(qemu), "-plugin", plugin_arg, str(binary), *program_args]

    env = os.environ.copy()
    print("运行命令:", " ".join(map(str, cmd)), file=sys.stderr)
    subprocess.run(cmd, check=True, env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


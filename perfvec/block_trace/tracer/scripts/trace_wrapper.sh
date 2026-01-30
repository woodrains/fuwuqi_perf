#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: trace_wrapper.sh [options] [-- program_args...]

Options:
  --src <file>          C/C++ 源文件路径，默认 examples/matmul.c
  --name <name>         任务名称，用于输出目录，默认来源于源文件名
  --build-root <dir>    输出根目录，默认 $PROJECT_ROOT/build/wrapper_runs
  --clang-cflags <str>  传给 clang 的额外 CFLAGS，默认 "-O2 -g"
  --ldflags <str>       额外 LDFLAGS，默认 "-lstdc++ -lpthread -ldl"
  --gem5-config <file>  自定义 gem5 配置脚本，默认 GEM5/configs/deprecated/example/se.py
  --gem5-cpu-type <t>   gem5 CPU 类型，默认 TimingSimpleCPU
  --gem5-sys-clock <c>  gem5 --sys-clock，默认 1GHz
  --gem5-cpu-clock <c>  gem5 --cpu-clock，默认 2GHz
  --gem5-extra-arg <a>  追加原样 gem5 参数，可重复（如 --param=system.cpu.fetchWidth=8）
  --no-uop-sort         不对 μOP trace 按 PC 重排序（默认排序）
  --help                显示本提示

`--` 之后的参数会原样传给目标程序。

脚本会：
  1. 先对 bitcode 运行 `bb-trace -bbtrace-static-only`，得到“无插桩但带完整静态信息/pcmap”的版本；
  2. 再运行常规 `bb-trace`，生成插桩版本以采集动态 JSONL；
  3. 将两份可执行、运行日志、bbinfo、pcmap 以及 `bbtrace_ordered_trace/full`、`address_diff.json` 汇总输出。
EOF
}

PROJECT_ROOT="/home/chiplab/PRL/PerfVec/block_trace/tracer"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BLOCK_TRACE_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"
REPO_ROOT="$(cd "${BLOCK_TRACE_ROOT}/.." && pwd)"

LLVM_HOME="${LLVM_HOME:-}"
if [[ -z "${LLVM_HOME}" ]]; then
  if [[ -d "${BLOCK_TRACE_ROOT}/llvm-install" ]]; then
    LLVM_HOME="${BLOCK_TRACE_ROOT}/llvm-install"
  elif [[ -d "/usr/lib/llvm-22" ]]; then
    LLVM_HOME="/usr/lib/llvm-22"
  else
    echo "[trace-wrapper] ERROR: LLVM 未找到；请设置 LLVM_HOME 或安装 LLVM (推荐 /usr/lib/llvm-22)" >&2
    exit 1
  fi
fi

BUILD_DIR="${PROJECT_ROOT}/build"
RUNTIME_LIB="${BUILD_DIR}/runtime/libbbtrace_runtime.a"
PASS_LIB="${BUILD_DIR}/passes/libBasicBlockTracer.so"

detect_gem5_root() {
  if [[ -f "${BLOCK_TRACE_ROOT}/gem5/SConstruct" ]]; then
    echo "${BLOCK_TRACE_ROOT}/gem5"
    return 0
  fi
  if [[ -f "${REPO_ROOT}/gem5-ml-sim/SConstruct" ]]; then
    echo "${REPO_ROOT}/gem5-ml-sim"
    return 0
  fi
  if [[ -f "/root/gem5-ml-sim/SConstruct" ]]; then
    echo "/root/gem5-ml-sim"
    return 0
  fi
  return 1
}

GEM5_ROOT="${GEM5_ROOT:-$(detect_gem5_root || true)}"
if [[ -z "${GEM5_ROOT}" ]]; then
  echo "[trace-wrapper] ERROR: 未找到 gem5 目录；请设置 GEM5_ROOT 指向 gem5 源码目录（需要含 SConstruct）" >&2
  exit 1
fi

GEM5_BIN="${GEM5_BIN:-${GEM5_ROOT}/build/X86/gem5.fast}"
GEM5_CONFIG="${GEM5_CONFIG:-${GEM5_ROOT}/configs/deprecated/example/se.py}"

GEM5_PYTHON_LIB="${GEM5_PYTHON_LIB:-}"
if [[ -z "${GEM5_PYTHON_LIB}" ]]; then
  if [[ -n "${CONDA_PREFIX:-}" && -d "${CONDA_PREFIX}/lib" ]]; then
    GEM5_PYTHON_LIB="${CONDA_PREFIX}/lib"
  else
    GEM5_PYTHON_LIB="$(python3 -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")' 2>/dev/null || true)"
  fi
fi

if [[ -n "${GEM5_PYTHON_LIB}" && -d "${GEM5_PYTHON_LIB}" ]]; then
  if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    GEM5_DEFAULT_LD="${GEM5_PYTHON_LIB}:${LD_LIBRARY_PATH}"
  else
    GEM5_DEFAULT_LD="${GEM5_PYTHON_LIB}"
  fi
else
  GEM5_DEFAULT_LD="${LD_LIBRARY_PATH:-}"
fi
GEM5_LD_LIBRARY_PATH="${GEM5_LD_LIBRARY_PATH:-${GEM5_DEFAULT_LD}}"
GEM5_CPU_TYPE="TimingSimpleCPU"
GEM5_SYS_CLOCK="1GHz"
GEM5_CPU_CLOCK="2GHz"
GEM5_EXTRA_ARGS=()
UOP_SORT=1

DEFAULT_SRC="${PROJECT_ROOT}/examples/matmul.c"
SOURCE="${DEFAULT_SRC}"
TASK_NAME=""
OUTPUT_ROOT="${BUILD_DIR}/wrapper_runs"
CLANG_CFLAGS="-O2 -g -fno-pie -no-pie"
EXTRA_LDFLAGS="-lstdc++ -lpthread -ldl"
PROGRAM_ARGS=()
QEMU_VERBOSE=0
RUN_NO_ASLR=()
if command -v setarch >/dev/null 2>&1; then
  if setarch "$(uname -m)" -R true >/dev/null 2>&1; then
    RUN_NO_ASLR=(setarch "$(uname -m)" -R)
  else
    echo "[trace-wrapper] WARNING: setarch 存在但无法关闭 ASLR（可能被容器/安全策略禁用），将继续运行" >&2
  fi
else
  echo "[trace-wrapper] WARNING: setarch 未找到，运行阶段无法关闭 ASLR" >&2
fi

run_no_aslr() {
  if [[ ${#RUN_NO_ASLR[@]} -gt 0 ]]; then
    "${RUN_NO_ASLR[@]}" "$@"
  else
    "$@"
  fi
}

run_host_cmd() {
  local saved_ld="${LD_LIBRARY_PATH-__UNSET__}"
  unset LD_LIBRARY_PATH
  "$@"
  local status=$?
  if [[ "${saved_ld}" == "__UNSET__" ]]; then
    unset LD_LIBRARY_PATH
  else
    export LD_LIBRARY_PATH="${saved_ld}"
  fi
  return ${status}
}

run_gem5_sim() {
  local log_file="$1"
  shift
  set +e
  (
    cd "${GEM5_ROOT}" && \
    env LD_LIBRARY_PATH="${GEM5_LD_LIBRARY_PATH}" "${GEM5_BIN}" "$@"
  ) | tee "${log_file}"
  local status=${PIPESTATUS[0]}
  set -e
  if [[ ${status} -ne 0 ]]; then
    echo "[trace-wrapper] gem5.fast 运行失败，日志: ${log_file}" >&2
    exit ${status}
  fi
}


while [[ $# -gt 0 ]]; do
  case "$1" in
    --src)
      SOURCE="$2"; shift 2;;
    --name)
      TASK_NAME="$2"; shift 2;;
    --build-root)
      OUTPUT_ROOT="$2"; shift 2;;
    --clang-cflags)
      CLANG_CFLAGS="$2"; shift 2;;
    --ldflags)
      EXTRA_LDFLAGS="$2"; shift 2;;
    --gem5-config)
      GEM5_CONFIG="$2"; shift 2;;
    --gem5-cpu-type)
      GEM5_CPU_TYPE="$2"; shift 2;;
    --gem5-sys-clock)
      GEM5_SYS_CLOCK="$2"; shift 2;;
    --gem5-cpu-clock)
      GEM5_CPU_CLOCK="$2"; shift 2;;
    --gem5-extra-arg)
      GEM5_EXTRA_ARGS+=("$2"); shift 2;;
    --no-uop-sort)
      UOP_SORT=0; shift;;
    --qemu-verbose)
      QEMU_VERBOSE=1; shift;;
    --help)
      usage; exit 0;;
    --)
      shift
      PROGRAM_ARGS=("$@")
      break;;
    *)
      echo "[trace-wrapper] 未知参数: $1" >&2
      usage
      exit 1;;
  esac
done

if [[ ! -f "${SOURCE}" ]]; then
  echo "[trace-wrapper] 源文件不存在: ${SOURCE}" >&2
  exit 1
fi

if [[ -z "${TASK_NAME}" ]]; then
  TASK_NAME="$(basename "${SOURCE}")"
  TASK_NAME="${TASK_NAME%.*}"
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RUN_ROOT="${OUTPUT_ROOT}/${TASK_NAME}/${TIMESTAMP}"
TRACE_DIR="${RUN_ROOT}/with_trace"
PLAIN_DIR="${RUN_ROOT}/without_trace"
QEMU_DIR="${RUN_ROOT}/qemu_runtime"
mkdir -p "${TRACE_DIR}" "${PLAIN_DIR}" "${QEMU_DIR}"

export PATH="${LLVM_HOME}/bin:${PATH}"

BITCODE="${RUN_ROOT}/${TASK_NAME}.bc"
PLAIN_BC="${RUN_ROOT}/${TASK_NAME}.plain.bc"
TRACED_BC="${RUN_ROOT}/${TASK_NAME}.traced.bc"
TRACED_BIN="${TRACE_DIR}/${TASK_NAME}_traced"
PLAIN_BIN="${PLAIN_DIR}/${TASK_NAME}_plain"
TRACE_LOG_DIR="${TRACE_DIR}/trace_logs"
ORDERED_TRACE_TRACE="${TRACE_DIR}/bbtrace_ordered_trace.txt"
ORDERED_TRACE_FULL="${TRACE_DIR}/bbtrace_ordered_full.txt"
PCMAP_TRACE_FILE="${TRACE_DIR}/${TASK_NAME}_traced.pcmap"
PCMAP_PLAIN_FILE="${PLAIN_DIR}/${TASK_NAME}_plain.pcmap"
INSTMAP_PLAIN_FILE="${PLAIN_DIR}/${TASK_NAME}_plain.instmap"
TRACE_STDOUT_LOG="${TRACE_DIR}/program_stdout.log"
PLAIN_STDOUT_LOG="${PLAIN_DIR}/program_stdout.log"
TRACE_BBINFO_EXPORT="${TRACE_DIR}/bbtrace_static_export"
PLAIN_BBINFO_EXPORT="${PLAIN_DIR}/bbtrace_static_export"
SYMBOL_DIFF_JSON="${RUN_ROOT}/address_diff.json"
QEMU_STDOUT_LOG="${QEMU_DIR}/program_stdout.log"
QEMU_EXTERNAL_BB="${QEMU_DIR}/${TASK_NAME}_externbb.txt"
QEMU_EXTERNAL_BB_FULL="${QEMU_DIR}/${TASK_NAME}_externbb_full.txt"
GEM5_DIR="${RUN_ROOT}/gem5_runtime"
GEM5_TRACED_OUT="${GEM5_DIR}/with_trace"
GEM5_PLAIN_OUT="${GEM5_DIR}/without_trace"
UOP_TRACE_DIR="${GEM5_PLAIN_OUT}/uop_trace"
if [[ ! -x "${GEM5_BIN}" ]]; then
  echo "[trace-wrapper] ERROR: 未找到 gem5.fast (${GEM5_BIN})" >&2
  exit 1
fi

echo "[trace-wrapper] 源码: ${SOURCE}"
echo "[trace-wrapper] 输出目录: ${RUN_ROOT}"

echo "[trace-wrapper] 1/8: clang 生成 bitcode..."
mkdir -p "$(dirname "${BITCODE}")"
run_host_cmd clang ${CLANG_CFLAGS} -emit-llvm -c "${SOURCE}" -o "${BITCODE}"

echo "[trace-wrapper] 2/8: 运行 bb-trace (static-only) 生成无插桩版本..."
BBTRACE_STATIC_ONLY=1 run_host_cmd opt -load-pass-plugin "${PASS_LIB}" -passes=bb-trace \
  "${BITCODE}" -o "${PLAIN_BC}"
PLAIN_BBINFO_DIR="$(dirname "${BITCODE}")/bbtrace_static"
if [[ -d "${PLAIN_BBINFO_DIR}" ]]; then
  rm -rf "${PLAIN_BBINFO_EXPORT}"
  cp -r "${PLAIN_BBINFO_DIR}" "${PLAIN_BBINFO_EXPORT}"
  echo "[trace-wrapper] plain bbinfo 导出到 ${PLAIN_BBINFO_EXPORT}"
  rm -rf "${PLAIN_BBINFO_DIR}"
else
  echo "[trace-wrapper] WARNING: 未找到 plain bbtrace_static (${PLAIN_BBINFO_DIR})" >&2
fi

echo "[trace-wrapper] 3/8: 构建 & 运行无插桩可执行..."
run_host_cmd clang ${CLANG_CFLAGS} "${PLAIN_BC}" ${EXTRA_LDFLAGS} -o "${PLAIN_BIN}"
set +e
run_no_aslr "${PLAIN_BIN}" "${PROGRAM_ARGS[@]}" | tee "${PLAIN_STDOUT_LOG}"
PLAIN_STATUS=${PIPESTATUS[0]}
set -e
if [[ ${PLAIN_STATUS} -ne 0 ]]; then
  echo "[trace-wrapper] 无插桩版本运行失败，退出码 ${PLAIN_STATUS}" >&2
  exit ${PLAIN_STATUS}
fi

echo "[trace-wrapper] 4/8: 生成插桩版本并运行..."
run_host_cmd opt -load-pass-plugin "${PASS_LIB}" -passes=bb-trace "${BITCODE}" -o "${TRACED_BC}"
TRACE_BBINFO_DIR="$(dirname "${BITCODE}")/bbtrace_static"
if [[ -d "${TRACE_BBINFO_DIR}" ]]; then
  rm -rf "${TRACE_BBINFO_EXPORT}"
  cp -r "${TRACE_BBINFO_DIR}" "${TRACE_BBINFO_EXPORT}"
  echo "[trace-wrapper] traced bbinfo 导出到 ${TRACE_BBINFO_EXPORT}"
else
  echo "[trace-wrapper] WARNING: 未找到 traced bbtrace_static (${TRACE_BBINFO_DIR})" >&2
fi

run_host_cmd clang ${CLANG_CFLAGS} "${TRACED_BC}" "${RUNTIME_LIB}" ${EXTRA_LDFLAGS} -o "${TRACED_BIN}"
export BBTRACE_OUT_DIR="${TRACE_LOG_DIR}"
mkdir -p "${TRACE_LOG_DIR}"
set +e
run_no_aslr "${TRACED_BIN}" "${PROGRAM_ARGS[@]}" | tee "${TRACE_STDOUT_LOG}"
TRACE_STATUS=${PIPESTATUS[0]}
set -e
if [[ ${TRACE_STATUS} -ne 0 ]]; then
  echo "[trace-wrapper] 插桩版本运行失败，退出码 ${TRACE_STATUS}" >&2
  exit ${TRACE_STATUS}
fi

TRACE_FILE="$(ls -1t "${TRACE_LOG_DIR}"/bbtrace-*.jsonl 2>/dev/null | head -n 1 || true)"
if [[ -z "${TRACE_FILE}" ]]; then
  echo "[trace-wrapper] 未找到 JSONL trace，检查 BBTRACE_OUT_DIR" >&2
  exit 1
fi
echo "[trace-wrapper] JSONL trace: ${TRACE_FILE}"

PLAIN_BBINFO_FILE="$(ls -1 "${PLAIN_BBINFO_EXPORT}"/*.jsonl 2>/dev/null | head -n 1 || true)"
TRACE_BBINFO_FILE="$(ls -1 "${TRACE_BBINFO_EXPORT}"/*.jsonl 2>/dev/null | head -n 1 || true)"
if [[ -z "${PLAIN_BBINFO_FILE}" || -z "${TRACE_BBINFO_FILE}" ]]; then
  echo "[trace-wrapper] ERROR: bbinfo 不完整（plain=${PLAIN_BBINFO_FILE}, trace=${TRACE_BBINFO_FILE})" >&2
  exit 1
fi

echo "[trace-wrapper] 5/8: 生成 bbtrace_ordered_trace..."
run_host_cmd python3 "${PROJECT_ROOT}/scripts/trace_to_text.py" \
  --trace "${TRACE_FILE}" \
  --bbinfo "${TRACE_BBINFO_FILE}" \
  --output "${ORDERED_TRACE_TRACE}"

echo "[trace-wrapper] 6/8: 导出 pcmap（trace/plain）..."
run_host_cmd python3 "${PROJECT_ROOT}/scripts/extract_pcmap.py" "${TRACED_BIN}" --output "${PCMAP_TRACE_FILE}"
run_host_cmd python3 "${PROJECT_ROOT}/scripts/extract_pcmap.py" "${PLAIN_BIN}" --output "${PCMAP_PLAIN_FILE}"
run_host_cmd python3 "${PROJECT_ROOT}/scripts/extract_inst_map.py" "${PLAIN_BIN}" --output "${INSTMAP_PLAIN_FILE}"

GEM5_OPTION_STRING=""
if [[ ${#PROGRAM_ARGS[@]} -gt 0 ]]; then
  GEM5_OPTION_STRING="$(printf "%q " "${PROGRAM_ARGS[@]}")"
  GEM5_OPTION_STRING="${GEM5_OPTION_STRING% }"
fi

mkdir -p "${GEM5_TRACED_OUT}" "${GEM5_PLAIN_OUT}" "${UOP_TRACE_DIR}"
GEM5_TRACE_LOG="${GEM5_TRACED_OUT}/gem5_stdout.log"
GEM5_PLAIN_LOG="${GEM5_PLAIN_OUT}/gem5_stdout.log"
UOP_TRACE_FILE="${UOP_TRACE_DIR}/${TASK_NAME}_plain_uops.jsonl"

GEM5_COMMON_ENV="${GEM5_DIR}/common.env"
cat > "${GEM5_COMMON_ENV}" <<'EOF'
MALLOC_MMAP_THRESHOLD_=268435456
MALLOC_TRIM_THRESHOLD_=-1
MALLOC_TOP_PAD_=0
MALLOC_ARENA_MAX=1
EOF

GEM5_TRACED_ENV="${GEM5_TRACED_OUT}/process.env"
GEM5_TRACE_LOG_DIR="${GEM5_TRACED_OUT}/trace_logs"
mkdir -p "${GEM5_TRACE_LOG_DIR}"
cp "${GEM5_COMMON_ENV}" "${GEM5_TRACED_ENV}"
cat >> "${GEM5_TRACED_ENV}" <<EOF
BBTRACE_OUT_DIR=${GEM5_TRACE_LOG_DIR}
EOF

echo "[trace-wrapper] 7/8: gem5.fast 运行 LLVM trace 版本（无 μOP 导出）..."
GEM5_TRACED_ARGS=(
  --outdir "${GEM5_TRACED_OUT}"
  "${GEM5_CONFIG}"
  --cmd "${TRACED_BIN}"
  --cpu-type="${GEM5_CPU_TYPE}"
  --sys-clock="${GEM5_SYS_CLOCK}"
  --cpu-clock="${GEM5_CPU_CLOCK}"
  --env "${GEM5_TRACED_ENV}"
)
if [[ ${#GEM5_EXTRA_ARGS[@]} -gt 0 ]]; then
  GEM5_TRACED_ARGS+=("${GEM5_EXTRA_ARGS[@]}")
fi
if [[ -n "${GEM5_OPTION_STRING}" ]]; then
  GEM5_TRACED_ARGS+=(--options "${GEM5_OPTION_STRING}")
fi
run_gem5_sim "${GEM5_TRACE_LOG}" "${GEM5_TRACED_ARGS[@]}"
GEM5_TRACE_FILE="$(ls -1t "${GEM5_TRACE_LOG_DIR}"/bbtrace-*.jsonl 2>/dev/null | head -n 1 || true)"
if [[ -z "${GEM5_TRACE_FILE}" ]]; then
  echo "[trace-wrapper] ERROR: gem5 traced 运行未生成 JSONL trace" >&2
  exit 1
fi

echo "[trace-wrapper] 8/8: gem5.fast 运行无 LLVM trace 版本（导出 μOP）..."
GEM5_PLAIN_ENV="${GEM5_PLAIN_OUT}/process.env"
cp "${GEM5_COMMON_ENV}" "${GEM5_PLAIN_ENV}"

GEM5_PLAIN_ARGS=(
  --outdir "${GEM5_PLAIN_OUT}"
  "${GEM5_CONFIG}"
  --cmd "${PLAIN_BIN}"
  --cpu-type="${GEM5_CPU_TYPE}"
  --sys-clock="${GEM5_SYS_CLOCK}"
  --cpu-clock="${GEM5_CPU_CLOCK}"
  --env "${GEM5_PLAIN_ENV}"
  --uop-trace-path "${UOP_TRACE_FILE}"
  --uop-trace-buffer 8GB
)
if [[ ${#GEM5_EXTRA_ARGS[@]} -gt 0 ]]; then
  GEM5_PLAIN_ARGS+=("${GEM5_EXTRA_ARGS[@]}")
fi
if [[ -n "${GEM5_OPTION_STRING}" ]]; then
  GEM5_PLAIN_ARGS+=(--options "${GEM5_OPTION_STRING}")
fi
run_gem5_sim "${GEM5_PLAIN_LOG}" "${GEM5_PLAIN_ARGS[@]}"

UOP_TRACE_UNSORTED="${UOP_TRACE_FILE}.unsorted"
UOP_TRACE_SORTED="${UOP_TRACE_FILE}.pc_sorted"
mv "${UOP_TRACE_FILE}" "${UOP_TRACE_UNSORTED}"

if [[ ${UOP_SORT} -eq 1 ]]; then
  echo "[trace-wrapper] μOP trace 按 PC 重排序..."
  run_host_cmd python3 "${PROJECT_ROOT}/scripts/sort_uop_trace.py" \
    --input "${UOP_TRACE_UNSORTED}" \
    --output "${UOP_TRACE_SORTED}"
  UOP_TRACE_FILE="${UOP_TRACE_SORTED}"
else
  UOP_TRACE_FILE="${UOP_TRACE_UNSORTED}"
fi

echo "[trace-wrapper] 补充：生成 bbtrace_ordered_full（按 plain 地址+μOP）..."
run_host_cmd python3 "${PROJECT_ROOT}/scripts/trace_to_text.py" \
  --trace "${GEM5_TRACE_FILE}" \
  --bbinfo "${TRACE_BBINFO_FILE}" \
  --addr-map "${PCMAP_PLAIN_FILE}" \
  --inst-map "${INSTMAP_PLAIN_FILE}" \
  --uop-trace "${UOP_TRACE_FILE}" \
  --output "${ORDERED_TRACE_FULL}"

echo "[trace-wrapper] 附加：比较符号地址..."

echo "[trace-wrapper] 8/9: 比较符号地址..."
TRACED_NM="${TRACE_DIR}/symbols_traced.txt"
PLAIN_NM="${PLAIN_DIR}/symbols_plain.txt"
run_host_cmd llvm-nm -n "${TRACED_BIN}" > "${TRACED_NM}"
run_host_cmd llvm-nm -n "${PLAIN_BIN}" > "${PLAIN_NM}"
run_host_cmd python3 - <<'PY' "${TRACED_NM}" "${PLAIN_NM}" "${SYMBOL_DIFF_JSON}"
import json
import sys

def parse(path):
    table = {}
    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            addr, sym_type, name = parts[0], parts[1], parts[2]
            if sym_type.lower() != "t":
                continue
            try:
                value = int(addr, 16)
            except ValueError:
                continue
            table[name] = value
    return table

trace_sym = parse(sys.argv[1])
plain_sym = parse(sys.argv[2])
diffs = []
for name in sorted(set(trace_sym) & set(plain_sym)):
    if trace_sym[name] != plain_sym[name]:
        diffs.append(
            {
                "symbol": name,
                "traced": hex(trace_sym[name]),
                "plain": hex(plain_sym[name]),
                "delta": hex(trace_sym[name] - plain_sym[name]),
            }
        )

result = {
    "trace_symbol_count": len(trace_sym),
    "plain_symbol_count": len(plain_sym),
    "diff_count": len(diffs),
    "diffs": diffs[:100],
    "note": "只比较了符号 (type=T/t)，bb 级别地址仍需结合 pcmap/IR。",
}
with open(sys.argv[3], "w", encoding="utf-8") as fp:
    json.dump(result, fp, indent=2)
PY

: <<'QEMU_DISABLED'
echo "[trace-wrapper] 9/9: 运行 QEMU externbb..."
QEMU_VERBOSE_ARGS=()
if [[ ${QEMU_VERBOSE} -eq 1 ]]; then
  QEMU_VERBOSE_ARGS+=(--verbose)
fi
set +e
python3 "${PROJECT_ROOT}/scripts/dump_external_bb.py" \
  --pcmap "${PCMAP_TRACE_FILE}" \
  --include-pcmap \
  "${QEMU_VERBOSE_ARGS[@]}" \
  --output "${QEMU_EXTERNAL_BB}" \
  -- "${TRACED_BIN}" "${PROGRAM_ARGS[@]}" | tee "${QEMU_STDOUT_LOG}"
QEMU_STATUS=${PIPESTATUS[0]}

EMPTY_PCMAP_FOR_FULL="${QEMU_DIR}/externbb_full_empty.pcmap"
: > "${EMPTY_PCMAP_FOR_FULL}"
python3 "${PROJECT_ROOT}/scripts/dump_external_bb.py" \
  --pcmap "${EMPTY_PCMAP_FOR_FULL}" \
  "${QEMU_VERBOSE_ARGS[@]}" \
  --output "${QEMU_EXTERNAL_BB_FULL}" \
  -- "${TRACED_BIN}" "${PROGRAM_ARGS[@]}" | tee -a "${QEMU_STDOUT_LOG}"
QEMU_FULL_STATUS=${PIPESTATUS[0]}
rm -f "${EMPTY_PCMAP_FOR_FULL}"
set -e
if [[ ${QEMU_STATUS} -ne 0 || ${QEMU_FULL_STATUS} -ne 0 ]]; then
  echo "[trace-wrapper] QEMU externbb 运行失败，退出码 ${QEMU_STATUS}/${QEMU_FULL_STATUS}" >&2
  exit 1
fi

echo "[trace-wrapper] QEMU externbb: ${QEMU_EXTERNAL_BB}"
echo "[trace-wrapper] QEMU externbb(full): ${QEMU_EXTERNAL_BB_FULL}"
QEMU_DISABLED

echo "[trace-wrapper] 任务完成。"
echo "[trace-wrapper] 插桩输出: ${TRACE_DIR}"
echo "[trace-wrapper] 无插桩输出: ${PLAIN_DIR}"
echo "[trace-wrapper] gem5 traced 输出: ${GEM5_TRACED_OUT}"
echo "[trace-wrapper] gem5 plain 输出: ${GEM5_PLAIN_OUT}"
echo "[trace-wrapper] μOP trace: ${UOP_TRACE_FILE}"
echo "[trace-wrapper] 符号差异: ${SYMBOL_DIFF_JSON}"
echo "[trace-wrapper] QEMU externbb 流程暂时已禁用。"

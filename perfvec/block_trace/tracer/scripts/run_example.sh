#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BLOCK_TRACE_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"
BUILD_DIR="${PROJECT_ROOT}/build"

LLVM_HOME="${LLVM_HOME:-}"
if [[ -z "${LLVM_HOME}" ]]; then
  if [[ -d "${BLOCK_TRACE_ROOT}/llvm-install" ]]; then
    LLVM_HOME="${BLOCK_TRACE_ROOT}/llvm-install"
  elif [[ -d "/usr/lib/llvm-22" ]]; then
    LLVM_HOME="/usr/lib/llvm-22"
  else
    echo "[bbtrace] ERROR: LLVM 未找到；请设置 LLVM_HOME 或安装 LLVM (推荐 /usr/lib/llvm-22)" >&2
    exit 1
  fi
fi

EXAMPLE_SRC="${PROJECT_ROOT}/examples/matmul.c"
EXAMPLE_BUILD="${BUILD_DIR}/examples"

export PATH="${LLVM_HOME}/bin:${PATH}"

mkdir -p "${EXAMPLE_BUILD}"

clang -O1 -g -emit-llvm -c "${EXAMPLE_SRC}" -o "${EXAMPLE_BUILD}/matmul.bc"

opt -load-pass-plugin "${BUILD_DIR}/passes/libBasicBlockTracer.so" \
  -passes=bb-trace \
  "${EXAMPLE_BUILD}/matmul.bc" \
  -o "${EXAMPLE_BUILD}/matmul.traced.bc"

BBINFO_DIR="${EXAMPLE_BUILD}/bbtrace_static"
BBINFO_FILE="${BBINFO_DIR}/matmul.bc.bbinfo.jsonl"

clang "${EXAMPLE_BUILD}/matmul.traced.bc" \
  "${BUILD_DIR}/runtime/libbbtrace_runtime.a" \
  -lstdc++ \
  -lpthread \
  -ldl \
  -o "${EXAMPLE_BUILD}/matmul_traced"

export BBTRACE_OUT_DIR="${EXAMPLE_BUILD}/trace"
mkdir -p "${BBTRACE_OUT_DIR}"

echo "[bbtrace] running instrumented binary..."
"${EXAMPLE_BUILD}/matmul_traced"

TRACE_FILE=$(ls -1t "${BBTRACE_OUT_DIR}"/bbtrace-*.jsonl | head -n 1)
echo "[bbtrace] latest trace: ${TRACE_FILE}"
head -n 5 "${TRACE_FILE}"

TEXT_TRACE="${BBTRACE_OUT_DIR}/bbtrace_ordered.txt"
if [[ -f "${BBINFO_FILE}" ]]; then
  "${PROJECT_ROOT}/scripts/trace_to_text.py" \
    --trace "${TRACE_FILE}" \
    --bbinfo "${BBINFO_FILE}" \
    --output "${TEXT_TRACE}"
  echo "[bbtrace] ordered bb trace: ${TEXT_TRACE}"
  head -n 20 "${TEXT_TRACE}"
else
  echo "[bbtrace] warning: bbinfo file not found at ${BBINFO_FILE}"
fi

PCMAP_FILE="${EXAMPLE_BUILD}/matmul_traced.pcmap"
"${PROJECT_ROOT}/scripts/extract_pcmap.py" \
  "${EXAMPLE_BUILD}/matmul_traced" \
  --output "${PCMAP_FILE}"
echo "[bbtrace] pc -> bb map: ${PCMAP_FILE}"
head -n 5 "${PCMAP_FILE}"

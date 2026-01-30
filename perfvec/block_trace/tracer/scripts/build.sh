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

CMAKE_ARGS=(
  "-DLLVM_INSTALL_PREFIX=${LLVM_HOME}"
)
if [[ -x "${LLVM_HOME}/bin/clang" && -x "${LLVM_HOME}/bin/clang++" ]]; then
  CMAKE_ARGS+=(
    "-DCMAKE_C_COMPILER=${LLVM_HOME}/bin/clang"
    "-DCMAKE_CXX_COMPILER=${LLVM_HOME}/bin/clang++"
  )
fi

cmake -S "${PROJECT_ROOT}" -B "${BUILD_DIR}" "${CMAKE_ARGS[@]}"
cmake --build "${BUILD_DIR}" -j"$(nproc)"

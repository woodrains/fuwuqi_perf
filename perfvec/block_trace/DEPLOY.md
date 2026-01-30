# Block Trace 共享与部署指引

> 入口脚本：`block_trace/tracer/scripts/trace_wrapper.sh`

本指南汇总仓库结构、推送到 GitHub 的做法，以及在新环境下复现 gem5 + LLVM + tracer 的步骤。当前 LLVM 使用官方源码，需锁定指定 commit 以保证可重复。

## 仓库拆分与推荐结构

- 主仓（建议新建 `ArchCangyuan/perfvec`）：保留 `DP/ML/CFG/DA` 主体代码、`block_trace/tracer`、脚本与文档。
- gem5 修改版（建议新建 `ArchCangyuan/gem5-ml-sim`）：对应 `block_trace/gem5`，包含 `MicroOpVerboseTracer` 等改动，作为主仓子模块。
  ```bash
  git submodule add git@github.com:ArchCangyuan/gem5-ml-sim.git block_trace/gem5
  ```
  如目录已被追踪，先 `git rm -r --cached block_trace/gem5` 再添加子模块。
- LLVM 使用官方源码，无需单独仓库：保留 `block_trace/llvm-project` 作为本地源码目录，安装前缀放在 `block_trace/llvm-install`（不入库）。
  - 当前固定官方 commit：`0a03b7e6569ae89d55c9703faedf8e2503bcc728`
  - 建议将此哈希写入 `block_trace/LLVM_COMMIT.txt` 并提交到主仓，便于协作者对齐环境。
- `.gitignore` 建议忽略：`block_trace/llvm-install/`、`block_trace/tracer/build/`、`block_trace/gem5/build*/`、`m5out/`、`**/__pycache__/`。

## 推送示例命令（按模块）

> 下面命令仅供参考，无需现在执行。

### gem5
```bash
cd /home/chiplab/PRL/PerfVec/block_trace/gem5
git remote add mine git@github.com:ArchCangyuan/gem5-ml-sim.git
git push mine HEAD:main            # 或保持原分支名
```

### 主仓
```bash
cd /home/chiplab/PRL/PerfVec
git remote add mine git@github.com:ArchCangyuan/perfvec.git
git submodule update --init --recursive
git add .gitmodules block_trace/gem5
echo 0a03b7e6569ae89d55c9703faedf8e2503bcc728 > block_trace/LLVM_COMMIT.txt
git add block_trace/LLVM_COMMIT.txt <其它需要的文件>
git commit -m "Add block trace pipeline with gem5 submodule"
git push mine HEAD:main
```

## 依赖准备

- 系统：Ubuntu 20.04+（示例环境 Linux 6.8）
- 基础工具：`build-essential cmake ninja-build python3 python3-pip git`
- 可选：`setarch`（trace_wrapper 关闭 ASLR），`conda`/`virtualenv`
- Python 依赖：`pip install -r block_trace/tracer/requirements.txt`（如存在）

## 构建流程

0) **确保 LLVM 官方源码在指定 commit**  
```bash
cd block_trace/llvm-project
git fetch origin
git checkout 0a03b7e6569ae89d55c9703faedf8e2503bcc728
git rev-parse HEAD > ../LLVM_COMMIT.txt
```

1) **LLVM（安装到 `block_trace/llvm-install`）**  
```bash
cd block_trace/llvm-project
mkdir -p build-release && cd build-release
cmake -G Ninja -DLLVM_ENABLE_PROJECTS="clang;lld;mlir" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=../llvm-install \
  ../llvm
ninja -j$(nproc)
ninja install
```

2) **Tracer pass + runtime**  
```bash
cd /home/chiplab/PRL/PerfVec/block_trace/tracer
./scripts/build.sh    # 使用上一步 LLVM 安装前缀
```

3) **gem5（启用 MicroOpVerboseTracer）**  
```bash
cd /home/chiplab/PRL/PerfVec/block_trace/gem5
scons build/X86/gem5.fast -j$(nproc)
```

## 运行示例（trace_wrapper 入口）

```bash
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/trace_wrapper.sh \
  --src /home/chiplab/PRL/PerfVec/block_trace/tracer/examples/matmul.c \
  --name matmul_demo
```

输出目录位于 `block_trace/tracer/build/wrapper_runs/<name>/<timestamp>/`，包含：
- `with_trace/`：插桩版本二进制、JSONL、`bbtrace_ordered_trace.txt`
- `without_trace/`：无插桩二进制
- `gem5_runtime/with_trace|without_trace`：gem5 日志、μOP trace
- `bbtrace_ordered_full.txt`、`address_diff.json`：用于对齐无插桩地址

## 更新子模块与依赖的日常流程

```bash
# 拉取主仓和子模块最新代码
git pull --recurse-submodules
git submodule update --init --recursive

# 子模块（gem5）内部开发
cd block_trace/gem5
git checkout -b feature/x
# ...修改...
git commit -am "feat: micro-op tracer tweak"
git push mine HEAD:feature/x
```

## 典型目录说明

- `block_trace/tracer/scripts/trace_wrapper.sh`：完整采集与对齐入口
- `block_trace/tracer/build/`：pass/runtime 产物与示例输出
- `block_trace/llvm-install/`：LLVM 安装前缀（不入库），`block_trace/LLVM_COMMIT.txt` 记录官方哈希
- `block_trace/gem5/m5out`、`trace_logs/`：gem5 运行输出（不入库）

按以上结构拆分并推送后，新机器只需克隆主仓、初始化 gem5 子模块，并在 `block_trace/llvm-project` 检出指定官方 commit，即可按“依赖准备 + 构建流程”完成部署。***


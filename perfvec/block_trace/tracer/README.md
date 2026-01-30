# Basic Block Trace Pipeline

该目录提供一个基础的 block-level trace 采集流水线，用于后续把函数/基本块级别的静态上下文与动态执行信息（执行路径、循环迭代、访存地址等）对齐，方便训练 block-level latency/embedding 模型。

## 组件

- `passes/BasicBlockTracer.cpp`：LLVM 模块级 pass，以 basic block 为粒度插桩并输出静态描述。它完成：
  - 为每个函数/基本块分配稳定 ID，并在 block 入口注入 `__bbtrace_on_basic_block`；
  - 利用 `LoopInfo` 为每个 loop header 维护迭代计数并调用 `__bbtrace_on_loop`；
  - 对所有 load/store 记录访存地址、访存尺寸以及所属 basic block，为每条分支指令记录实际跳转目的，并为每条函数调用注入 `__bbtrace_on_call` 以 dump 目标地址与实参值；
  - 将模块名注册到运行时（便于多模块应用后续聚合）；
  - 针对每个 basic block 生成 `bbtrace_static/<module>.bbinfo.jsonl`（静态 IR+注释），以及常量区段 `.bbtrace_map`（`func_id/bb_id -> blockaddress`），可把最终可执行中的 PC 反查到优化前的 IR BB，同时 `bb` 事件会携带实时 `bb_addr` 字段，用于直接定位当前 PC。
- `runtime/trace_logger.cpp`：轻量级运行时，负责把事件按 JSONL 流写入 `trace_logs/`（可通过 `BBTRACE_OUT_DIR` 覆盖）。所有事件拥有纳秒级时间戳与单调递增序列号，`bb` 事件包含实时 `bb_addr`，`branch` 事件指明实际跳转目标和地址，`call` 事件可记录调用指令在内存中的实际地址(`call_addr`)、被调目标地址(`target_addr`)以及每个实参的即时值，方便将动态信息与未插桩 IR 精确对齐。
- `scripts/`：自动化脚本
  - `build.sh`：配置并编译 pass + runtime；
  - `run_example.sh`：用 LLVM 自带 `clang/opt` 对 `examples/matmul.c` 进行插桩、链接并运行，示范如何收集 trace，并自动把最新 JSONL + bbinfo 转成带注释的顺序文本，同时提取 `.bbtrace_map`→`func_id/bb_id`→`PC` 的映射；
  - `trace_wrapper.sh`：统一封装“先插桩收集动态信息，再用相同编译选项构建无插桩最终可执行”的流程。脚本内部先以 `BBTRACE_STATIC_ONLY=1` 运行 `bb-trace`，得到无插桩但已按 `call` 拆块的 IR 及静态信息，再生成带插桩版本采集 JSONL，并同时输出 `bbtrace_ordered_trace.txt`（插桩 IR）与 `bbtrace_ordered_full.txt`（无插桩 IR）以及双份 pcmap/bbinfo/可执行文件和 `address_diff.json`；
  - `summarize_trace.py`：解析 JSONL，快速汇总 loop 迭代次数、load/store 数量等统计；
  - `trace_to_text.py`：根据静态 bbinfo，将 `bb` 事件序列化为可读的执行路径文本，并在每条指令后追加动态属性（load/store 的实时地址/大小、branch 的实际目标、静态候选目标等）；
  - `extract_pcmap.py`：利用 `llvm-objcopy` 解析最终可执行中的 `.bbtrace_map` 区段，得到 `func_id/bb_id -> PC` 映射，便于将硬件 profile 的 PC 聚合回优化前的 basic block；
  - `dump_external_bb.py`：调用 `block_trace/qemu` 中的 `externbb` 插件，运行指定可执行文件并把所有翻译块（可选包含 LLVM 已覆盖部分）按“反汇编 + 分支目的地 + 动态访存地址”形式写入日志，方便审计 libc/运行时等外部模块；
  - `merge_pcmap.py`：解析 LLVM pcmap 与 QEMU dump，自动为缺失的 basic block 分配新的 `func_id/bb_id`，生成统一的 pcmap 以及携带汇编文本的 JSONL 描述，便于 gem5/profile 完整覆盖整条执行路径。

## 先决条件

- `/home/chiplab/PRL/PerfVec/block_trace/llvm-install`：已经通过源码构建好的 LLVM/Clang/MLIR 前缀；
- `cmake`、`ninja`、`python3` 已安装。

## 使用方法

```bash
# 1. 构建 pass 与 runtime
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/build.sh

# 2. 对示例程序插桩并运行（会自动展示前 5 行 trace）
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/run_example.sh

# 3. 查看统计
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/summarize_trace.py \
  /home/chiplab/PRL/PerfVec/block_trace/tracer/build/examples/trace/bbtrace-*.jsonl

# 3+. 采用 wrapper 同时得到“带/不带 trace”两个版本（含 bbtrace_ordered_full）
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/trace_wrapper.sh \
  --src /home/chiplab/PRL/PerfVec/block_trace/tracer/examples/matmul.c \
  --name gemm

# 4. 生成包含bb文本的执行顺序
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/trace_to_text.py \
  --trace /home/chiplab/PRL/PerfVec/block_trace/tracer/build/examples/trace/bbtrace-*.jsonl \
  --bbinfo /home/chiplab/PRL/PerfVec/block_trace/tracer/build/examples/bbtrace_static/matmul.bc.bbinfo.jsonl \
  --output /tmp/matmul_bbtrace.txt

# 5. 解析最终可执行中的PC映射，用于profile回溯
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/extract_pcmap.py \
  /home/chiplab/PRL/PerfVec/block_trace/tracer/build/examples/matmul_traced \
  --output /tmp/matmul_pcmap.txt

# 6. 运行 QEMU + externbb 插件，抓取 pcmap 覆盖之外的物理基本块
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/dump_external_bb.py \
  --pcmap /tmp/matmul_pcmap.txt \
  --include-pcmap \
  --output /tmp/matmul_external_bb.txt \
  -- /home/chiplab/PRL/PerfVec/block_trace/tracer/build/examples/matmul_traced

# 7. 合并 LLVM/QEMU 的 pcmap（生成新的 pcmap + JSONL）
/home/chiplab/PRL/PerfVec/block_trace/tracer/scripts/merge_pcmap.py \
  --pcmap /tmp/matmul_pcmap.txt \
  --qemu-log /tmp/matmul_external_bb.txt \
  --output-pcmap /tmp/matmul_pcmap_merged.txt \
  --external-info /tmp/matmul_external_bb.jsonl
```

`pcmap` 每行记录 `func_id/bb_id` 以及 `[start_pc, end_pc]` 区间（`end_pc` 为下一 block 的起始地址前一字节，若为最后一个 block 则取 `.text` 区段真实末地址减一），方便把硬件/模拟器采集到的 PC 精确映射回对应的 IR basic block。
```

## 与 gem5 对接：导出 μOP 时序

- `block_trace/gem5` 新增 `MicroOpVerboseTracer`，可在 μOP 级别记录 gem5 fast 的内部执行。运行 `gem5.fast` 时追加：

  ```bash
  build/X86/gem5.fast configs/deprecated/example/se.py \
    --cmd /path/to/bin_traced \
    --uop-trace-path traced_uops.jsonl \
    --uop-trace-buffer 8GB
  ```

  `--uop-trace-path` 支持绝对路径或相对 `m5out` 的文件名；`--uop-trace-buffer` 控制在内存中累积的最大 JSONL 尺寸（默认 8GB，填满后统一 flush，避免频繁 I/O）。

- tracer 在 μOP 进入 pipeline 时记录 `enter_tick`，在 commit/fault 时记录 `commit_tick`，并输出：

  ```
  {"cpu":"system.cpu","thread":0,"pc":"0x4016b0","micro_pc":0,"enter_tick":540120,"commit_tick":540480,"is_micro":false,"fault":false}
  {"cpu":"system.cpu","thread":0,"pc":"0x4016b0","micro_pc":1,"enter_tick":540200,"commit_tick":540540,"is_micro":true,"fault":false,"fetch_seq":12,"commit_seq":12}
  ```

- 结合 `bbtrace_ordered_trace/full`、LLVM IR 与 `pcmap`，即可把 μOP 粒度的真实时间轴与静态基本块对齐，为 PerfVec/CFG/LLVM pass 提供 ground truth。

 `trace_to_text.py` 会把 `bb` 事件按执行顺序展开，并对关键指令打上动态注释：

```
bb_6:
    %"<unnamed loop>.iter.load" = load i64, ptr %"<unnamed loop>.iter", align 8  ; addr=0x7ffeb27cece0 size=8 type=load
    store i64 %40, ptr %"<unnamed loop>.iter", align 8                            ; addr=0x7ffeb27cece0 size=8 type=store
    br i1 %50, label %6, label %38                                               ; taken_bb=6, targets=[1,6]
```

这样即可直接得到“block 内容 + 动态行为”的序列文本，便于输入 NLP/LSTM/Transformer 模型。

> **地址一致性说明**：当前插桩在 basic block 开头直接插入 `__bbtrace_on_basic_block` 调用，因此 `.bbtrace_map`/`bb_addr` 记录的是“带 trace”二进制的入口 PC，而未插桩版本的入口 PC 会提前若干指令。`BBTRACE_STATIC_ONLY=1 opt ...` + `trace_wrapper.sh` 会额外导出 `bbtrace_ordered_full`（使用无插桩 IR 的文本）和 `address_diff.json`（符号级偏差），便于核对。若需要在最终二进制中彻底对齐 PC，可考虑在 pass 中引入“前置入口块”方案：利用 `SplitBlockPredecessors` 为每个原始 BB 建立中转块，仅在中转块执行插桩，保持真正的 BB label 与无插桩版本完全一致（后续改进计划）。

## 扩展方向

1. **特征拼接**：在 JSONL 中可进一步加入静态哈希或 embedding index（例如 basic block 的 opcode 序列哈希），以便后续直接映射到模型输入。
2. **访存上下文**：当前 runtime 输出原始地址，可在 `summarize_trace.py` 中接入 cache line/页面分布分析，或扩展 pass 在插桩时附带 LLVM SSA value ID，方便与静态访存分析对齐。
3. **跨模块/多线程**：JSONL 包含 `seq`（原子自增）与 `ts_ns`，可在离线处理阶段根据 `thread_id`、`pid` 等附加字段进行分流，进一步做到 per-thread embedding。

通过该 pipeline，可以快速得到 basic block 执行路径与循环边界信息，后续即可把 trace 融入 block-level 模型，绕开逐指令依赖带来的可扩展性瓶颈。***


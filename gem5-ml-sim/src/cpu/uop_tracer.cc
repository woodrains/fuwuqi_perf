#include "cpu/uop_tracer.hh"

#include <algorithm>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>

#include "base/cprintf.hh"
#include "base/logging.hh"
#include "cpu/base.hh"
#include "cpu/static_inst.hh"
#include "cpu/thread_context.hh"
#include "sim/core.hh"

namespace gem5
{

namespace trace
{

namespace
{
constexpr uint64_t kMinReserve = 1ull << 20;
}

MicroOpVerboseTracerRecord::MicroOpVerboseTracerRecord(
        Tick when, ThreadContext *thread, const StaticInstPtr staticInst,
        const PCStateBase &pc, MicroOpVerboseTracer &owner,
        const StaticInstPtr macroStaticInst)
    : InstRecord(when, thread, staticInst, pc, macroStaticInst),
      tracer(owner)
{
}

void
MicroOpVerboseTracerRecord::dump()
{
    tracer.writeRecord(*this);
}

MicroOpVerboseTracer::MicroOpVerboseTracer(const Params &params)
    : InstTracer(params), bufferLimit(params.buffer_size)
{
    recordRequests.store(0, std::memory_order_relaxed);
    recordsWritten.store(0, std::memory_order_relaxed);
    droppedNoThread.store(0, std::memory_order_relaxed);
    droppedNoInst.store(0, std::memory_order_relaxed);

    const std::string fileName = params.output_path.empty() ?
        csprintf("uoptrace.%s.jsonl", name()) : params.output_path;
    output = simout.create(fileName);
    if (!output) {
        warn("MicroOpVerboseTracer: failed to create '%s'", fileName);
        return;
    }
    stream = output->stream();
    if (!stream) {
        warn("MicroOpVerboseTracer: stream unavailable for '%s'", fileName);
        return;
    }
    buffer.reserve(std::min<uint64_t>(bufferLimit, kMinReserve));
    registerExitCallback([this]() {
        flush();
        inform("MicroOpVerboseTracer[%s]: requests=%llu, written=%llu, "
               "drop_no_thread=%llu, drop_no_inst=%llu",
               name(),
               static_cast<unsigned long long>(recordRequests.load()),
               static_cast<unsigned long long>(recordsWritten.load()),
               static_cast<unsigned long long>(droppedNoThread.load()),
               static_cast<unsigned long long>(droppedNoInst.load()));
    });
}

MicroOpVerboseTracer::~MicroOpVerboseTracer()
{
    flush();
}

InstRecord *
MicroOpVerboseTracer::getInstRecord(Tick when, ThreadContext *tc,
        const StaticInstPtr staticInst, const PCStateBase &pc,
        const StaticInstPtr macroStaticInst)
{
    recordRequests.fetch_add(1, std::memory_order_relaxed);
    if (!stream)
        return nullptr;
    return new MicroOpVerboseTracerRecord(
        when, tc, staticInst, pc, *this, macroStaticInst);
}

void
MicroOpVerboseTracer::writeRecord(const MicroOpVerboseTracerRecord &record)
{
    if (!stream)
        return;

    ThreadContext *thread = record.getThread();
    if (!thread) {
        droppedNoThread.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    const StaticInstPtr inst = record.getStaticInst();
    if (!inst) {
        droppedNoInst.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    recordsWritten.fetch_add(1, std::memory_order_relaxed);
    const StaticInstPtr macroInst = record.getMacroStaticInst();
    const PCStateBase &pc = record.getPCState();
    const Tick commitTick = curTick();
    std::unique_ptr<PCStateBase> seq_pc(pc.clone());
    inst->advancePC(*seq_pc);
    const PCStateBase *actual_pc = record.getNextPCValid() ?
        &record.getNextPC() : seq_pc.get();
    bool branch_taken = false;
    if (inst->isControl() && actual_pc) {
        branch_taken = actual_pc->instAddr() != seq_pc->instAddr() ||
            actual_pc->microPC() != seq_pc->microPC();
    }

    std::ostringstream oss;
    const std::string uopDisasm = disassemble(inst, pc);
    const std::string origAsm = macroInst ?
        macroInst->disassemble(pc.instAddr(), nullptr) :
        inst->disassemble(pc.instAddr(), nullptr);

    oss << "{\"cpu\":\"" << thread->getCpuPtr()->name() << "\""
        << ",\"thread\":" << thread->threadId()
        << ",\"pc\":\"0x" << std::hex << pc.instAddr() << std::dec << "\""
        << ",\"micro_pc\":" << pc.microPC()
        << ",\"enter_tick\":" << record.getWhen()
        << ",\"commit_tick\":" << commitTick
        << ",\"is_micro\":" << (inst->isMicroop() ? "true" : "false")
        << ",\"fault\":" << (record.getFaulting() ? "true" : "false")
        << ",\"uop\":\"" << uopDisasm << "\""
        << ",\"orig_asm\":\"" << origAsm << "\"";
    if (record.getFetchSeqValid())
        oss << ",\"fetch_seq\":" << record.getFetchSeq();
    if (record.getCpSeqValid())
        oss << ",\"commit_seq\":" << record.getCpSeq();
    if (macroInst) {
        oss << ",\"macro\":\""
            << macroInst->disassemble(pc.instAddr(), nullptr) << "\"";
    }
    oss << ",\"next_pc\":\"0x" << std::hex << actual_pc->instAddr()
        << std::dec << "\""
        << ",\"next_micro_pc\":" << actual_pc->microPC();
    if (inst->isControl())
        oss << ",\"branch_taken\":" << (branch_taken ? "true" : "false");
    if (record.getMemValid()) {
        oss << ",\"mem_addr\":\"0x" << std::hex << record.getAddr()
            << std::dec << "\""
            << ",\"mem_size\":" << record.getSize()
            << ",\"mem_flags\":" << record.getFlags();
    }
    oss << "}\n";
    append(oss.str());
}

void
MicroOpVerboseTracer::append(const std::string &entry)
{
    if (!stream)
        return;
    std::lock_guard<std::mutex> guard(bufferMutex);
    buffer.append(entry);
    if (bufferLimit == 0 || buffer.size() >= bufferLimit) {
        stream->write(buffer.data(), buffer.size());
        stream->flush();
        buffer.clear();
    }
}

void
MicroOpVerboseTracer::flush()
{
    if (!stream)
        return;
    std::lock_guard<std::mutex> guard(bufferMutex);
    if (buffer.empty())
        return;
    stream->write(buffer.data(), buffer.size());
    stream->flush();
    buffer.clear();
}

} // namespace trace
} // namespace gem5

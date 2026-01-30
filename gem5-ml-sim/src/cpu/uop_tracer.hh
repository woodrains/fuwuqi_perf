#ifndef __CPU_UOP_TRACER_HH__
#define __CPU_UOP_TRACER_HH__

#include <atomic>
#include <mutex>
#include <string>

#include "base/output.hh"
#include "params/MicroOpVerboseTracer.hh"
#include "sim/insttracer.hh"

namespace gem5
{

class ThreadContext;

namespace trace
{

class MicroOpVerboseTracer;

class MicroOpVerboseTracerRecord : public InstRecord
{
  public:
    MicroOpVerboseTracerRecord(Tick when, ThreadContext *thread,
                               const StaticInstPtr staticInst,
                               const PCStateBase &pc,
                               MicroOpVerboseTracer &owner,
                               const StaticInstPtr macroStaticInst = nullptr);

    void dump() override;

  private:
    MicroOpVerboseTracer &tracer;
};

class MicroOpVerboseTracer : public InstTracer
{
  public:
    using Params = MicroOpVerboseTracerParams;

    MicroOpVerboseTracer(const Params &params);
    ~MicroOpVerboseTracer() override;

    InstRecord *getInstRecord(Tick when, ThreadContext *tc,
                              const StaticInstPtr staticInst,
                              const PCStateBase &pc,
                              const StaticInstPtr macroStaticInst = nullptr)
                              override;

    void writeRecord(const MicroOpVerboseTracerRecord &record);

  private:
    void append(const std::string &entry);
    void flush();

    std::atomic<uint64_t> recordRequests{0};
    std::atomic<uint64_t> recordsWritten{0};
    std::atomic<uint64_t> droppedNoThread{0};
    std::atomic<uint64_t> droppedNoInst{0};

    OutputStream *output = nullptr;
    std::ostream *stream = nullptr;
    std::string buffer;
    const uint64_t bufferLimit;
    std::mutex bufferMutex;
};

} // namespace trace
} // namespace gem5

#endif // __CPU_UOP_TRACER_HH__

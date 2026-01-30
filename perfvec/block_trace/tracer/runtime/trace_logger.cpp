#include <atomic>
#include <cinttypes>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
#include <unordered_map>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <chrono>
#include <ctime>

namespace {

using clock_type = std::chrono::steady_clock;

enum class CallArgKind : uint32_t { Unknown = 0, Integer = 1, Pointer = 2, Floating = 3 };

const char *call_arg_kind_to_string(uint32_t kind) {
  switch (static_cast<CallArgKind>(kind)) {
  case CallArgKind::Integer:
    return "int";
  case CallArgKind::Pointer:
    return "ptr";
  case CallArgKind::Floating:
    return "float";
  case CallArgKind::Unknown:
  default:
    return "unknown";
  }
}

const char *pointer_to_json(const void *addr) {
  thread_local char buffers[2][32];
  thread_local int index = 0;
  index ^= 1;
  if (!addr) {
    std::snprintf(buffers[index], sizeof(buffers[index]), "%s", "null");
  } else {
    std::snprintf(buffers[index], sizeof(buffers[index]), "\"0x%" PRIxPTR "\"",
                  reinterpret_cast<uintptr_t>(addr));
  }
  return buffers[index];
}

constexpr size_t kPathBufSize = 1024;
constexpr size_t kJsonBufSize = 4096;

int mkdir_p(const char *path) {
  char tmp[kPathBufSize];
  size_t len = std::strlen(path);
  if (len == 0 || len >= sizeof(tmp))
    return -1;
  std::strcpy(tmp, path);
  for (char *p = tmp + 1; *p; ++p) {
    if (*p == '/') {
      *p = '\0';
      ::mkdir(tmp, 0755);
      *p = '/';
    }
  }
  if (::mkdir(tmp, 0755) == -1 && errno != EEXIST)
    return -1;
  return 0;
}

inline uint64_t now_ns() {
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return static_cast<uint64_t>(ts.tv_sec) * 1000000000ull + ts.tv_nsec;
}

struct TraceLogger {
  TraceLogger() { open_stream(); }
  ~TraceLogger() { flush_and_close(); }

  void set_module(const char *name) {
    std::lock_guard<std::mutex> lock(mu_);
    sanitize(module_name_, sizeof(module_name_), name);
  }

  uint64_t next_sequence() { return sequence_.fetch_add(1, std::memory_order_relaxed); }

  uint64_t elapsed_ns() const { return now_ns() - start_time_ns_; }

  void log(const char *payload, size_t len) {
    std::lock_guard<std::mutex> lock(mu_);
    if (fd_ < 0)
      return;
    ::write(fd_, payload, len);
    ::write(fd_, "\n", 1);
  }

  void flush_and_close() {
    std::lock_guard<std::mutex> lock(mu_);
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
  }

private:
  void sanitize(char *dst, size_t cap, const char *src) {
    if (!src) {
      std::snprintf(dst, cap, "%s", "null");
      return;
    }
    size_t n = 0;
    while (*src && n + 1 < cap) {
      dst[n++] = (*src == '"') ? '\'' : *src;
      ++src;
    }
    dst[n] = '\0';
  }

  void open_stream() {
    char dir[kPathBufSize];
    const char *dir_env = std::getenv("BBTRACE_OUT_DIR");
    if (dir_env && *dir_env) {
      std::snprintf(dir, sizeof(dir), "%s", dir_env);
    } else {
      std::snprintf(dir, sizeof(dir), "%s", "trace_logs");
    }
    mkdir_p(dir);

    char file[kPathBufSize];
    auto pid = static_cast<long>(::getpid());
    auto start = std::chrono::system_clock::now();
    std::time_t start_t = std::chrono::system_clock::to_time_t(start);
    char ts[32];
    std::strftime(ts, sizeof(ts), "%Y%m%d-%H%M%S", std::localtime(&start_t));
    int max_dir = static_cast<int>(sizeof(file) - 64);
    if (max_dir < 0)
      max_dir = 0;
    std::snprintf(file, sizeof(file), "%.*s/bbtrace-%ld-%s.jsonl", max_dir, dir, pid, ts);
    fd_ = ::open(file, O_CREAT | O_TRUNC | O_WRONLY, 0644);
    start_time_ns_ = now_ns();
  }

  int fd_ = -1;
  char module_name_[128] = "unknown";
  mutable std::mutex mu_;
  std::atomic<uint64_t> sequence_{0};
  uint64_t start_time_ns_ = now_ns();
};

bool tracing_disabled() {
  static bool disabled = [] {
    if (const char *env = std::getenv("BBTRACE_DISABLE")) {
      if (*env == '\0')
        return true;
      switch (env[0]) {
      case '0':
      case 'f':
      case 'F':
      case 'n':
      case 'N':
        return false;
      default:
        break;
      }
      return true;
    }
    return false;
  }();
  return disabled;
}

TraceLogger &logger() {
  static TraceLogger instance;
  return instance;
}

std::string sanitize(const char *name) {
  if (!name)
    return "null";
  std::string value{name};
  for (auto &c : value) {
    if (c == '"')
      c = '\'';
  }
  return value;
}

uint64_t next_loop_iter(uint32_t func_id, uint32_t loop_id) {
  thread_local std::unordered_map<uint64_t, uint64_t> loop_iters;
  uint64_t key = (static_cast<uint64_t>(func_id) << 32) | loop_id;
  uint64_t current = loop_iters[key];
  loop_iters[key] = current + 1;
  return current;
}

} // namespace

extern "C" {

void __bbtrace_register_module(const char *module_name) {
  if (tracing_disabled())
    return;
  logger().set_module(module_name);
}

void __bbtrace_on_basic_block(uint32_t func_id, uint32_t bb_id, uint32_t loop_id_hint,
                              const void *bb_addr) {
  if (tracing_disabled())
    return;
  const uint64_t seq = logger().next_sequence();
  char buf[kJsonBufSize];
  int len = std::snprintf(buf, sizeof(buf),
      "{\"event\":\"bb\",\"seq\":%" PRIu64 ",\"func\":%u,\"bb\":%u,"
      "\"loop_hint\":%u,\"bb_addr\":%s,\"ts_ns\":%" PRIu64 "}",
      seq, func_id, bb_id, loop_id_hint, pointer_to_json(bb_addr), logger().elapsed_ns());
  if (len > 0)
    logger().log(buf, static_cast<size_t>(len));
}

void __bbtrace_on_loop(uint32_t func_id, uint32_t loop_id) {
  if (tracing_disabled())
    return;
  uint64_t iter_index = next_loop_iter(func_id, loop_id);
  const uint64_t seq = logger().next_sequence();
  char buf[kJsonBufSize];
  int len = std::snprintf(buf, sizeof(buf),
      "{\"event\":\"loop\",\"seq\":%" PRIu64 ",\"func\":%u,\"loop\":%u,"
      "\"iter\":%" PRIu64 ",\"ts_ns\":%" PRIu64 "}",
      seq, func_id, loop_id, iter_index, logger().elapsed_ns());
  if (len > 0)
    logger().log(buf, static_cast<size_t>(len));
}

void __bbtrace_on_mem(uint32_t func_id, uint32_t bb_id, uint32_t inst_id, const void *addr,
                      uint64_t size, bool is_store) {
  if (tracing_disabled())
    return;
  const uint64_t seq = logger().next_sequence();
  char buf[kJsonBufSize];
  uintptr_t ptr = reinterpret_cast<uintptr_t>(addr);
  int len = std::snprintf(buf, sizeof(buf),
      "{\"event\":\"mem\",\"seq\":%" PRIu64 ",\"func\":%u,\"bb\":%u,"
      "\"inst\":%u,\"is_store\":%s,\"addr\":\"0x%" PRIxPTR "\",\"size\":%" PRIu64
      ",\"inst_pc\":%s,\"ts_ns\":%" PRIu64 "}",
      seq, func_id, bb_id, inst_id, is_store ? "true" : "false", ptr, size,
      pointer_to_json(__builtin_return_address(0)), logger().elapsed_ns());
  if (len > 0)
    logger().log(buf, static_cast<size_t>(len));
}

void __bbtrace_on_branch(uint32_t func_id, uint32_t bb_id, uint32_t inst_id,
                         uint32_t target_bb_id, const void *target_addr) {
  if (tracing_disabled())
    return;
  const uint64_t seq = logger().next_sequence();
  char buf[kJsonBufSize];
  int len = std::snprintf(buf, sizeof(buf),
      "{\"event\":\"branch\",\"seq\":%" PRIu64 ",\"func\":%u,\"bb\":%u,"
      "\"inst\":%u,\"target_bb\":%u,\"target_addr\":%s,\"ts_ns\":%" PRIu64 "}",
      seq, func_id, bb_id, inst_id, target_bb_id, pointer_to_json(target_addr),
      logger().elapsed_ns());
  if (len > 0)
    logger().log(buf, static_cast<size_t>(len));
}

void __bbtrace_on_call(uint32_t func_id, uint32_t bb_id, uint32_t inst_id,
                       const void *call_site_addr, const void *target_addr,
                       uint32_t num_args, ...) {
  if (tracing_disabled())
    return;
  const uint64_t seq = logger().next_sequence();
  char args_buf[kJsonBufSize];
  size_t off = 0;
  off += std::snprintf(args_buf + off, sizeof(args_buf) - off, "[");
  va_list ap;
  va_start(ap, num_args);
  for (uint32_t idx = 0; idx < num_args; ++idx) {
    uint32_t kind = va_arg(ap, uint32_t);
    uint32_t bits = va_arg(ap, uint32_t);
    uint64_t value = va_arg(ap, uint64_t);
    off += std::snprintf(args_buf + off, sizeof(args_buf) - off,
        "%s{\"idx\":%u,\"kind\":\"%s\",\"bits\":%u,\"value\":\"0x%" PRIx64 "\"}",
        (idx == 0 ? "" : ","), idx, call_arg_kind_to_string(kind), bits, value);
    if (off >= sizeof(args_buf))
      break;
  }
  va_end(ap);
  off += std::snprintf(args_buf + off, sizeof(args_buf) - off, "]");

  char buf[kJsonBufSize];
  int len = std::snprintf(buf, sizeof(buf),
      "{\"event\":\"call\",\"seq\":%" PRIu64 ",\"func\":%u,\"bb\":%u,\"inst\":%u,"
      "\"call_addr\":%s,\"target_addr\":%s,\"num_args\":%u,\"args\":%s,\"ts_ns\":%" PRIu64 "}",
      seq, func_id, bb_id, inst_id, pointer_to_json(call_site_addr),
      pointer_to_json(target_addr), num_args, args_buf, logger().elapsed_ns());
  if (len > 0)
    logger().log(buf, static_cast<size_t>(len));
}

void __bbtrace_finalize() {
  if (tracing_disabled())
    return;
  logger().flush_and_close();
}

}


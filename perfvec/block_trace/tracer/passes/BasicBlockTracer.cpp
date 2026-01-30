#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/Analysis/LoopAnalysisManager.h"
#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/DataLayout.h"
#include "llvm/IR/DerivedTypes.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/InlineAsm.h"
#include "llvm/IR/InstrTypes.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Dominators.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/Intrinsics.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/IR/Type.h"
#include "llvm/IR/Value.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/Alignment.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Transforms/Utils/ModuleUtils.h"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <string>
#include <vector>

using namespace llvm;

namespace {

constexpr uint32_t kInvalidLoopId = std::numeric_limits<uint32_t>::max();

struct LoopContext {
  uint32_t Id;
};

enum class InstKind : uint8_t { Generic, Load, Store, Branch, Call };

enum class CallArgKind : uint32_t {
  Unknown = 0,
  Integer = 1,
  Pointer = 2,
  Floating = 3,
};

struct InstructionStaticInfo {
  InstKind Kind = InstKind::Generic;
  uint32_t InstId = 0;
  std::vector<uint32_t> BranchTargets;
  std::string Buffer;
};

struct BlockStaticInfo {
  uint32_t FuncId;
  std::string FuncName;
  uint32_t BbId;
  std::string BbName;
  std::string Header;
  std::vector<InstructionStaticInfo> Instructions;
};

struct BlockPcInfo {
  uint32_t FuncId;
  uint32_t BbId;
  Constant *Address;
};

static bool isStaticOnlyMode() {
  static bool Enabled = [] {
    if (const char *Env = std::getenv("BBTRACE_STATIC_ONLY")) {
      switch (Env[0]) {
      case '1':
      case 'T':
      case 't':
      case 'Y':
      case 'y':
        return true;
      default:
        break;
      }
    }
    return false;
  }();
  return Enabled;
}

static bool isInlineAsmCall(const CallBase &Call) {
  return isa<InlineAsm>(Call.getCalledOperand());
}

static bool isBbtraceRuntimeCall(const CallBase &Call) {
  if (const Function *Callee = Call.getCalledFunction()) {
    StringRef Name = Callee->getName();
    if (Name.starts_with("__bbtrace_"))
      return true;
  }
  return false;
}

static Value *materializeCallArg(Value *Arg, CallArgKind &Kind, uint32_t &BitWidth,
                                 IRBuilder<> &Builder, Type *Int64Ty, const DataLayout &DL) {
  LLVMContext &Ctx = Arg->getContext();
  Type *Ty = Arg->getType();
  if (Ty->isPointerTy()) {
    Kind = CallArgKind::Pointer;
    BitWidth = DL.getPointerSizeInBits(Ty->getPointerAddressSpace());
    if (BitWidth == 0)
      BitWidth = DL.getPointerSizeInBits(0);
    auto *PtrIntTy = IntegerType::get(Ctx, std::max<uint32_t>(BitWidth, 1));
    Value *PtrInt = Builder.CreatePtrToInt(Arg, PtrIntTy);
    if (BitWidth < 64)
      PtrInt = Builder.CreateZExt(PtrInt, Int64Ty);
    else if (BitWidth > 64)
      PtrInt = Builder.CreateTrunc(PtrInt, Int64Ty);
    return PtrInt;
  }

  if (Ty->isIntegerTy()) {
    Kind = CallArgKind::Integer;
    BitWidth = Ty->getIntegerBitWidth();
    Value *Val = Arg;
    if (BitWidth < 64)
      Val = Builder.CreateZExt(Val, Int64Ty);
    else if (BitWidth > 64)
      Val = Builder.CreateTrunc(Val, Int64Ty);
    else if (!Val->getType()->isIntegerTy(64))
      Val = Builder.CreateBitCast(Val, Int64Ty);
    return Val;
  }

  if (Ty->isFloatingPointTy()) {
    Kind = CallArgKind::Floating;
    BitWidth = Ty->getScalarSizeInBits();
    if (BitWidth == 0)
      BitWidth = DL.getTypeStoreSizeInBits(Ty);
    auto *IntTy = IntegerType::get(Ctx, std::max<uint32_t>(BitWidth, 1));
    Value *Bits = Builder.CreateBitCast(Arg, IntTy);
    if (BitWidth < 64)
      Bits = Builder.CreateZExt(Bits, Int64Ty);
    else if (BitWidth > 64)
      Bits = Builder.CreateTrunc(Bits, Int64Ty);
    else if (!Bits->getType()->isIntegerTy(64))
      Bits = Builder.CreateBitCast(Bits, Int64Ty);
    return Bits;
  }

  Kind = CallArgKind::Unknown;
  BitWidth = DL.getTypeStoreSizeInBits(Ty);
  if (BitWidth == 0)
    BitWidth = 1;
  return ConstantInt::get(Int64Ty, 0);
}

static std::string printInstruction(const Instruction &I) {
  std::string Buffer;
  raw_string_ostream OS(Buffer);
  OS << "  ";
  I.print(OS);
  return Buffer;
}

static std::string makeBlockHeader(const BasicBlock &BB, uint32_t BbId) {
  std::string Name =
      BB.hasName() ? std::string(BB.getName()) : ("bb_" + std::to_string(BbId));
  return Name + ":";
}

static StringRef instKindToString(InstKind Kind) {
  switch (Kind) {
  case InstKind::Load:
    return "load";
  case InstKind::Store:
    return "store";
  case InstKind::Branch:
    return "branch";
  case InstKind::Call:
    return "call";
  case InstKind::Generic:
  default:
    return "generic";
  }
}

class BasicBlockTracePass : public PassInfoMixin<BasicBlockTracePass> {
public:
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &MAM);

private:
  void emitInstPcRecord(IRBuilder<> &Builder, uint32_t FuncId, uint32_t BbId,
                        uint32_t InstId);
  bool instrumentModule(Module &M, ModuleAnalysisManager &MAM);
  void ensureCtorDtor(Module &M);
  void instrumentFunction(Function &F, Module &M, FunctionAnalysisManager &FAM,
                          uint32_t FuncId, std::vector<BlockStaticInfo> &StaticInfos,
                          std::vector<BlockPcInfo> &PcInfos, bool EnableInstrumentation);
  FunctionCallee declareHook(Module &M, StringRef Name, Type *RetTy,
                             ArrayRef<Type *> Args, bool IsVarArg = false);
  Constant *getModuleNameGlobal(Module &M);
  ConstantInt *constI32(LLVMContext &Ctx, uint32_t Value);
  ConstantInt *constI64(LLVMContext &Ctx, uint64_t Value);
  void dumpBasicBlockInfo(Module &M, ArrayRef<BlockStaticInfo> Infos);
  void emitPcMap(Module &M, ArrayRef<BlockPcInfo> Infos);
};

PreservedAnalyses BasicBlockTracePass::run(Module &M, ModuleAnalysisManager &MAM) {
  if (!instrumentModule(M, MAM))
    return PreservedAnalyses::all();
  return PreservedAnalyses::none();
}

bool BasicBlockTracePass::instrumentModule(Module &M, ModuleAnalysisManager &MAM) {
  bool EnableInstrumentation = !isStaticOnlyMode();
  if (EnableInstrumentation)
    ensureCtorDtor(M);

  auto &FAM = MAM.getResult<FunctionAnalysisManagerModuleProxy>(M).getManager();
  std::vector<BlockStaticInfo> StaticInfos;
  std::vector<BlockPcInfo> PcInfos;
  uint32_t FuncId = 0;
  for (Function &F : M) {
    if (F.isDeclaration())
      continue;
    if (F.getName().starts_with("__bbtrace_"))
      continue;
    instrumentFunction(F, M, FAM, FuncId++, StaticInfos, PcInfos, EnableInstrumentation);
  }
  dumpBasicBlockInfo(M, StaticInfos);
  emitPcMap(M, PcInfos);
  return true;
}

void BasicBlockTracePass::ensureCtorDtor(Module &M) {
  LLVMContext &Ctx = M.getContext();
  auto *VoidTy = Type::getVoidTy(Ctx);
  auto *Int8PtrTy = PointerType::get(Ctx, 0);

  SmallVector<Type *, 1> CtorArgs{Int8PtrTy};
  auto RegisterFn = declareHook(M, "__bbtrace_register_module", VoidTy, CtorArgs);
  auto FinalizeFn = declareHook(M, "__bbtrace_finalize", VoidTy, {});

  Constant *NameGlobal = getModuleNameGlobal(M);

  Function *Ctor = Function::Create(FunctionType::get(VoidTy, {}, false),
                                    GlobalValue::PrivateLinkage, "__bbtrace_ctor", &M);
  Ctor->setUnnamedAddr(GlobalValue::UnnamedAddr::Global);
  Ctor->setDoesNotThrow();
  BasicBlock *CtorBB = BasicBlock::Create(Ctx, "entry", Ctor);
  IRBuilder<> CtorBuilder(CtorBB);
  CtorBuilder.CreateCall(RegisterFn, {CtorBuilder.CreatePointerCast(NameGlobal, Int8PtrTy)});
  CtorBuilder.CreateRetVoid();

  Function *Dtor = Function::Create(FunctionType::get(VoidTy, {}, false),
                                    GlobalValue::PrivateLinkage, "__bbtrace_dtor", &M);
  Dtor->setUnnamedAddr(GlobalValue::UnnamedAddr::Global);
  Dtor->setDoesNotThrow();
  BasicBlock *DtorBB = BasicBlock::Create(Ctx, "entry", Dtor);
  IRBuilder<> DtorBuilder(DtorBB);
  DtorBuilder.CreateCall(FinalizeFn);
  DtorBuilder.CreateRetVoid();

  appendToGlobalCtors(M, Ctor, 0);
  appendToGlobalDtors(M, Dtor, 0);
}

Constant *BasicBlockTracePass::getModuleNameGlobal(Module &M) {
  LLVMContext &Ctx = M.getContext();
  Constant *Name = ConstantDataArray::getString(Ctx, M.getModuleIdentifier(), true);
  auto *GV = new GlobalVariable(M, Name->getType(), true, GlobalValue::PrivateLinkage, Name,
                                "__bbtrace_module_name");
  GV->setUnnamedAddr(GlobalValue::UnnamedAddr::Global);
  GV->setAlignment(Align(1));
  return GV;
}

FunctionCallee BasicBlockTracePass::declareHook(Module &M, StringRef Name, Type *RetTy,
                                               ArrayRef<Type *> Args, bool IsVarArg) {
  auto *FnType = FunctionType::get(RetTy, Args, IsVarArg);
  return M.getOrInsertFunction(Name, FnType);
}

ConstantInt *BasicBlockTracePass::constI32(LLVMContext &Ctx, uint32_t Value) {
  return ConstantInt::get(Type::getInt32Ty(Ctx), Value);
}

ConstantInt *BasicBlockTracePass::constI64(LLVMContext &Ctx, uint64_t Value) {
  return ConstantInt::get(Type::getInt64Ty(Ctx), Value);
}

void BasicBlockTracePass::emitInstPcRecord(IRBuilder<> &Builder, uint32_t FuncId,
                                           uint32_t BbId, uint32_t InstId) {
  Module *M = Builder.GetInsertBlock()->getModule();
  if (!M)
    return;
  LLVMContext &Ctx = M->getContext();
  FunctionType *AsmTy = FunctionType::get(Type::getVoidTy(Ctx), {}, false);
  std::string AsmTemplate;
  {
    raw_string_ostream OS(AsmTemplate);
    OS << ".pushsection .bbtrace_inst,\"a\",@progbits\n";
    OS << ".long " << FuncId << "\n";
    OS << ".long " << BbId << "\n";
    OS << ".long " << InstId << "\n";
    OS << ".long 0\n";
    OS << ".quad 1f\n";
    OS << ".popsection\n";
    OS << "1:\n";
  }
  InlineAsm *Asm = InlineAsm::get(AsmTy, AsmTemplate, "", true);
  Builder.CreateCall(Asm);
}

void BasicBlockTracePass::instrumentFunction(Function &F, Module &M,
                                             FunctionAnalysisManager &FAM, uint32_t FuncId,
                                             std::vector<BlockStaticInfo> &StaticInfos,
                                             std::vector<BlockPcInfo> &PcInfos,
                                             bool EnableInstrumentation) {
  LLVMContext &Ctx = M.getContext();
  auto &DL = M.getDataLayout();
  auto *VoidTy = Type::getVoidTy(Ctx);
  auto *Int1Ty = Type::getInt1Ty(Ctx);
  auto *Int32Ty = Type::getInt32Ty(Ctx);
  auto *Int64Ty = Type::getInt64Ty(Ctx);
  auto *Int8PtrTy = PointerType::get(Ctx, 0);

  FunctionCallee BBHook;
  FunctionCallee LoopHook;
  FunctionCallee MemHook;
  FunctionCallee BranchHook;
  FunctionCallee CallHook;
  FunctionCallee ReturnAddrFn = nullptr;

  if (EnableInstrumentation) {
    SmallVector<Type *, 4> BbArgs{Int32Ty, Int32Ty, Int32Ty, Int8PtrTy};
    SmallVector<Type *, 2> LoopArgs{Int32Ty, Int32Ty};
    SmallVector<Type *, 6> MemArgs{Int32Ty, Int32Ty, Int32Ty, Int8PtrTy, Int64Ty, Int1Ty};
    BBHook = declareHook(M, "__bbtrace_on_basic_block", VoidTy, BbArgs);
    LoopHook = declareHook(M, "__bbtrace_on_loop", VoidTy, LoopArgs);
    MemHook = declareHook(M, "__bbtrace_on_mem", VoidTy, MemArgs);
  }

  auto &LoopInfo = FAM.getResult<LoopAnalysis>(F);

  DenseMap<const BasicBlock *, uint32_t> BlockIds;
  DenseMap<const Loop *, LoopContext> LoopIds;

  uint32_t NextBlockId = 0;
  uint32_t NextMemInstId = 0;
  uint32_t NextBranchInstId = 0;
  uint32_t NextCallInstId = 0;

  if (EnableInstrumentation) {
    SmallVector<Loop *, 8> LoopQueue(LoopInfo.begin(), LoopInfo.end());
    uint32_t NextLoopId = 0;
    while (!LoopQueue.empty()) {
      Loop *L = LoopQueue.pop_back_val();
      LoopQueue.append(L->begin(), L->end());
      LoopIds[L] = LoopContext{NextLoopId++};
    }
  }

  for (BasicBlock &BB : F) {
    BlockIds[&BB] = NextBlockId++;
  }

  if (EnableInstrumentation) {
    SmallVector<Type *, 5> BranchArgs{Int32Ty, Int32Ty, Int32Ty, Int32Ty, Int8PtrTy};
    BranchHook = declareHook(M, "__bbtrace_on_branch", VoidTy, BranchArgs);
    SmallVector<Type *, 6> CallArgs{Int32Ty, Int32Ty, Int32Ty, Int8PtrTy, Int8PtrTy, Int32Ty};
    CallHook = declareHook(M, "__bbtrace_on_call", VoidTy, CallArgs, true);
    ReturnAddrFn = Intrinsic::getOrInsertDeclaration(&M, Intrinsic::returnaddress);
  }

  for (BasicBlock &BB : F) {
    uint32_t BbId = BlockIds.lookup(&BB);
    BlockStaticInfo Info;
    Info.FuncId = FuncId;
    Info.FuncName = F.hasName() ? std::string(F.getName()) : ("func_" + std::to_string(FuncId));
    Info.BbId = BbId;
    Info.BbName = BB.hasName() ? std::string(BB.getName()) : ("bb_" + std::to_string(BbId));
    Info.Header = makeBlockHeader(BB, BbId);
    Constant *AddrConst = nullptr;
    if (&BB == &F.getEntryBlock()) {
      AddrConst = ConstantExpr::getPointerCast(&F, PointerType::get(Ctx, 0));
    } else {
      AddrConst = BlockAddress::get(&F, &BB);
    }
    PcInfos.push_back(BlockPcInfo{FuncId, BbId, AddrConst});

    if (EnableInstrumentation) {
      IRBuilder<> Builder(&*BB.getFirstInsertionPt());
      Constant *BlockAddrValue = ConstantExpr::getPointerCast(AddrConst, Int8PtrTy);
      uint32_t LoopHint = kInvalidLoopId;
      if (Loop *Containing = LoopInfo.getLoopFor(&BB)) {
        LoopHint = LoopIds.lookup(Containing).Id;
      }
      Builder.CreateCall(BBHook,
                         {constI32(Ctx, FuncId), constI32(Ctx, BbId), constI32(Ctx, LoopHint),
                          BlockAddrValue});

      if (Loop *Containing = LoopInfo.getLoopFor(&BB)) {
        if (Containing->getHeader() == &BB) {
          auto CtxInfo = LoopIds.lookup(Containing);
          IRBuilder<> HeaderBuilder(&*BB.getFirstInsertionPt());
          HeaderBuilder.CreateCall(
              LoopHook, {constI32(Ctx, FuncId), constI32(Ctx, CtxInfo.Id)});
        }
      }
    }

    for (Instruction &I : BB) {
      if (auto *Call = dyn_cast<CallBase>(&I)) {
        if (isBbtraceRuntimeCall(*Call))
          continue;
      }
      InstructionStaticInfo InstInfo;
      InstInfo.Buffer = printInstruction(I);

      if (auto *Load = dyn_cast<LoadInst>(&I)) {
        uint32_t InstId = NextMemInstId++;
        {
          IRBuilder<> LabelBuilder(Load);
          emitInstPcRecord(LabelBuilder, FuncId, BbId, InstId);
        }
        if (EnableInstrumentation) {
          IRBuilder<> MemBuilder(Load);
          Value *Ptr = MemBuilder.CreatePointerCast(Load->getPointerOperand(), Int8PtrTy);
          uint64_t Size = DL.getTypeStoreSize(Load->getType());
          MemBuilder.CreateCall(MemHook,
                                {constI32(Ctx, FuncId), constI32(Ctx, BbId),
                                 constI32(Ctx, InstId), Ptr, constI64(Ctx, Size),
                                 ConstantInt::getFalse(Int1Ty)});
        }
        InstInfo.Kind = InstKind::Load;
        InstInfo.InstId = InstId;
      } else if (auto *Store = dyn_cast<StoreInst>(&I)) {
        uint32_t InstId = NextMemInstId++;
        {
          IRBuilder<> LabelBuilder(Store);
          emitInstPcRecord(LabelBuilder, FuncId, BbId, InstId);
        }
        if (EnableInstrumentation) {
          IRBuilder<> MemBuilder(Store);
          Value *Ptr = MemBuilder.CreatePointerCast(Store->getPointerOperand(), Int8PtrTy);
          uint64_t Size = DL.getTypeStoreSize(Store->getValueOperand()->getType());
          MemBuilder.CreateCall(MemHook,
                                {constI32(Ctx, FuncId), constI32(Ctx, BbId),
                                 constI32(Ctx, InstId), Ptr, constI64(Ctx, Size),
                                 ConstantInt::getTrue(Int1Ty)});
        }
        InstInfo.Kind = InstKind::Store;
        InstInfo.InstId = InstId;
      } else if (auto *Br = dyn_cast<BranchInst>(&I)) {
        uint32_t InstId = NextBranchInstId++;
        if (EnableInstrumentation) {
          IRBuilder<> BrBuilder(Br);
          Value *Taken = nullptr;
          Value *TakenAddr = nullptr;
          auto *Succ0 = Br->getSuccessor(0);
          auto *Succ0Addr =
              ConstantExpr::getPointerCast(BlockAddress::get(&F, Succ0), Int8PtrTy);
          if (Br->isConditional()) {
            auto *Succ1 = Br->getSuccessor(1);
            auto *TrueId = constI32(Ctx, BlockIds.lookup(Succ0));
            auto *FalseId = constI32(Ctx, BlockIds.lookup(Succ1));
            Taken = BrBuilder.CreateSelect(Br->getCondition(), TrueId, FalseId);
            auto *Succ1Addr =
                ConstantExpr::getPointerCast(BlockAddress::get(&F, Succ1), Int8PtrTy);
            TakenAddr = BrBuilder.CreateSelect(Br->getCondition(), Succ0Addr, Succ1Addr);
            InstInfo.BranchTargets.push_back(BlockIds.lookup(Succ0));
            InstInfo.BranchTargets.push_back(BlockIds.lookup(Succ1));
          } else {
            uint32_t TargetId = BlockIds.lookup(Succ0);
            Taken = constI32(Ctx, TargetId);
            TakenAddr = Succ0Addr;
            InstInfo.BranchTargets.push_back(TargetId);
          }
          BrBuilder.CreateCall(
              BranchHook,
              {constI32(Ctx, FuncId), constI32(Ctx, BbId), constI32(Ctx, InstId), Taken,
               TakenAddr});
        } else {
          if (Br->isConditional()) {
            auto *Succ0 = Br->getSuccessor(0);
            auto *Succ1 = Br->getSuccessor(1);
            InstInfo.BranchTargets.push_back(BlockIds.lookup(Succ0));
            InstInfo.BranchTargets.push_back(BlockIds.lookup(Succ1));
          } else {
            uint32_t TargetId = BlockIds.lookup(Br->getSuccessor(0));
            InstInfo.BranchTargets.push_back(TargetId);
          }
        }
        InstInfo.Kind = InstKind::Branch;
        InstInfo.InstId = InstId;
      } else if (auto *Call = dyn_cast<CallBase>(&I)) {
        if (!isa<IntrinsicInst>(&I) && !isInlineAsmCall(*Call) &&
            !isBbtraceRuntimeCall(*Call)) {
          uint32_t InstId = NextCallInstId++;
          if (EnableInstrumentation) {
            IRBuilder<> CallBuilder(Call);
            Value *TargetAddr = nullptr;
            Value *CalledOperand = Call->getCalledOperand();
            if (CalledOperand && CalledOperand->getType()->isPointerTy()) {
              TargetAddr = CallBuilder.CreatePointerCast(CalledOperand, Int8PtrTy);
            } else {
              TargetAddr = ConstantPointerNull::get(Int8PtrTy);
            }
            Value *CallSiteAddr =
                CallBuilder.CreateCall(ReturnAddrFn, {constI32(Ctx, 0)});
            CallSiteAddr =
                CallBuilder.CreatePointerCast(CallSiteAddr, Int8PtrTy);

            SmallVector<Value *, 16> CallOperands;
            CallOperands.push_back(constI32(Ctx, FuncId));
            CallOperands.push_back(constI32(Ctx, BbId));
            CallOperands.push_back(constI32(Ctx, InstId));
            CallOperands.push_back(CallSiteAddr);
            CallOperands.push_back(TargetAddr);
            CallOperands.push_back(constI32(Ctx, Call->arg_size()));

            for (Value *Arg : Call->args()) {
              CallArgKind Kind = CallArgKind::Unknown;
              uint32_t BitWidth = 0;
              Value *Materialized =
                  materializeCallArg(Arg, Kind, BitWidth, CallBuilder, Int64Ty, DL);
              CallOperands.push_back(constI32(Ctx, static_cast<uint32_t>(Kind)));
              CallOperands.push_back(constI32(Ctx, BitWidth));
              CallOperands.push_back(Materialized);
            }

            CallBuilder.CreateCall(CallHook, CallOperands);
          }
          InstInfo.Kind = InstKind::Call;
          InstInfo.InstId = InstId;
        }
      }

      Info.Instructions.push_back(std::move(InstInfo));
    }

    StaticInfos.push_back(std::move(Info));
  }
}

void BasicBlockTracePass::dumpBasicBlockInfo(Module &M, ArrayRef<BlockStaticInfo> Infos) {
  namespace fs = std::filesystem;
  if (Infos.empty())
    return;

  std::string ModuleId = M.getModuleIdentifier();
  fs::path ModulePath(ModuleId);
  fs::path Parent = ModulePath.has_parent_path() ? ModulePath.parent_path() : fs::path(".");
  fs::path OutDir = Parent / "bbtrace_static";
  std::error_code EC;
  fs::create_directories(OutDir, EC);

  std::string BaseName =
      ModulePath.has_filename() ? ModulePath.filename().string() : "module";
  fs::path OutFile = OutDir / (BaseName + ".bbinfo.jsonl");

  std::ofstream OS(OutFile, std::ios::out | std::ios::trunc);
  if (!OS.is_open())
    return;

  for (const auto &Entry : Infos) {
    json::Array InstArray;
    InstArray.reserve(Entry.Instructions.size());
    for (const auto &Inst : Entry.Instructions) {
      json::Object InstObj;
      InstObj["text"] = Inst.Buffer;
      InstObj["kind"] = instKindToString(Inst.Kind).str();
      if (Inst.Kind != InstKind::Generic)
        InstObj["inst_id"] = Inst.InstId;
      if (!Inst.BranchTargets.empty()) {
        json::Array Targets;
        Targets.reserve(Inst.BranchTargets.size());
        for (uint32_t Target : Inst.BranchTargets)
          Targets.push_back(Target);
        InstObj["targets"] = std::move(Targets);
      }
      InstArray.push_back(std::move(InstObj));
    }

    json::Object Obj{
        {"func_id", Entry.FuncId},
        {"func_name", Entry.FuncName},
        {"bb_id", Entry.BbId},
        {"bb_name", Entry.BbName},
        {"header", Entry.Header},
        {"insts", std::move(InstArray)},
    };

    std::string Serialized;
    raw_string_ostream ROS(Serialized);
    ROS << json::Value(std::move(Obj));
    ROS.flush();
    OS << Serialized << '\n';
  }
}

void BasicBlockTracePass::emitPcMap(Module &M, ArrayRef<BlockPcInfo> Infos) {
  if (Infos.empty())
    return;

  LLVMContext &Ctx = M.getContext();
  const DataLayout &DL = M.getDataLayout();
  auto *Int32Ty = Type::getInt32Ty(Ctx);
  auto *IntPtrTy = DL.getIntPtrType(Ctx);
  auto *EntryTy = StructType::get(Int32Ty, Int32Ty, IntPtrTy);

  SmallVector<Constant *, 64> Entries;
  Entries.reserve(Infos.size());
  for (const auto &Entry : Infos) {
    Constant *FuncIdConst = constI32(Ctx, Entry.FuncId);
    Constant *BbIdConst = constI32(Ctx, Entry.BbId);
    Constant *AddrValue = ConstantExpr::getPtrToInt(Entry.Address, IntPtrTy);
    Entries.push_back(ConstantStruct::get(EntryTy, {FuncIdConst, BbIdConst, AddrValue}));
  }

  auto *ArrayTy = ArrayType::get(EntryTy, Entries.size());
  Constant *Init = ConstantArray::get(ArrayTy, Entries);

  auto *GV = new GlobalVariable(M, ArrayTy, true, GlobalValue::PrivateLinkage, Init,
                                "__bbtrace_pcmap");
  GV->setSection(".bbtrace_map");
  GV->setAlignment(Align(DL.getPointerSize()));
  appendToCompilerUsed(M, GV);
}

} // namespace

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {
      LLVM_PLUGIN_API_VERSION, "BasicBlockTracer", LLVM_VERSION_STRING,
      [](PassBuilder &PB) {
        PB.registerPipelineParsingCallback(
            [](StringRef Name, ModulePassManager &MPM, ArrayRef<PassBuilder::PipelineElement>) {
              if (Name == "bb-trace") {
                MPM.addPass(BasicBlockTracePass());
                return true;
              }
              return false;
            });
      }};
}


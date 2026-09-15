#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PIN = "31eabe1e534a70a2b7d5c39eb31e56a75c17be3b"
ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
changes = []


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")
    changes.append(rel)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {n}")
    return text.replace(old, new, 1)


head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
if head != PIN:
    raise SystemExit(f"Refusing to patch unexpected LibreOffice commit: {head} != {PIN}")

# 1. Emscripten platform: remove pthread/shared-memory flags only in ROW mode.
rel = "solenv/gbuild/platform/EMSCRIPTEN_INTEL_GCC.mk"
s = read(rel)
s = replace_once(
    s,
    "gb_EMSCRIPTEN_CPPFLAGS := -pthread -s USE_PTHREADS=1 -D_LARGEFILE64_SOURCE -D_LARGEFILE_SOURCE -s SUPPORT_LONGJMP=wasm\ngb_EMSCRIPTEN_LDFLAGS := $(gb_EMSCRIPTEN_CPPFLAGS)\n",
    "ifeq ($(ENABLE_EMSCRIPTEN_SINGLE_THREAD),TRUE)\n"
    "gb_EMSCRIPTEN_CPPFLAGS := -DROW_EMSCRIPTEN_SINGLE_THREAD=1 -D_LARGEFILE64_SOURCE -D_LARGEFILE_SOURCE -s SUPPORT_LONGJMP=wasm\n"
    "else\n"
    "gb_EMSCRIPTEN_CPPFLAGS := -pthread -s USE_PTHREADS=1 -D_LARGEFILE64_SOURCE -D_LARGEFILE_SOURCE -s SUPPORT_LONGJMP=wasm\n"
    "endif\n"
    "gb_EMSCRIPTEN_LDFLAGS := $(gb_EMSCRIPTEN_CPPFLAGS)\n",
    "platform cppflags",
)
s = replace_once(
    s,
    "ifeq ($(ENABLE_EMSCRIPTEN_PROXY_TO_PTHREAD),)\ngb_EMSCRIPTEN_LDFLAGS += -sPTHREAD_POOL_SIZE=7\nendif\n\n# Double the main thread stack size, but keep the default value for other threads:\ngb_EMSCRIPTEN_LDFLAGS += -sSTACK_SIZE=131072 -sDEFAULT_PTHREAD_STACK_SIZE=65536\n",
    "ifeq ($(ENABLE_EMSCRIPTEN_SINGLE_THREAD),)\n"
    "ifeq ($(ENABLE_EMSCRIPTEN_PROXY_TO_PTHREAD),)\n"
    "gb_EMSCRIPTEN_LDFLAGS += -sPTHREAD_POOL_SIZE=7\n"
    "endif\n"
    "endif\n\n"
    "# Double the main thread stack size. Only pthread builds need a pthread stack.\n"
    "gb_EMSCRIPTEN_LDFLAGS += -sSTACK_SIZE=131072\n"
    "ifeq ($(ENABLE_EMSCRIPTEN_SINGLE_THREAD),)\n"
    "gb_EMSCRIPTEN_LDFLAGS += -sDEFAULT_PTHREAD_STACK_SIZE=65536\n"
    "endif\n",
    "platform pthread pool",
)
write(rel, s)

# 2. comphelper ThreadPool: one logical lane, all work inline, no worker thread codegen.
rel = "comphelper/source/misc/threadpool.cxx"
s = read(rel)
s = replace_once(
    s,
    "#include <salhelper/thread.hxx>\n",
    "#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD\n"
    "#include <salhelper/simplereferenceobject.hxx>\n"
    "#else\n#include <salhelper/thread.hxx>\n#endif\n",
    "threadpool include",
)
start = "class ThreadPool::ThreadWorker : public salhelper::Thread\n"
end = "\nThreadPool::ThreadPool(std::size_t nWorkers)"
a = s.find(start)
b = s.find(end, a)
if a < 0 or b < 0:
    raise RuntimeError("threadpool worker class anchors missing")
original = s[a:b]
stub = (
    "#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD\n"
    "class ThreadPool::ThreadWorker : public salhelper::SimpleReferenceObject\n"
    "{\npublic:\n    explicit ThreadWorker(ThreadPool*) {}\n    void launch() {}\n    void join() {}\n};\n"
    "#else\n" + original + "\n#endif\n"
)
s = s[:a] + stub + s[b:]
needle = "std::size_t ThreadPool::getPreferredConcurrency()\n{\n"
repl = needle + "#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD\n    return 1;\n#else\n"
s = replace_once(s, needle, repl, "threadpool concurrency start")
marker = "\n    return ThreadCount;\n}\n\n// Used to order shutdown"
s = replace_once(s, marker, "\n    return ThreadCount;\n#endif\n}\n\n// Used to order shutdown", "threadpool concurrency end")
needle = "void ThreadPool::pushTask( std::unique_ptr<ThreadTask> pTask )\n{\n"
repl = needle + (
    "#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD\n"
    "    pTask->mpTag->onTaskPushed();\n"
    "    pTask->exec();\n"
    "    pTask->mpTag->onTaskWorkerDone();\n"
    "    return;\n"
    "#else\n"
)
s = replace_once(s, needle, repl, "threadpool push start")
marker = "\n    maTasksChanged.notify_one();\n}\n\nstd::unique_ptr<ThreadTask> ThreadPool::popWorkLocked"
s = replace_once(s, marker, "\n    maTasksChanged.notify_one();\n#endif\n}\n\nstd::unique_ptr<ThreadTask> ThreadPool::popWorkLocked", "threadpool push end")
write(rel, s)

# 3. configmgr: replace background configuration writer with synchronous persistence.
rel = "configmgr/source/components.cxx"
s = read(rel)
s = replace_once(
    s,
    "#include <salhelper/thread.hxx>\n",
    "#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD\n"
    "#include <salhelper/simplereferenceobject.hxx>\n"
    "#else\n#include <salhelper/thread.hxx>\n#endif\n",
    "configmgr include",
)
start = "class Components::WriteThread: public salhelper::Thread {\n"
end = "\nComponents & Components::getSingleton("
a = s.find(start)
b = s.find(end, a)
if a < 0 or b < 0:
    raise RuntimeError("configmgr WriteThread anchors missing")
original = s[a:b]
stub = (
    "#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD\n"
    "class Components::WriteThread: public salhelper::SimpleReferenceObject {\n"
    "public:\n    void trigger() {}\n    void flush() {}\n    void join() {}\n};\n"
    "#else\n" + original + "\n#endif\n"
)
s = s[:a] + stub + s[b:]
old = """    case ModificationTarget::File:
        if (!writeThread_.is()) {
            writeThread_ = new WriteThread(
                &writeThread_, *this, modificationFileUrl_, data_);
            writeThread_->launch();
        }
        writeThread_->trigger();
        break;
"""
new = """    case ModificationTarget::File:
#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD
        try {
            writeModFile(*this, modificationFileUrl_, data_);
        } catch (css::uno::RuntimeException &) {
            TOOLS_WARN_EXCEPTION("configmgr", "error writing modifications");
        }
#else
        if (!writeThread_.is()) {
            writeThread_ = new WriteThread(
                &writeThread_, *this, modificationFileUrl_, data_);
            writeThread_->launch();
        }
        writeThread_->trigger();
#endif
        break;
"""
s = replace_once(s, old, new, "configmgr write path")
write(rel, s)

# 4. Fast SAX: upstream forces mbEnableThreads=false on Emscripten. Remove dead thread codegen.
rel = "sax/source/fastparser/fastparser.cxx"
s = read(rel)
s = replace_once(
    s,
    "#include <salhelper/thread.hxx>\n",
    "#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD\n"
    "#include <salhelper/simplereferenceobject.hxx>\n"
    "#else\n#include <salhelper/thread.hxx>\n#endif\n",
    "fastparser include",
)
start = "class ParserThread: public salhelper::Thread\n"
end = "\nextern \"C\" {"
a = s.find(start)
b = s.find(end, a)
if a < 0 or b < 0:
    raise RuntimeError("fastparser ParserThread anchors missing")
original = s[a:b]
stub = (
    "#if defined __EMSCRIPTEN__ && defined ROW_EMSCRIPTEN_SINGLE_THREAD\n"
    "class ParserThread: public salhelper::SimpleReferenceObject\n"
    "{\npublic:\n    explicit ParserThread(FastSaxParserImpl*) {}\n    void launch() {}\n    void join() {}\n};\n"
    "#else\n" + original + "\n#endif\n"
)
s = s[:a] + stub + s[b:]
write(rel, s)

# 5. Backport the upstream headless SalInstance DoExecute signature fix.
# The pinned core has the new SalInstance::DoExecute() pure virtual, but its
# headless SvpSalInstance declaration/definition still take an obsolete exit-code
# reference. Current upstream fixes exactly these two signatures.
rel = "vcl/inc/headless/svpinst.hxx"
s = read(rel)
s = replace_once(
    s,
    "    bool DoExecute(int &nExitCode) override;\n",
    "    bool DoExecute() override;\n",
    "svpinst declaration",
)
write(rel, s)

rel = "vcl/headless/svpinst.cxx"
s = read(rel)
s = replace_once(
    s,
    "bool SvpSalInstance::DoExecute(int &)\n",
    "bool SvpSalInstance::DoExecute()\n",
    "svpinst definition",
)
write(rel, s)

report = {
    "pinnedCommit": PIN,
    "patchedFiles": changes,
    "mode": "headless-writer-no-pthread",
    "threadPoolLogicalLanes": 1,
    "threadPoolExecution": "synchronous-inline",
}
(ROOT / "row-patch-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))

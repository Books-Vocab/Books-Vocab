"""KG crash forensics — lldb stop-hook 自動取證。

問題：Xcode 攔截（真機）crash 時 iOS 不落 .ips，backtrace 只存在於 Xcode
debugger UI，agent 的唯一觀測介面淪為使用者螢幕截圖 + 人肉轉貼 lldb 輸出。

本模組讓任何 exception / 致命 signal stop 自動把全量證據寫進
$KG_LLDB_DUMP_DIR（預設 /tmp/kg_lldb_forensics）：
  - stop reason / process / target triple
  - 全量 frame 表（不截斷），含 fp 差分推得的每層 frame size
    （stack overflow 取證的關鍵：直接點名誰吃掉 stack）
  - selected thread 的 stack region（memory region $sp）
  - frame 0 registers
  - 其他 thread 的 top frames（截 20 條 thread）

安裝（一次，寫入 ~/.lldbinit，之後 Xcode / CLI lldb 全自動生效）：
    ops/install_lldb_forensics.sh
手動載入（既有 lldb session，例如 Xcode 正 paused 在案發現場）：
    (lldb) command script import /Users/chenliangyu/project/kg/ops/lldb_crash_forensics.py
手動 dump（任何 stop 點）：
    (lldb) kgdump

測試：ops/tests/test_lldb_crash_forensics.sh
"""

import datetime
import os
import sys

import lldb

# launch / attach 過程會有非致命 signal stop（spike 證實 exec 時有一次
# signal stop），只對致命集合 dump，避免每次啟動都噴檔案。
_FATAL_SIGNALS = {4, 6, 8, 10, 11}  # SIGILL, SIGABRT, SIGFPE, SIGBUS, SIGSEGV

_DEFAULT_DUMP_DIR = "/tmp/kg_lldb_forensics"

# (pid, stop_id) 去重：同一次 stop 可能多次進 handle_stop（多 thread）。
_seen_stops = set()


def _dump_dir():
    d = os.environ.get("KG_LLDB_DUMP_DIR", _DEFAULT_DUMP_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _frame_name(frame):
    name = frame.GetDisplayFunctionName() or frame.GetFunctionName()
    if not name:
        sym = frame.GetSymbol()
        name = sym.GetName() if sym and sym.IsValid() else "?"
    mod = frame.GetModule()
    mod_name = mod.GetFileSpec().GetFilename() if mod and mod.IsValid() else "?"
    return name or "?", mod_name or "?"


def _frame_table(thread):
    """全量 frame 表。frame i 的 size ≈ fp(i+1) - fp(i)（stack 向下長，
    caller fp 較高）；frame 0 在 fp1 缺失時 fallback 用 fp0 - sp。
    fp 缺失（0）或差分不合理（負值 / >64MB，如 async frame）標 '?'。"""
    lines = ["  idx  fp                 size(B)  function (module)"]
    n = thread.GetNumFrames()
    fps = []
    for i in range(n):
        fps.append(thread.GetFrameAtIndex(i).GetFP())
    sp0 = thread.GetFrameAtIndex(0).GetSP() if n else 0
    for i in range(n):
        frame = thread.GetFrameAtIndex(i)
        fp = fps[i]
        if i + 1 < n and fp and fps[i + 1] and 0 < fps[i + 1] - fp < (64 << 20):
            size = str(fps[i + 1] - fp)
        elif i == 0 and fp and sp0 and 0 < fp - sp0 < (64 << 20):
            size = str(fp - sp0)
        else:
            size = "?"
        name, mod = _frame_name(frame)
        lines.append("%5d  0x%016x %8s  %s (%s)" % (i, fp, size, name, mod))
    return "\n".join(lines)


def _write_dump(process, thread, trigger):
    target = process.GetTarget()
    exe = target.GetExecutable()
    proc_name = exe.GetFilename() or "unknown"
    pid = process.GetProcessID()
    stop_id = process.GetStopID()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    parts = []
    parts.append("== KG CRASH FORENSICS ==")
    parts.append("time:      %s" % datetime.datetime.now().isoformat())
    parts.append("trigger:   %s" % trigger)
    parts.append("process:   %s (pid %d, stop_id %d)" % (proc_name, pid, stop_id))
    parts.append("target:    %s" % (target.GetTriple() or "?"))
    parts.append("platform:  %s" % (target.GetPlatform().GetName() or "?"))

    if thread and thread.IsValid():
        desc = lldb.SBStream()
        thread.GetStatus(desc)
        parts.append("thread:    #%d tid=0x%x" % (thread.GetIndexID(), thread.GetThreadID()))
        parts.append("stop reason: %s" % (desc.GetData().splitlines()[0] if desc.GetData() else "?"))

        sp = thread.GetFrameAtIndex(0).GetSP() if thread.GetNumFrames() else 0
        parts.append("")
        parts.append("== STACK REGION (sp=0x%x) ==" % sp)
        # stop-hook 內 interpreter 無 current process，HandleCommand("memory
        # region") 會失敗；走 SBProcess API。
        region = lldb.SBMemoryRegionInfo()
        region_err = process.GetMemoryRegionInfo(sp, region)
        if region_err.Success():
            base, end = region.GetRegionBase(), region.GetRegionEnd()
            parts.append("region: [0x%x - 0x%x) size=%dKB perms=%s%s%s  sp-base=%dKB headroom" % (
                base, end, (end - base) // 1024,
                "r" if region.IsReadable() else "-",
                "w" if region.IsWritable() else "-",
                "x" if region.IsExecutable() else "-",
                (sp - base) // 1024))
        else:
            parts.append("(memory region unavailable: %s)" % region_err.GetCString())

        parts.append("")
        parts.append("== FRAMES (thread #%d, %d frames, fp-delta sizes) ==" % (
            thread.GetIndexID(), thread.GetNumFrames()))
        parts.append(_frame_table(thread))

        parts.append("")
        parts.append("== REGISTERS (frame 0, GPR) ==")
        # 同上：HandleCommand("register read") 在 stop-hook 內無 context，走 API。
        if thread.GetNumFrames():
            reg_sets = thread.GetFrameAtIndex(0).GetRegisters()
            gpr = reg_sets.GetValueAtIndex(0) if reg_sets.GetSize() else None
            if gpr:
                row = []
                for i in range(gpr.GetNumChildren()):
                    r = gpr.GetChildAtIndex(i)
                    row.append("%s=%s" % (r.GetName(), r.GetValue()))
                    if len(row) == 4:
                        parts.append("  " + "  ".join(row))
                        row = []
                if row:
                    parts.append("  " + "  ".join(row))
            else:
                parts.append("(registers unavailable)")

    parts.append("")
    parts.append("== OTHER THREADS (top 5 frames, max 20 threads) ==")
    count = 0
    for t in process:
        if thread and t.GetThreadID() == thread.GetThreadID():
            continue
        if count >= 20:
            parts.append("... (%d more threads truncated)" % (process.GetNumThreads() - count - 1))
            break
        count += 1
        parts.append("thread #%d tid=0x%x queue=%s" % (
            t.GetIndexID(), t.GetThreadID(), t.GetQueueName() or "?"))
        for i in range(min(5, t.GetNumFrames())):
            name, mod = _frame_name(t.GetFrameAtIndex(i))
            parts.append("    %2d %s (%s)" % (i, name, mod))

    d = _dump_dir()
    path = os.path.join(d, "%s_%s_%d_%d.txt" % (ts, proc_name, pid, stop_id))
    with open(path, "w") as f:
        f.write("\n".join(parts) + "\n")
    latest = os.path.join(d, "LATEST.txt")
    try:
        if os.path.lexists(latest):
            os.remove(latest)
        os.symlink(path, latest)
    except OSError:
        print(f"[kg-forensics] latest symlink update failed for {latest}: fallback to copy mode", file=sys.stderr)
        with open(latest, "w") as f:
            f.write("\n".join(parts) + "\n")
    return path


def _should_dump(thread):
    reason = thread.GetStopReason()
    if reason == lldb.eStopReasonException:
        return True
    if reason == lldb.eStopReasonSignal:
        signo = thread.GetStopReasonDataAtIndex(0) if thread.GetStopReasonDataCount() else 0
        return signo in _FATAL_SIGNALS
    return False


class KGCrashStopHook:
    """exception / 致命 signal stop 時自動 dump；breakpoint / step 不動作。"""

    def __init__(self, target, extra_args, internal_dict):
        pass

    def handle_stop(self, exe_ctx, stream):
        thread = exe_ctx.GetThread()
        process = exe_ctx.GetProcess()
        if not (thread and thread.IsValid() and process and process.IsValid()):
            return True
        if not _should_dump(thread):
            return True
        key = (process.GetProcessID(), process.GetStopID())
        if key in _seen_stops:
            return True
        # 失敗必須出聲：取證工具在唯一需要它的時刻靜默失敗 = 最壞結局。
        # lldb 會吞 stop-hook 內未捕捉的 Python 例外（實測零 traceback），
        # 所以這裡自己抓、自己印。成功才記 _seen_stops（失敗保留重試資格）。
        try:
            path = _write_dump(process, thread, "auto")
            _seen_stops.add(key)
            stream.Print("[kg-forensics] crash dump written: %s\n" % path)
        except Exception as e:  # noqa: BLE001 — 取證面，任何失敗都要可見
            stream.Print("[kg-forensics] dump FAILED: %r\n" % e)
        return True


def kgdump(debugger, command, exe_ctx, result, internal_dict):
    """任何 stop 點手動 dump（例如 Xcode 已 paused 的既有現場）。"""
    process = exe_ctx.GetProcess()
    thread = exe_ctx.GetThread()
    if not (process and process.IsValid() and process.GetState() == lldb.eStateStopped):
        result.SetError("kgdump: no stopped process")
        return
    try:
        path = _write_dump(process, thread, "manual")
    except Exception as e:  # noqa: BLE001 — 取證面，任何失敗都要可見
        result.SetError("kgdump FAILED: %r" % e)
        return
    result.AppendMessage("[kg-forensics] dump written: %s" % path)


def __lldb_init_module(debugger, internal_dict):
    # ~/.lldbinit 全域生效：這裡任何例外會在「每個」lldb session（含其他
    # 專案、Xcode）啟動時噴 traceback，所以整段防禦化；也不在 import 期
    # 建 dump dir（lazy，留到真的要寫時）。--overwrite 讓重複 import
    # （已裝 ~/.lldbinit 後又在 paused session 手動 import）不報錯。
    try:
        debugger.HandleCommand(
            "command script add --overwrite -f lldb_crash_forensics.kgdump kgdump")
        res = lldb.SBCommandReturnObject()
        debugger.GetCommandInterpreter().HandleCommand(
            "target stop-hook add -P lldb_crash_forensics.KGCrashStopHook", res)
        if res.Succeeded():
            print("[kg-forensics] armed: auto-dump on crash → %s (manual: kgdump)"
                  % os.environ.get("KG_LLDB_DUMP_DIR", _DEFAULT_DUMP_DIR))
        else:
            # ~/.lldbinit 在 target 建立前 source 時可能落到 dummy target；新
            # target 會繼承 dummy target 的 stop-hook（lldb 行為），這裡僅提示。
            print("[kg-forensics] stop-hook add: %s (kgdump 仍可用)" % (res.GetError() or "?").strip())
    except Exception as e:  # noqa: BLE001
        print("[kg-forensics] init failed: %r" % e)

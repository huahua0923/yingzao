# -*- coding: utf-8 -*-
"""长活作业：起子进程、收日志、判超时、限并发。

为什么要有这一层（而不是在路由里裸 `subprocess.Popen`）：

1. **一个进程一个端口之后，长活跑在管理进程里。** 原先这些活由 `_portal.py`(8144)
   或 `control.py`(8130) 各自起，卡住了只卡住那个进程；现在卡住的是**管着所有屏**的
   那个进程。所以三条必须有真的实现，不许只写在 `settings.py` 里：
   `job_timeout_s`（超时要真杀）、`job_max_concurrency`（并发要真限）、
   **日志要落文件**。
   ★ **超时是「每个作业一个」（2026-09-25 加的）**：`cfg.job_timeout_s` 是 7200
     （重建整栋三维那种活要几十分钟），而图谱那条 `--run` 是 900 秒级的
     （`_scratch/_retired_20260925/_kg_view.py` 原文就是这个数）。共用一个 7200 的后果不是"更宽松"，
     是**那条闸门对图谱这一支等于不存在** —— 一个卡死的判据会占着槽位两小时，
     而屏幕上写着「运行中」，看不出是它还是真在算。⇒ `Job.timeout_s` 存**解析后
     的那个数**，`reap()` 与屏幕都读它：设置里那个值从此只是**缺省**，不是最终值。
2. **`stdout=PIPE` 不抽干 = 死锁**（本仓铁律 14，实测白等 11 分钟）：子进程输出一超
   管道缓冲就永远写不下去。⇒ 这里一律把 stdout/stderr 接到**文件**上，不接管道。
3. **「进程起来了」≠「它在干活」**（铁律 20）：所以状态机分 `running / ok / failed /
   timeout`，**退出码单独一个字段**；"跑完了但失败"与"跑完了且成功"必须在屏幕上
   长得不一样。

★ 两处刻意的取舍，写在明面上：

  · **超时是"读到才判"**：`reap()` 在每次 `start()` 与每次查询时跑一遍。这**不是**后台
    定时器 —— 没人看的时候，一个卡死的作业会一直占着槽位。之所以够用：下一次
    `start()` 会先 `reap()`，于是"想开新的"那一刻，卡死的旧的一定先被清掉。
    换成后台线程的代价是长活进程里多一个没人监督的循环，且它对"槽位被占"这件事
    并没有改善。**但记忆里要说实话**：`state.json` 里的 `timeout` 是"某次读的时候
    发现已经超时了"，不是"正好在超时那一刻杀的"。
  · **`job_persist` 落的是终态**：作业跑完（或被杀）写一份 `<id>.json`。进程重启后
    `get()` 读不到内存就回落到那份文件 —— 这就是 settings 里说的"能报出孤儿作业"。
    运行中的作业**不**落盘：进程没了，它也就没了，假装它还在跑才是谎报。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from ..responses import ApiError
from ..settings import Settings

#: 内存里最多留多少个作业（含已结束的）。长活进程不能让它无界长 —— 这是本仓
#: `control.py:126` 的 `_FLOOR_CACHE` 那个坑的同族（无界字典 = 泄漏），
#: 区别是这里的"丢"是**明说的**：超出的老作业从内存里掉出去，但盘上有终态 JSON。
MAX_KEEP = 40

#: 终态集合。`lost` = 内存里没有、盘上也没有（进程重启且没落盘）—— 与"没跑过"分开。
TERMINAL = ("ok", "failed", "timeout")


@dataclass
class Job:
    id: str
    mode: str
    label: str
    argv: list
    cwd: str
    log: str
    pid: int
    started_wall: str
    started_mono: float
    proc: object = None
    state: str = "running"
    exit_code: int | None = None
    ended_wall: str | None = None
    note: str = ""
    #: 这个作业自己的超时（秒）；`None` = 无上限。★ 起作业时解析**一次**并存在这里
    #: （`start()` 里 `timeout_s or cfg.job_timeout_s`），于是 `reap()` 判的、
    #: 屏幕上报的是**同一个数** —— 不会再出现"设置里写着 7200、这个作业其实按 900 跑"
    #: 这种只有读代码才知道的事。
    timeout_s: int | None = None
    extra: dict = field(default_factory=dict)

    def public(self) -> dict:
        """给前端的形状。**每个字段都要能自己说话**，不要让它去猜。"""
        return {
            "id": self.id, "mode": self.mode, "label": self.label,
            "pid": self.pid, "state": self.state,
            "exit_code": self.exit_code,          # 没跑完 = None，不是 0
            "started": self.started_wall, "ended": self.ended_wall,
            "elapsed_s": round((time.monotonic() - self.started_mono), 1),
            "log": self.log, "argv": self.argv, "cwd": self.cwd,
            # 单位是秒；`None` = 这个作业不判超时（不是"0 秒"）。
            "timeout_s": self.timeout_s,
            "note": self.note, **self.extra,
        }


#: 进程内存里的登记表（有界）。key = job id，插入序 = 开始序。
_JOBS: "OrderedDict[str, Job]" = OrderedDict()


def _jobs_dir(cfg: Settings) -> Path:
    return Path(cfg.resolved_data_dir) / "_jobs"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def child_env() -> dict:
    """子进程的环境：**中文日志必须 utf-8**，否则落下来的是一屏乱码。

    ★ 本仓记过这一条（memory: gbk-mangled-log-units）：`PYTHONIOENCODING` 不给，
      Windows 上子进程按 GBK 写，日志里中文全成乱码，而**乱码不会报错** ——
      它只是让人读不懂，于是"日志在这儿"这条退路在需要它的那天正好失效。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _kill_tree(proc) -> bool:
    """把子进程**连它的孩子**一起杀掉。回 True = 走了 taskkill。

    ★ 为什么不能只 `proc.kill()`：这些脚本自己会再起子进程（`_system.py` 逐栋调
      `run_step.py`）；只杀父进程会留下一群孤儿继续占 CPU 与文件锁，而屏幕上
      那条作业已经写着"超时已杀"。本仓铁律 20(b) 就是这个形状（Git Bash 的
      `kill` 杀不掉 Windows 进程，孤儿还占着端口，curl 却能拿到 200）。
    """
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.kill()
    except OSError:
        pass
    return False


def _finish(job: Job, cfg: Settings, state: str, exit_code, note: str = "") -> None:
    job.state = state
    job.exit_code = exit_code
    job.ended_wall = _now()
    if note:
        job.note = note
    job.proc = None
    if cfg.job_persist:
        try:
            d = _jobs_dir(cfg)
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / (job.id + ".json.tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(job.public(), fh, ensure_ascii=False, indent=1)
            os.replace(tmp, d / (job.id + ".json"))
        except OSError as ex:      # 落盘失败不该把作业本身也毁了
            job.extra["persist_error"] = "%s: %s" % (type(ex).__name__, ex)


def reap(cfg: Settings) -> None:
    """推进所有在跑的作业：跑完的收尾、超时的杀掉。**每次读都顺手跑一遍。**

    ★ 超时读的是 **`job.timeout_s`（起作业时解析好的那个数）**，不是 `cfg.job_timeout_s`
      —— 后者只是缺省。共用一个全局值的后果见模块头那一段：图谱那条 900 秒的活
      会被 7200 的闸门放过，于是"超时"这件事对它**一次都不会触发**。
    """
    for job in list(_JOBS.values()):
        if job.state != "running" or job.proc is None:
            continue
        rc = job.proc.poll()
        if rc is not None:
            _finish(job, cfg, "ok" if rc == 0 else "failed", rc)
            continue
        limit = job.timeout_s
        if limit is None or limit <= 0:          # ≤0 / 没给 = 这个作业不判超时
            continue
        spent = time.monotonic() - job.started_mono
        if spent > limit:
            _kill_tree(job.proc)
            _finish(job, cfg, "timeout", None,
                    note="超过 timeout_s=%ds（此判定发生在读到时，不是正好那一刻）"
                         % limit)
    # 有界：超出 MAX_KEEP 的**已结束**作业从内存里掉出去（盘上仍有终态 JSON）
    while len(_JOBS) > MAX_KEEP:
        for key, old in list(_JOBS.items()):
            if old.state != "running":
                _JOBS.pop(key, None)
                break
        else:
            break


def _read_persisted(cfg: Settings, job_id: str) -> dict | None:
    p = _jobs_dir(cfg) / (job_id + ".json")
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        # 读不动就说读不动：把坏 JSON 当"没有这个作业"会让"产物损坏"与"没跑过"同形。
        return {"id": job_id, "state": "lost", "note": "终态记录存在但读不动：%s" % p.name,
                "exit_code": None, "elapsed_s": None}


#: 作业 id 的形状。★ 这不是洁癖，是一条**实测可达的读取原语**的闸门：
#: `get()` 把 id 拼成 `data/_jobs/<id>.json` 去读，而 `job_id` 来自 URL ——
#: `../../_meta/<某个>.json` 这种串会读到**别的 JSON 并原样从响应里回出去**，
#: 而且它在"局域网只读"的访问上照样可用（读路径不过 `require_compute`）。
#: ⇒ 闸门放在**把 id 变成路径的那一处**（`get`），不放在各个路由里：
#:   路由有三个（`/kg/run/<id>`、`/console/jobs/<id>`、以及将来的），
#:   名单式判断只会往漏的方向漂（铁律 29）。
#: ★ 排除 `.` 是关键 —— `..` 靠它才成立。id 由 `start()` 生成，形状是
#:   `<mode>-<YYYYMMDD>-<HHMMSS>[-<n>]`，`mode` 是调用方给的字面量（`kg-run` /
#:   `console` / …），全在这个字符集内。
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def get(cfg: Settings, job_id: str) -> dict | None:
    """一个作业的当前状态：内存 → 盘上的终态。都没有 = None（不是"在跑"）。

    ★ 形状不对 ⇒ **直接 None**（= 路由那边回 404），不去盘上试 ——
      "这个 id 不在我可寻址的范围里"与"这里没有这个作业"是两件事，
      但它们的**答案**在这一屏上是同一个（没有作业可看），而后者是安全的那个。
      `_read_persisted` 自己不加这道闸门：它的另一个调用方（`listing`）拿的是
      **盘上真实文件名**，不是外部输入 —— 闸门只该加在边界上。
    """
    reap(cfg)
    if not JOB_ID_RE.match(job_id or ""):
        return None
    job = _JOBS.get(job_id)
    if job is not None:
        return job.public()
    return _read_persisted(cfg, job_id)


#: 读日志尾巴的上限（字节）。★ 这个数只许有一处：读这些日志的**有两个**消费者
#: （图谱的 `run_report` 要解析尾部那段 JSON、控制台的 `jobs/<id>` 要给人看全文），
#: 各写一份的结局是"图谱截在 512KB、控制台截在别处"，而且**两边都不报这件事**。
LOG_TAIL_BYTES = 512 * 1024


def log_tail(path, nbytes: int = LOG_TAIL_BYTES) -> tuple[str, int | None]:
    """读日志文件的最后 `nbytes` 字节 → `(文本, 被截掉的字节数或 None)`。

    ★ 为什么 `Job.public()` 里的 `log` 是**路径**而这里给的是**文本**：路径是
      作业记录自己要记的（进程重启后还能找到那盘文件），而页面要的是内容 ——
      把路径当内容发出去，屏幕上会出现一个"看起来像日志"的字符串（就那一行路径），
      前端只能靠自己 `fetch` 一次，而那条路没有信封、没有截断说明。
    ★ 截断了**要说**：否则那份被切掉开头的输出会解析失败，而"解析失败"在这一屏上
      与"没有输出"长得一样（铁律 16、38）。返回被截掉多少，调用方原样报出来。
    ★ 文件不在/读不动 ⇒ `("", None)`，**不是**抛错：作业刚起、日志还没建出来是常态。
      调用方要能分开"空日志"与"读不到"——那就去看 `Job.state` 与 `note`。
    """
    if not path:
        return "", None
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            cut = max(0, size - nbytes)
            fh.seek(cut)
            return fh.read().decode("utf-8", "replace"), (cut or None)
    except OSError:
        return "", None


def listing(cfg: Settings, limit: int = 10) -> list:
    """最近的作业，新的在前。内存 +（内存里没有的）盘上终态。"""
    reap(cfg)
    mem = [j.public() for j in reversed(list(_JOBS.values()))]
    seen = {m["id"] for m in mem}
    d = _jobs_dir(cfg)
    older = []
    if d.is_dir():
        names = sorted((p.name for p in d.glob("*.json")), reverse=True)
        for name in names:
            jid = name[:-5]
            if jid in seen:
                continue
            rec = _read_persisted(cfg, jid)
            if rec is not None:
                older.append(rec)
    return (mem + older)[:limit]


def active(cfg: Settings) -> dict | None:
    """正在跑的那一个（若有）。`status` 的 `running` / `mode` 读它。"""
    reap(cfg)
    for j in reversed(list(_JOBS.values())):
        if j.state == "running":
            return j.public()
    return None


def running_count(cfg: Settings) -> int:
    reap(cfg)
    return sum(1 for j in _JOBS.values() if j.state == "running")


def start(cfg: Settings, *, mode: str, label: str, argv: list,
          cwd=None, extra: dict | None = None, timeout_s: int | None = None) -> Job:
    """起一个作业。并发到顶 ⇒ **409 并点名**是谁占着，不默默排队、不默默丢弃。

    ★ 为什么要点名：用户手上可能根本没有那个作业（他在命令行另一个窗口里跑的），
      只说"上一个还在跑"就等于让他去猜、去翻日志（本仓铁律 32 的结论）。

    ★ `timeout_s` 不给 ⇒ 用 `cfg.job_timeout_s`（缺省）。**解析一次、存进 `Job`**，
      于是判的与报的是同一个数；≤0 或 `None` = 这个作业不判超时。
    """
    reap(cfg)
    cap = max(1, int(cfg.job_max_concurrency))
    if running_count(cfg) >= cap:
        cur = active(cfg) or {}
        raise ApiError(409, "job_busy",
                       "同时只允许 %d 个作业在跑，现在占着的是「%s」"
                       % (cap, cur.get("label") or cur.get("mode") or "?"),
                       {"max_concurrency": cap, "running": cur})

    # ★ 超时在**起作业这一刻**解析成定值（缺省 = 设置里那个）。≤0 与 None 都表示
    #   "不判超时" —— 与 `settings.job_timeout_s` 的既有语义保持一致（那里 ≤0 也是
    #   这个意思），别在这里发明第二种说法。
    limit = cfg.job_timeout_s if timeout_s is None else int(timeout_s)
    if limit is not None and limit <= 0:
        limit = None

    jobs_dir = _jobs_dir(cfg)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    fid = mode if mode else "job"
    n = 1
    while (fid + "-" + stamp + ("-%d" % n if n > 1 else "")) in _JOBS:
        n += 1
    job_id = fid + "-" + stamp + ("-%d" % n if n > 1 else "")
    log_path = jobs_dir / (job_id + ".log")

    # ★ 输出写**文件**，不写管道（铁律 14）。父进程随后立刻关掉自己那一份 ——
    #   句柄已经复制进子进程，父进程留着只会在 Windows 上多一道文件锁。
    fh = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u"] + list(argv),
            cwd=str(cwd or cfg.root), env=child_env(),
            stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as ex:
        fh.close()
        raise ApiError(500, "job_spawn_failed",
                       "起不了这个作业：%s" % ex,
                       {"argv": [str(a) for a in argv]}) from ex
    finally:
        try:
            fh.close()
        except OSError:
            pass

    job = Job(id=job_id, mode=mode, label=label,
              argv=[str(a) for a in argv], cwd=str(cwd or cfg.root),
              log=str(log_path), pid=proc.pid,
              started_wall=_now(), started_mono=time.monotonic(),
              timeout_s=limit, proc=proc, extra=dict(extra or {}))
    _JOBS[job_id] = job
    return job

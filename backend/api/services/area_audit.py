# -*- coding: utf-8 -*-
"""面积对账数据源 —— **图纸自带的面积表** ↔ 模型逐层楼板面积。

这份数据是本项目最值钱的一把外部量具：它不是我们自己算的数，是画图人
写在图里的数（DXF 里的 ACAD_TABLE）。模型对不对，拿它一比就有结论。

**但算它需要 ezdxf + shapely + 读 DXF**（几十秒到几分钟），所以：

  · 读路径（GET）**只解析已落盘的日志**，绝不现算 —— 只服务模式下
    服务器 venv 里没有 ezdxf，现算会直接 ImportError，或者逼着服务器装全套重依赖，
    那条"依赖层"防线就废了。
  · 现算（POST refresh）是写操作：compute 门禁 + 子进程，且把结果落盘成日志，
    下次 GET 就读到它。

★ 一处刻意的诚实：读路径回的是**带时间戳的快照**，不是"此刻的真实"。
  日志文件与它的 mtime 一起回给前端，前端必须把"这份对账是什么时候跑的"
  显示出来 —— 归档报告只反映 copy 那刻（memory: qa-baseline-is-copy-time-not-rerun）。
  后台如果把它当成实时数据展示，就是在帮它撒谎。
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from pathlib import Path

from ..responses import ApiError

# 对账脚本：不在 data/ 里，是仓库根的 _scratch/ 工具脚本。
# 刻意**不搬进 backend/**：它是"调试好的"量具（CLAUDE.md 铁律：调试好的代码禁止再修改），
# 搬动会顺手改坏判据。这里只当它是外部命令来调。
SCRIPT_REL = os.path.join("_scratch", "_area_audit.py")

# 楼栋行：`c047        1   21371.4㎡   21371.4㎡   F0(图纸5350.9/模型26722.3)`
_ROW_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_-]+)\s+(?P<n>\d+)\s+(?P<avg>-?[\d.]+)㎡\s+"
    r"(?P<worst>-?[\d.]+)㎡\s+F(?P<wf>\d+)\(图纸(?P<wa>[\d.]+)/模型(?P<wm>[\d.]+)\)\s*$")
# 逐层行：`   1层 图纸  6751.30  模型  3892.70  差  -2858.6   房间数 21`
_FLOOR_RE = re.compile(
    r"^\s*(?P<k>\d+)层\s+图纸\s*(?P<a>-?[\d.]+)\s+模型\s*(?P<m>-?[\d.]+)\s+"
    r"差\s*(?P<d>[-+]?[\d.]+)\s+房间数\s*(?P<rooms>\S*)\s*$")
_BAD_RE = re.compile(r"^\s{3}(?P<name>[A-Za-z0-9_-]+)\s+(?P<why>\S.*)$")
_TITLE_RE = re.compile(r"^---\s+(?P<name>[A-Za-z0-9_-]+)\s+逐层")


def find_log(root: Path) -> Path | None:
    """最新的一份全库对账日志。带日期后缀，取 mtime 最新的那份 ——
    并把这个事实（哪份、什么时候）回给前端。"""
    cands = [Path(p) for p in
             glob.glob(str(root / "_scratch" / "_area_audit_fleet_*.log"))]
    cands = [p for p in cands if p.is_file()]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def parse_fleet(text: str) -> dict:
    """把日志文本解析成结构化。**解析不到就报空，不编。**"""
    rows, unauditable, per_floor = [], [], {}
    cur = None
    for line in text.splitlines():
        m = _TITLE_RE.match(line)
        if m:
            cur = m.group("name")
            per_floor.setdefault(cur, [])
            continue
        m = _ROW_RE.match(line)
        if m:
            rows.append({
                "name": m.group("name"), "pairs": int(m.group("n")),
                "avg_m2": float(m.group("avg")), "worst_m2": float(m.group("worst")),
                "worst_floor": int(m.group("wf")),
                "worst_drawing_m2": float(m.group("wa")),
                "worst_model_m2": float(m.group("wm")),
            })
            continue
        m = _FLOOR_RE.match(line)
        if m and cur:
            per_floor[cur].append({
                "drawing_floor": int(m.group("k")),
                "model_floor": int(m.group("k")) - 1,
                "drawing_m2": float(m.group("a")), "model_m2": float(m.group("m")),
                "delta_m2": float(m.group("d")),
                "drawing_rooms": (int(m.group("rooms"))
                                  if m.group("rooms").isdigit() else None),
            })
            continue
        m = _BAD_RE.match(line)
        if m and not m.group("name").startswith("平均") and "㎡" not in line:
            unauditable.append({"name": m.group("name"), "why": m.group("why")})
    rows.sort(key=lambda r: -abs(r["avg_m2"]))
    for r in rows:
        r["abs_m2"] = abs(r["avg_m2"])
        r["verdict"] = _verdict(r["avg_m2"])
    # 「无法对账」的楼**原样**回给前端，不因为"不是有效行"就丢掉：
    # 「没量过」和「全对」在汇总里长得一模一样，是本项目反复栽的坑
    # （memory: gauge-coverage-invisible-in-summary）。宁可多一栏，也不让它消失。
    return {"rows": rows, "unauditable": unauditable, "per_floor": per_floor}


def _verdict(delta: float) -> str:
    # 门槛：±200㎡ 内算对得上（口径差：墙厚外皮 + 屋面块）。
    # ★ 这是**逐项**判据，不是"整栋平均值小于阈值就过" ——
    #   单个例外不该翻掉整组结论，也不该被平均值抹平
    #   （memory: per-item-count-not-max-threshold）。
    a = abs(delta)
    if a <= 200:
        return "reconciled"
    if a <= 800:
        return "watch"
    return "gap"


def fleet(repo_root: Path) -> dict:
    log = find_log(repo_root)
    if log is None:
        return {"source": None, "rows": [], "unauditable": [], "per_floor": {},
                "hint": "还没有对账日志。跑 `python -u _scratch/_area_audit.py` "
                        "（不带参数 = 全库）后刷新本页。"}
    st = log.stat()
    parsed = parse_fleet(log.read_text(encoding="utf-8", errors="replace"))
    parsed["source"] = {"file": log.name, "mtime": st.st_mtime,
                        "mtime_iso": _iso(st.st_mtime), "bytes": st.st_size}
    parsed["counts"] = {
        "audited": len(parsed["rows"]),
        "reconciled": sum(1 for r in parsed["rows"] if r["verdict"] == "reconciled"),
        "watch": sum(1 for r in parsed["rows"] if r["verdict"] == "watch"),
        "gap": sum(1 for r in parsed["rows"] if r["verdict"] == "gap"),
        "unauditable": len(parsed["unauditable"]),
    }
    return parsed


def _iso(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def refresh(repo_root: Path, name: str, timeout_s: int) -> dict:
    """现算一栋（写操作，已过 compute 门禁）。

    子进程而不是函数调用：脚本 `sys.path` 魔法很重（它自己往 sys.path 塞三个目录），
    在进程内跑会污染本进程的 import 表。隔离跑最省心 —— 而且它崩了不会带走服务。
    """
    script = repo_root / SCRIPT_REL
    if not script.is_file():
        raise ApiError(500, "audit_script_missing",
                       "找不到对账脚本：%s" % SCRIPT_REL)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        # 输出走 PIPE 但**同时**由 communicate() 抽干 —— 这里用的是 run()，
        # 它边跑边收，不会出现"子进程写满管道卡死"那种死锁。
        p = subprocess.run([sys.executable, "-u", str(script), name],
                           cwd=str(repo_root), env=env, timeout=timeout_s,
                           capture_output=True,
                           # 系统编码可能是 GBK；不 decode 成 utf-8 中文全变糊字
                           # （memory: gbk-mangled-log-units）。
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise ApiError(504, "audit_timeout",
                       "对账超时（%ds）——这栋楼图元太多或 DXF 太大" % timeout_s,
                       {"building": name, "timeout_s": timeout_s}) from None
    if p.returncode != 0:
        raise ApiError(500, "audit_failed", "对账脚本退出码 %d" % p.returncode,
                       {"stderr": (p.stderr or "")[-4000:]})
    parsed = parse_fleet(p.stdout or "")
    hit = next((r for r in parsed["rows"] if r["name"] == name), None)
    if hit is None:
        # 脚本没报这栋楼的偏差 ⇒ 多半是"DXF 里没有面积表"。原样说出来，
        # 别回一个空对象让前端以为"它对上了"。
        why = next((u["why"] for u in parsed["unauditable"] if u["name"] == name),
                   "脚本没有为这栋楼产出对账行")
        return {"name": name, "audited": False, "why": why,
                "floors": parsed["per_floor"].get(name, []),
                "stdout_tail": (p.stdout or "")[-4000:]}
    return {"name": name, "audited": True, **hit,
            "floors": parsed["per_floor"].get(name, [])}

# -*- coding: utf-8 -*-
"""给「所有检查一页」生成索引：每个闸一行 —— 编号 / 说明 / 该读哪个结果文件 / 档位。

★ 为什么要有这个文件：页面是静态的，浏览器列不出目录；而**手写闸名单**会漂
  （新增一个闸页面里永远看不见 —— 铁律 174：同一个量不许有第二份手抄副本）。
  所以名单从 `gates/*.py` **现扫**：说明取各闸 docstring 首行，档位取
  `tools/gate_tiers.py`（唯一来源），结果文件取 `_out` 里**该闸最新的一份**。

用法:  python -I -X utf8 tools/build_gates_index.py
产物:  gates/_out/_page_index.json
"""
import ast
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATES = os.path.join(ROOT, "gates")
OUT = os.path.join(GATES, "_out")
TIER_ORDER = ["quick", "dxf", "cad", "other"]

# 结果文件名里这些是别的楼的读数/中间件，不当「这个闸的代表读数」
SKIP_RE = re.compile(r"(\.run|\.baseline|_probe|_tamper|_ledger|^matrix|^defects)")


def tier_map():
    sys.path.insert(0, HERE)
    try:
        import gate_tiers as t
        return dict(getattr(t, "TIER", {}))
    except Exception:                                                  # noqa: BLE001
        return {}


def first_line(doc):
    for ln in (doc or "").strip().splitlines():
        ln = ln.strip()
        if ln and not set(ln) <= set("=-— "):
            return ln
    return ""


def title_of(gid, doc):
    """说明 = docstring 首行去掉「判据 / 闸号 / 破折号 / 粗体星号」。"""
    s = first_line(doc)
    s = re.sub(r"^判据\s*", "", s)
    s = re.sub(r"^%s\s*[-—:：]*\s*" % re.escape(gid), "", s).strip()
    s = s.replace("**", "").strip(" —-—:：")
    return s[:60]


def newest_result(gid, files):
    """优先 `<闸>.c006.json`，其次 `<闸>.json`，都没有就取该闸最新的一份。"""
    cand = [f for f in files
            if f == gid + ".json" or f.startswith(gid + ".") or f.startswith(gid + "_")]
    cand = [f for f in cand if not SKIP_RE.search(f)]
    for exact in (gid + ".c006.json", gid + ".json"):
        if exact in cand:
            return exact
    if not cand:
        return None
    return max(cand, key=lambda f: os.path.getmtime(os.path.join(OUT, f)))


def resolve(gid, files):
    """文件名里的说明后缀不带进闸号：`J-10.0-01-docx_sync.py` 的闸号是 `J-10.0-01`。

    ★ 判据：**结果文件有没有**。没有就沿 `-` 往回退一段再试；
      退到 `J-10` 还没找到就停（防止把闸号退成 `J`）。
      退不下来就保留原名 —— 「还没跑过」也要能显示，不能因为没结果就把闸藏了。
    """
    cur = gid
    while True:
        if newest_result(cur, files):
            return cur, newest_result(cur, files)
        if cur.count("-") <= 1:
            return gid, None
        cur = cur.rsplit("-", 1)[0]


def main():
    files = [f for f in os.listdir(OUT) if f.endswith(".json") and not f.startswith("_")]
    tiers = tier_map()
    rows = []
    for fn in sorted(os.listdir(GATES)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        gid = fn[:-3].split("_")[0]
        if not gid.startswith("J-"):
            continue
        gid, res = resolve(gid, files)
        # ★ 用 ast 取 docstring：有的闸 docstring 长达几千字，按「前 2000 字找闭合引号」
        #   会**静默取不到**（J-10.9-07 / J-10.2-02 实测验过）—— 不是没说明，是没读到。
        with open(os.path.join(GATES, fn), "r", encoding="utf-8",
                  errors="replace") as fh:
            src = fh.read()
        try:
            doc = ast.get_docstring(ast.parse(src)) or ""
        except SyntaxError:
            m = re.search(r'"""(.*?)"""', src, re.S)
            doc = m.group(1) if m else ""
        rows.append({
            "id": gid,
            "file": res,
            "title": title_of(gid, doc),
            "tier": tiers.get(gid, "other"),
            "mtime": (datetime.datetime.fromtimestamp(
                os.path.getmtime(os.path.join(OUT, res))).isoformat(timespec="seconds")
                if res else ""),
        })

    rows.sort(key=lambda r: (TIER_ORDER.index(r["tier"]) if r["tier"] in TIER_ORDER
                             else 99, r["id"]))
    p = os.path.join(OUT, "_page_index.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"schema": "cdut3d-gates-index/1",
                   "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                   "gates": rows}, f, ensure_ascii=False, indent=1)
    have = sum(1 for r in rows if r["file"])
    print("写出 %s：%d 个闸，其中 %d 个有结果文件" % (p, len(rows), have))
    for r in rows:
        print("  %-14s %-6s %s" % (r["id"], r["tier"], r["title"][:40]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

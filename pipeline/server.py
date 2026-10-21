# -*- coding: utf-8 -*-
"""8800 · 第六教学楼「从图纸到模型」流程台

一个页面，七段：
  ① 原图  ② 识别  ③ 重画  ④ 审图  ⑤ 建模  ⑥ 出件  ⑦ 交付包

★ 页面上的每个数都**现算**（铁律 103/174）：目录里有什么文件、JSON 里写着什么，
  就读什么；不手打、不留第二份副本。
★ 参数（值/标注/作用）直接读 `rebuild/构件库/参数.json` —— 那是唯一真源，
  这里只做「摊平 + 归到哪一段」。

用法：python -I -X utf8 pipeline/server.py [--port 8800]
"""
import argparse
import datetime
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # D:\项目\cdut3d
MIME = {
    ".glb": "model/gltf-binary", ".gltf": "model/gltf+json",
    ".dxf": "application/dxf", ".obj": "text/plain; charset=utf-8",
    ".skp": "application/octet-stream", ".md": "text/plain; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json",
    ".html": "text/html; charset=utf-8", ".css": "text/css",
    ".js": "application/javascript",
}

# 参数归段：前缀 → 段 id。参数只在这一张表里「归类」，值/作用一个字不抄。
PARAM_STAGE = [
    ("共用/环_最短边下限", "recognize"),
    ("共用/房间_面积下限", "recognize"),
    ("共用/墙带来源", "recognize"),
    ("共用/墙厚", "redraw"),
    ("共用/层高", "build"),
    ("门/", "build"),
    ("楼梯/", "build"),
    ("竖井/", "build"),
    ("顶部/", "build"),
]

# 给普通人直接拖的旋钮：只挑这几个（全量 61 个放在页面底部的折叠里）。
# 值 / 单位 / 标注 / 作用 一律从 参数.json 取；这里只写「给谁、什么范围」。
KNOBS = [
    ("raw", "地上楼层数", "@n_above", 1, 30, 1),
    ("recognize", "房间面积下限", "构件/共用/房间_面积下限", 0.5, 20, 0.5),
    ("redraw", "墙厚", "构件/共用/墙厚", 100, 500, 10),
    ("build", "层高", "构件/共用/层高", 2500, 6000, 100),
    ("build", "门洞高", "构件/门/洞高", 1800, 3000, 50),
    ("build", "女儿墙高", "构件/顶部/女儿墙高", 0, 2000, 100),
    ("build", "楼梯踢面", "构件/楼梯/踢面", 120, 200, 1),
    ("out", "轮廓最短边", "构件/共用/环_最短边下限", 1, 50, 0.25),
]

# 五个参数化过的闸 → 它守着哪一段（闸的读数一律从 `_out/*.json` 现读）
GATE_STAGE = {
    "J-10.8-00": "out",
    "J-10.9-07": "out",
    "J-10.8-01": "build",
    "J-10.8-04": "build",
    "J-10.9-08": "build",
}


def jload(rel, default=None):
    p = os.path.join(ROOT, rel)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                              # noqa: BLE001
        return default


def size(rel):
    p = os.path.join(ROOT, rel)
    return os.path.getsize(p) if os.path.isfile(p) else 0


def mb(n):
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % max(1, n // 1024)


def files_in(rel, ext):
    d = os.path.join(ROOT, rel)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.lower().endswith(ext))


def floor_key(fn):
    """「地下1层」排最前，其余按层号。文件名排序会把 10层 排到 1层 前面。"""
    head = fn.split("层")[0]
    if head.startswith("地下"):
        try:
            return -100 + int(head[2:])
        except ValueError:
            return -999
    try:
        return int(head)
    except ValueError:
        return 999


def relurl(rel):
    return "/files/" + urllib.parse.quote(rel.replace("\\", "/"))


def collect_params():
    """把 参数.json 里的叶子摊平：路径 / 值 / 单位 / 标注 / 作用 → 一段。"""
    doc = jload("rebuild/构件库/参数.json", {}) or {}
    out = []

    def stage_of(path):
        # 参数路径以「构件/」开头；归段表里写的是「构件/」下面那一层
        rel = path[len("构件/"):] if path.startswith("构件/") else path
        for pre, sid in PARAM_STAGE:
            if rel == pre or rel.startswith(pre):
                return sid
        return ""

    def walk(node, path):
        if isinstance(node, dict):
            if "值" in node:
                st = stage_of(path)
                out.append({
                    "path": path,
                    "group": path.split("/")[1] if path.count("/") >= 1 else "",
                    "name": path.rsplit("/", 1)[-1],
                    "value": node.get("值"),
                    "unit": node.get("单位") or "",
                    "tag": node.get("标注") or "",
                    "effect": node.get("作用") or "",
                    "source": node.get("出处") or "",
                    "range": node.get("区间"),
                    "stage": st,
                })
                return
            for k, v in node.items():
                walk(v, path + "/" + k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, "%s[%d]" % (path, i))

    walk(doc.get("构件", {}), "构件")
    return out


def collect_knobs(params, model):
    """旋钮 = 参数.json 里的真值 + 一个可拖的范围。值不另抄。"""
    by_path = {p["path"]: p for p in params}
    out = []
    for stage, name, path, lo, hi, step in KNOBS:
        if path == "@n_above":
            out.append({"stage": stage, "name": name, "path": path,
                        "value": model["n_above"], "unit": "层",
                        "tag": "现件", "why": "参与建模的地上楼层数",
                        "min": lo, "max": hi, "step": step})
            continue
        p = by_path.get(path)
        if not p:
            continue
        out.append({"stage": stage, "name": name, "path": path,
                    "value": p["value"], "unit": p["unit"],
                    "tag": p["tag"], "why": p["effect"],
                    "source": p.get("source") or "",
                    "min": lo, "max": hi, "step": step})
    return out


STD_RE = re.compile(
    r"(?:GB/T|GB|JGJ/T|JGJ|CH/T|CH|CJJ/T|CJJ)\s*\d{2,5}(?:\.\d+)?(?:-\d{4})?"
    r"|\d{2}[GJ]\d{3}(?:[～-]\d+)?"
)


def std_codes(text):
    """从 `出处` 里把标准号捞出来。只捞写了的，不替谁补一条。"""
    return sorted({m.group(0).replace("  ", " ").strip()
                   for m in STD_RE.finditer(text or "")})


def collect_standards():
    """规范依据：`规范/标准绑定.json` 是唯一真源，这里只摊平、不改判词。"""
    doc = jload("规范/标准绑定.json", {}) or {}
    src = doc.get("正本") or []
    clauses = []
    for r in doc.get("条款") or []:
        clauses.append({
            "id": r.get("id") or "",
            "section": r.get("章节") or "",
            "page": r.get("pdf页"),
            "printed": r.get("印刷页") or "",
            "verified": bool(r.get("已核")),
            "check": r.get("核验词") or "",
            "content": r.get("内容") or "",
            "limits": r.get("限值"),
            "apply": r.get("套用") or "",
            "why": r.get("理由") or "",
        })
    return {
        "source": src,
        "n": len(clauses),
        "verified": sum(1 for c in clauses if c["verified"]),
        "applied": sum(1 for c in clauses if str(c["apply"]).startswith("套用")),
        "clauses": clauses,
        "unverified": doc.get("未核_方向引用") or [],
    }


def collect_gates():
    idx = jload("gates/_out/_page_index.json", {}) or {}
    rows = {g["id"]: g for g in idx.get("gates", [])}
    out = []
    for gid, stage in GATE_STAGE.items():
        g = rows.get(gid, {})
        res = jload("gates/_out/" + g["file"], {}) if g.get("file") else {}
        items = res.get("items") or []
        fail = sum(1 for x in items if x.get("status") == "fail")
        skip = sum(1 for x in items if x.get("status") == "unmeasured")
        if not items and res.get("rc") == 4:
            state = "unmeasured"
        elif res.get("pass") is False or fail:
            state = "bad"
        elif res:
            state = "ok"
        else:
            state = "none"
        out.append({
            "id": gid, "stage": stage,
            "title": g.get("title") or gid,
            "state": state,
            "n": len(items), "fail": fail, "skip": skip,
            "when": res.get("measured_at") or g.get("mtime") or "",
        })
    return out


def collect_all_gates():
    """全部闸的读数（验证那一段用）：按状态排，红的在前。"""
    idx = jload("gates/_out/_page_index.json", {}) or {}
    out = []
    for g in idx.get("gates", []):
        res = jload("gates/_out/" + g["file"], {}) if g.get("file") else {}
        items = res.get("items") or []
        fail = sum(1 for x in items if x.get("status") == "fail")
        skip = sum(1 for x in items if x.get("status") == "unmeasured")
        if not g.get("file"):
            state = "none"
        elif not items and res.get("rc") == 4:
            state = "unmeasured"
        elif res.get("pass") is False or fail:
            state = "bad"
        elif res:
            state = "ok"
        else:
            state = "none"
        out.append({"id": g["id"], "title": g.get("title") or g["id"],
                    "tier": g.get("tier") or "other", "state": state,
                    "n": len(items), "fail": fail, "skip": skip})
    order = {"bad": 0, "unmeasured": 1, "none": 2, "ok": 3}
    out.sort(key=lambda r: (order.get(r["state"], 9), r["id"]))
    return out


def collect_floors():
    """每层一页：层名 / 标高 / 识别读数 / 重画图 / 审图 / DXF，全部现读。"""
    contours = jload("rebuild/06_su/contours/index.json", []) or []
    out = []
    for c in contours:
        f = c.get("floor") or ""
        if not f:
            continue

        def has(rel):
            return os.path.isfile(os.path.join(ROOT, rel))

        rec = jload("rebuild/02_recognize/%s.json" % f, {}) or {}
        red = "rebuild/03_redraw/%s.png" % f
        plan = "rebuild/03_redraw/%s_plan.png" % f
        rev = "rebuild/04_review/%s_审图.png" % f
        dxf = "rebuild/03_redraw/%s.dxf" % f
        out.append({
            "floor": f,
            "z0_m": c.get("z0_m"),
            "polys": c.get("polys"),
            "segments": rec.get("segments"),
            "wall_polys": rec.get("wall_polys"),
            "regions": len(rec.get("regions") or []),
            "area_wall_m2": rec.get("area_wall_m2"),
            "area_open_m2": rec.get("area_open_m2"),
            "thick_mm": rec.get("thick_mm"),
            "treads_dropped": rec.get("treads_dropped"),
            "img": relurl(red) if has(red) else "",
            "plan": relurl(plan) if has(plan) else "",
            "review": relurl(rev) if has(rev) else "",
            "dxf": relurl(dxf) if has(dxf) else "",
        })
    out.sort(key=lambda r: floor_key(r["floor"]))
    return out


# ==== 五段：识别 / 判断 / 成图 / 验证 / 修订 ====
# 左列是旧的 8 段编号（数据契约不变），右列是人在页面上看到的五段。
# 合并只在**展示层**做：磁盘上的 8 段目录、判据 id、参数归属一个字都不动。
PHASE_OF = {
    "raw": "identify", "recognize": "identify",
    "redraw": "judge",
    "build": "model", "out": "model", "pack": "model",
    "verify": "verify",
    "review": "revise",
}
PHASES = [
    ("identify", "识别"),
    ("judge", "判断"),
    ("model", "成图"),
    ("verify", "验证"),
    ("revise", "修订"),
]


def ph(sid):
    """旧 8 段 id → 五段 id。未知 id 原样返回（不猜）。"""
    return PHASE_OF.get(sid, sid)


def merge_phases(parts):
    """把 8 段明细按 PHASE_OF 合成 5 段。数字全部照抄明细，不另算。"""
    out = []
    for i, (pid, pname) in enumerate(PHASES, 1):
        grp = [p for p in parts if ph(p["id"]) == pid]
        if not grp:
            continue
        out.append({
            "id": pid, "n": i, "name": pname,
            "sub": " → ".join(p["name"] for p in grp),
            "visual": next((p["visual"] for p in grp if p["visual"]), None),
            "visual_caption": next((p["visual_caption"] for p in grp
                                    if p.get("visual_caption")), ""),
            "one": grp[0]["one"],
            "did": [x for p in grp for x in p["did"]][:6],
            "impact": [x for p in grp for x in p["impact"]][:4],
            "stats": [x for p in grp for x in p["stats"]][:6],
            "files": [x for p in grp for x in p["files"]][:12],
            "gates": [],
            "ledger": next((p.get("ledger") for p in grp if p.get("ledger")), None),
            "parts": [{"id": p["id"], "name": p["name"], "sub": p["sub"]}
                      for p in grp],
        })
    return out


def stage_defs(d):
    """五段的说明文字。**数字全部来自 `d`**（现读的件），文字里只放名词。"""
    raw = d["raw"]
    rec = d["recognize"]
    red = d["redraw"]
    rev = d["review"]
    b = d["build"]
    su = d["su"]
    pk = d["pack"]

    return merge_phases([
        {
            "id": "raw", "n": 1, "name": "原图", "sub": "%d 层 CAD 图" % raw["n"],
            "visual": None, "visual_caption": "",
            "one": "设计院给的每层平面图，只读不改。",
            "did": ["每层一张 DXF，墙、柱、门、窗、楼梯都在上面",
                    "图纸是矢量线，不是照片",
                    "这一步不动手，只把件收齐"],
            "impact": ["图上没有的东西，后面也长不出来",
                       "图画错一笔，后面七个环节跟着错"],
            "stats": [["楼层", str(raw["n"])], ["图纸总量", mb(raw["bytes"])],
                      ["最大一层", raw["biggest"]]],
            "files": raw["files"][:12],
            "gates": [],
        },
        {
            "id": "recognize", "n": 2, "name": "识别", "sub": "把线认成构件",
            "visual": relurl("rebuild/03_redraw/1层.png"),
            "visual_caption": "1 层：灰线是原图线稿，粉红是判出来的墙（红=判成墙，灰=CAD 原线）",
            "one": "把图上的线按形状认成墙、柱、门、楼梯。",
            "did": ["两条线夹出的带 = 墙；小方块 = 柱",
                    "弧加一条线 = 门；成排短线 = 踏步",
                    "认完把结果写成结构化数据"],
            "impact": ["认错一处，模型里就多一堵墙或少一堵墙",
                       "墙厚和门洞位置在这一步定下来"],
            "stats": [["线段", "{:,}".format(rec["segments"])],
                      ["墙块", str(rec["wall_polys"])],
                      ["房间", str(rec["regions"])],
                      ["墙面积", "%.0f m²" % rec["area_wall_m2"]]],
            "files": [],
            "gates": [],
        },
        {
            "id": "redraw", "n": 3, "name": "重画", "sub": "画回 CAD 给人改",
            "visual": relurl("rebuild/04_review/全部12层_总览.png"),
            "visual_caption": "12 层重画总览：红=墙 蓝=柱 黄=门 细黑=踏步线",
            "one": "把认出来的构件画成一整套能改的 CAD 图。",
            "did": ["墙、柱、门、梯分图层重画",
                    "每层一份可编辑 DXF，人能在 CAD 里直接改",
                    "改这一层，模型就跟着变"],
            "impact": ["这是模型真正的底稿",
                       "在 CAD 里改一笔，三维里就少一块或多一块"],
            "stats": [["重画 DXF", str(red["n_dxf"])],
                      ["对照图", str(red["n_png"])],
                      ["墙面积合计", "%.0f m²" % rec["area_wall_m2"]]],
            "files": [],
            "gates": [],
        },
        {
            "id": "review", "n": 4, "name": "审图", "sub": "人眼过一遍",
            "visual": relurl("rebuild/04_review/地下1层_审图.png"),
            "visual_caption": "地下 1 层审图：重画结果叠在原图上，逐层列可疑处",
            "one": "把重画的和原图叠起来看，标出对不上的地方。",
            "did": ["逐层列出墙面积、墙块、门数、剔除的踏步线",
                    "可疑处标出坐标和它离墙多远",
                    "可疑处要人回 CAD 确认，不是自动修"],
            "impact": ["审出来的问题不修，后面会被当成真的建进去",
                       "整条链里只有这一步靠人眼"],
            "stats": [["审图页", str(rev["n_png"])],
                      ["审图行", str(rev["rows"])],
                      ["可疑处", str(rev["suspicious"])]],
            "files": [],
            "gates": [],
        },
        {
            "id": "build", "n": 5, "name": "建模", "sub": "平面拉成三维",
            "visual": relurl("rebuild/05_build/c006_iso.png"),
            "visual_caption": "白模轴测：墙、柱、楼板、楼梯、女儿墙逐层分件",
            "one": "按层高把平面一层层拉起来，门洞真的打穿。",
            "did": ["每层 %.1f m，%d 层平面逐层叠起来" % (b["storey_m"], d["su"]["floors"]),
                    "墙、柱、板、梯、女儿墙各自成块，共 %d 个节点" % b["n_nodes"],
                    "门洞在墙上打穿，门头上方的墙单独补"],
            "impact": ["层次和总高在这一步定死",
                       "门窗洞口、门头墙、楼梯形制都在这里长出来"],
            "stats": [["层高", "%.1f m" % b["storey_m"]],
                      ["主体高", "%.1f m" % b["top_m"]],
                      ["最高点", "%.2f m" % b["z_max_m"]],
                      ["白模", mb(b["glb_bytes"])]],
            "files": [],
            "gates": [],
        },
        {
            "id": "out", "n": 6, "name": "出件", "sub": "SU 走一遍 → GLB",
            "visual": relurl("rebuild/05_build/c006_front.png"),
            "visual_caption": "正立面：地下层 + 上部逐层 4 m，屋面以上还有楼梯房和机房",
            "one": "把模型交给 SketchUp 走一遍，再转成最终格式。",
            "did": ["轮廓按 12 类构件分开（墙/柱/门/梯/板/门头墙…）",
                    "进 SketchUp 生成 SKP，再导出 OBJ / GLB",
                    "这一步只换容器，不改形状"],
            "impact": ["分类错了，看模型时点不中构件",
                       "轮廓少一圈，三维里就少一块"],
            "stats": [["轮廓层", str(su["floors"])],
                      ["轮廓圈", "{:,}".format(su["polys"])],
                      ["SU 件", mb(su["su_obj"])],
                      ["FC 件", mb(su["fc_glb"])]],
            "files": [],
            "gates": [],
        },
        {
            "id": "verify", "n": 7, "name": "验证", "sub": "%d 个检查" % len(d["gates_all"]),
            "visual": None, "visual_caption": "全部检查的实时读数：每条判据一行，红=有问题、黄=没测到",
            "one": "把每一段的结果拉回去和图纸对，不对就红。",
            "did": ["每条判据一个函数，逐条量、逐条判",
                    "红了会说出：哪个参数不对、真源在哪、实测多少、改哪里",
                    "故意弄坏来验检查本身（自检）也算一条判据"],
            "impact": ["验证不过，后面交付的包就不该出门",
                       "红一条 = 图上有一处对不上，不是小数点点错了"],
            "stats": [["合格", str(d["gate_ok"])],
                      ["有问题", str(d["gate_bad"])],
                      ["没测到", str(d["gate_skip"])]],
            "files": [],
            "gates": [],
            "ledger": d["gates_all"],
        },
        {
            "id": "pack", "n": 8, "name": "交付包", "sub": "%d 件，带指纹" % pk["n"],
            "visual": None, "visual_caption": "",
            "one": "模型 + 房间台账 + 分层说明 + 质检，打成一包。",
            "did": ["包里有模型、房间台账、分层说明、质检报告",
                    "每件都带 sha256 指纹",
                    "整包能单独部署，不依赖仓库"],
            "impact": ["交出去的是这一包，不是仓库里的散件",
                       "包里任何一件变了，包指纹就变"],
            "stats": [["包内件数", str(pk["n"])], ["包体积", mb(pk["bytes"])],
                      ["质检", pk["qc"]], ["包指纹", pk["sha"][:12]]],
            "files": [{"name": a.get("role", "") + " · " + a.get("path", ""),
                       "bytes": a.get("bytes", 0)} for a in pk["artifacts"][:12]],
            "gates": [],
        },
    ])


# 工作台是另一个站（它自己默认 8150）。这里只写地址，不复述它的端口/路由。
WORKBENCH = os.environ.get("CDUT_WORKBENCH") or "http://127.0.0.1:8150"

# 专项页目录：每页回答一个问题。`stage` 是它挂在第几步下（人定的归属，不是量出来的数）。
# ★ 2026-10-20 用户令：只留「首页 building.html + 合并后台（8800+8150）+ 对照/分层合页」，
#   其余页不再保留 ⇒ 目录里删掉那十条链接（墙层闭合/构件对照/门头墙/楼板/两条出件路线/
#   全部检查/判据矩阵/外部复核/实景编辑器/系统总览）。页面文件已归档后删除，
#   见 `闸账-2026-10-20.md` §四；不要在这里留死链。
#   页面路由同时从根路径改成 `/pipeline/*`（根 `/` 归工作台）。
PAGES = [
    {"href": "/pipeline/flow", "title": "流程总览", "stage": "",
     "asked": "五段各自吃哪个目录、吐哪个目录、谁在算、闸门红几条"},
    {"href": "/pipeline/floors", "title": "每层一页", "stage": "redraw",
     "asked": "每一层重画出来是什么样，多少墙、多少房间、多少墙面积"},
    {"href": "/pipeline/pages", "title": "全部页面", "stage": "",
     "asked": "后台里还有哪些页，各自回答什么问题"},
    # 跨端口：工作台与流程台已合成一个后台（8150），地址仍是绝对路径
    {"href": WORKBENCH, "title": "建模工作台（8150）", "stage": "build",
     "asked": "改一处、跑一段、看一段；桌面式的建模工作台"},
    {"href": WORKBENCH + "/quick.html", "title": "快速立体块（8150）", "stage": "build",
     "asked": "从一个平面轮廓先拉出体量块，再细建"},
    {"href": "/files/demo/index.html", "title": "模型包查看器", "stage": "out",
     "asked": "出件的包里到底有什么，能不能离线打开"},
    {"href": "/files/demo/building.html#/building/cdut-main/c006", "title": "楼栋三维 · 首页", "stage": "out",
     "asked": "整栋楼在三维里长什么样"},
    # 一页两个标签：同机位对照 / 分层显隐（2026-10-20 用户令合成）
    {"href": "/compare", "title": "白模×实景 · 对照与分层", "stage": "verify",
     "asked": "白模和实景在同一机位下对得上吗；近处换白模、远处留实景怎么拼"},
]


# 流程总览：每段吃哪几个目录、吐哪几个目录、由哪几个脚本产生。
# 只放**目录与文件名**；文件数/体积/最新时间一律现扫，不手打。
FLOW_DIRS = {
    "identify": {"in": ["rebuild/01_cad"], "out": ["rebuild/02_recognize"]},
    "judge":    {"in": ["rebuild/02_recognize"], "out": ["rebuild/03_redraw"]},
    "model":    {"in": ["rebuild/03_redraw"],
                 "out": ["rebuild/05_build", "rebuild/06_su", "packs"]},
    "verify":   {"in": ["gates/_out"], "out": ["gates/_out"]},
    "revise":   {"in": ["rebuild/04_review"], "out": ["rebuild/03_redraw"]},
}
FLOW_TOOLS = {
    "identify": ["recognize.py", "recognize_semantics.py", "recognize_voids.py"],
    "judge": ["redraw.py", "build_libraries.py"],
    "model": ["build3d.py", "export_contours.py", "contours_to_fc.py",
              "su_obj_to_glb.py"],
    "verify": ["overlay_check.py", "audit_components.py", "door_rule.py",
               "check_pack_floors.py"],
    "revise": ["review_index.py", "lintel_thickness.py", "defect_scan.py"],
}


def dir_stat(rel):
    """现扫一个目录：文件数、字节、最新一件的时间。不存在就如实报 0。"""
    p = os.path.join(ROOT, rel)
    n = 0
    b = 0
    newest = 0.0
    if os.path.isdir(p):
        for base, _dirs, files in os.walk(p):
            for f in files:
                try:
                    st = os.stat(os.path.join(base, f))
                except OSError:
                    continue
                n += 1
                b += st.st_size
                newest = max(newest, st.st_mtime)
    elif os.path.isfile(p):
        st = os.stat(p)
        n, b, newest = 1, st.st_size, st.st_mtime
    return {"path": rel, "files": n, "bytes": b,
            "newest": (datetime.datetime.fromtimestamp(newest)
                       .strftime("%Y-%m-%d %H:%M") if newest else "")}


def tool_stat(name):
    p = os.path.join(ROOT, "rebuild", "tools", name)
    if not os.path.isfile(p):
        return {"name": name, "exists": False, "newest": ""}
    return {"name": name, "exists": True,
            "newest": datetime.datetime.fromtimestamp(os.path.getmtime(p))
                      .strftime("%Y-%m-%d")}


def collect():
    contours = jload("rebuild/06_su/contours/index.json", []) or []
    floors = [c.get("floor") for c in contours if c.get("floor")]
    recognize = [jload("rebuild/02_recognize/%s.json" % f, {}) or {} for f in floors]
    build = jload("rebuild/05_build/build.json", {}) or {}
    manifest = jload("packs/cdut-main/c006/manifest.json", {}) or {}

    raw_files = sorted(files_in("rebuild/01_cad/raw", ".dxf"), key=floor_key)
    raw_sizes = [{"name": f, "bytes": size("rebuild/01_cad/raw/" + f)} for f in raw_files]
    red_dxf = files_in("rebuild/03_redraw", ".dxf")
    red_plain = [f for f in red_dxf if not f.endswith("_full.dxf")]
    red_png = files_in("rebuild/03_redraw", ".png")

    # 审图说明是一张表：行数 / 最后一格不是「—」的行 = 有可疑处
    rev_rows = rev_susp = 0
    p = os.path.join(ROOT, "rebuild/04_review/审图说明.md")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln.startswith("|") and not set(ln) <= set("|-: "):
                    cells = [c.strip() for c in ln.strip("|").split("|")]
                    if cells and cells[0] == "层":
                        continue
                    rev_rows += 1
                    if len(cells) >= 2 and cells[-1] not in ("—", "-", ""):
                        rev_susp += 1

    arts = manifest.get("artifacts") or []
    d = {
        "raw": {
            "n": len(raw_files),
            "bytes": sum(x["bytes"] for x in raw_sizes),
            "biggest": max(raw_sizes, key=lambda x: x["bytes"])["name"] if raw_sizes else "—",
            "files": raw_sizes,
        },
        "recognize": {
            "segments": sum(int(x.get("segments") or 0) for x in recognize),
            "wall_polys": sum(int(x.get("wall_polys") or 0) for x in recognize),
            "regions": sum(len(x.get("regions") or []) for x in recognize),
            "area_wall_m2": sum(float(x.get("area_wall_m2") or 0) for x in recognize),
            "floors": len([x for x in recognize if x]),
        },
        "redraw": {"n_dxf": len(red_plain), "n_png": len(red_png)},
        "review": {"n_png": len(files_in("rebuild/04_review", ".png")),
                   "rows": rev_rows, "suspicious": rev_susp},
        "build": {
            "storey_m": float(build.get("storey_m") or 0),
            "top_m": float(build.get("top_m") or 0),
            "z_max_m": float(build.get("z_max_m") or 0),
            "n_nodes": int(build.get("n_nodes") or 0),
            "glb_bytes": size("rebuild/05_build/c006_white.glb"),
        },
        "su": {
            "floors": len(contours),
            "polys": sum(int(c.get("polys") or 0) for c in contours),
            "su_obj": size("rebuild/06_su/c006_su.obj"),
            "fc_glb": size("rebuild/06_su/c006_fc.glb"),
        },
        "pack": {
            "n": len(arts),
            "bytes": sum(int(a.get("bytes") or 0) for a in arts),
            "qc": (manifest.get("qc") or {}).get("level", "—"),
            "sha": manifest.get("package_sha256", "") or "",
            "artifacts": arts,
        },
        "gates_all": collect_all_gates(),
    }
    d["gate_ok"] = sum(1 for g in d["gates_all"] if g["state"] == "ok")
    d["gate_bad"] = sum(1 for g in d["gates_all"] if g["state"] == "bad")
    d["gate_skip"] = sum(1 for g in d["gates_all"] if g["state"] == "unmeasured")

    params = collect_params()
    by_path = {p["path"]: p for p in params}

    def pval(path, default=0.0):
        p = by_path.get(path)
        try:
            return float(p["value"]) if p else default
        except (TypeError, ValueError):
            return default

    base = contours[0] if contours else {}
    model = {
        "n_above": len(build.get("floor_h_m") or []),
        "storey_m": d["build"]["storey_m"],
        "top_m": d["build"]["top_m"],
        "z_max_m": d["build"]["z_max_m"],
        "basement_m": abs(float(base.get("z0_m") or 0)),
        "door_mm": pval("构件/门/洞高"),
        "parapet_mm": pval("构件/顶部/女儿墙高"),
        "riser_mm": pval("构件/楼梯/踢面"),
        "wall_mm": pval("构件/共用/墙厚"),
        "ring_mm": pval("构件/共用/环_最短边下限"),
        "room_m2": pval("构件/共用/房间_面积下限"),
    }
    knobs = collect_knobs(params, model)

    stages = stage_defs(d)
    bind = collect_standards()
    for s in stages:
        # 验证/交付段挂的是**外部质检口径**（标准绑定里的已核条款），不是参数出处
        if s["id"] == "verify":
            s["clauses"] = [c for c in bind["clauses"] if c["verified"]]
        elif s["id"] == "model":
            s["clauses"] = [c for c in bind["clauses"]
                            if str(c["apply"]).startswith("套用")]
    gates = collect_gates()
    for g in gates:
        for s in stages:
            if s["id"] == ph(g["stage"]):
                s["gates"].append(g)
    for s in stages:
        s["params"] = [p for p in params if ph(p["stage"]) == s["id"]]
        s["knobs"] = [k for k in knobs if ph(k["stage"]) == s["id"]]
        # 本段用到的标准号：只从这些参数的 `出处` 里现捞（不手打第二份名单）
        # 只数「有几个参数引它」。**标准号本身不判新旧**：新旧是每个值的标注，
        # 一个标准号常同时被「旧规范」与「现行」两类参数引到，按号判必误伤。
        codes = {}
        for p in s["params"]:
            for c in std_codes(p.get("source") or ""):
                codes[c] = codes.get(c, 0) + 1
        s["std"] = [{"code": k, "n": v} for k, v in sorted(codes.items())]
        s["pages"] = [{"href": p["href"], "title": p["title"], "asked": p["asked"]}
                      for p in PAGES if ph(p["stage"]) == s["id"]]
        fl = FLOW_DIRS.get(s["id"], {})
        s["dirs_in"] = [dir_stat(x) for x in fl.get("in", [])]
        s["dirs_out"] = [dir_stat(x) for x in fl.get("out", [])]
        s["tools"] = [tool_stat(t) for t in FLOW_TOOLS.get(s["id"], [])]

    return {
        "schema": "cdut3d-pipeline/1",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "building": {"id": "c006", "name": "第六教学楼", "alias": "逸夫楼"},
        "stages": stages,
        "params": params,
        "model": model,
        "knobs": knobs,
        "standards": collect_standards(),
        "floors": collect_floors(),
        "pages": [{"href": p["href"], "title": p["title"], "asked": p["asked"],
                   "stage": ph(p["stage"]),
                   "stage_name": next((s["name"] for s in stages
                                       if s["id"] == ph(p["stage"])), "")}
                  for p in PAGES],
        "counts": {
            "floors": len(floors),
            "contours": d["su"]["polys"],
            "top_m": d["build"]["top_m"],
            "artifacts": d["pack"]["n"],
            "params": len(params),
            "gates": len(d["gates_all"]),
        },
    }


TRIAL_ROOT = os.path.join(HERE, "_try")
_TRIAL_LOCK = threading.Lock()

# 哪些旋钮**真的**驱动 build3d（逐个核过 PL.p 的调用点；没核到的不许假装能重跑）
TRIAL_LEVERS = {
    "构件/共用/层高": "层高（连同 `构件/层高按栋/c006` 一起覆盖）",
    "构件/顶部/女儿墙高": "女儿墙高",
    "构件/共用/环_最短边下限": "轮廓最短边",
}


def trial_run(edits):
    """按页面上的数，在沙盒里真跑一遍 build3d。**不碰真源、不写对照表**。"""
    n_floor = len((jload("rebuild/05_build/build.json", {}) or {}).get("floor_h_m") or [])
    ov, notes, skipped = {}, [], []
    for path, val in (edits or {}).items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            skipped.append({"path": path, "why": "不是数"})
            continue
        if path == "构件/共用/层高":
            ov[path] = v
            if n_floor:
                ov["构件/层高按栋/c006"] = [v] * n_floor
            notes.append("层高 %g mm（按栋表 %d 层一并改）" % (v, n_floor))
        elif path in TRIAL_LEVERS:
            ov[path] = v
            notes.append("%s %g" % (TRIAL_LEVERS[path], v))
        else:
            # ★ 这一条改了**不会**进 build3d：它属于识别/重画段，或那一段还没接上重跑
            skipped.append({"path": path, "why": "这一段还没接重跑（数只影响示意比较）"})

    key = hashlib.sha1(json.dumps(ov, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    d = os.path.join(TRIAL_ROOT, key)
    os.makedirs(d, exist_ok=True)
    cfg = os.path.join(d, "ov.json")
    bj = os.path.join(d, "build.json")

    result = {
        "key": key, "overrides": ov, "notes": notes, "skipped": skipped,
        "dir": os.path.relpath(d, ROOT).replace("\\", "/"),
        "cached": False, "rc": None, "seconds": 0.0, "build": None, "log_tail": "",
    }
    # ★ 先判缓存再写 ov.json：写在前头会把 cfg 的 mtime 顶到 build.json 之上，缓存永远打不中
    if (os.path.isfile(bj) and os.path.isfile(cfg)
            and os.path.getmtime(bj) >= os.path.getmtime(cfg)):
        result["cached"] = True
    else:
        with open(cfg, "w", encoding="utf-8", newline="\n") as f:
            json.dump(ov, f, ensure_ascii=False, indent=1)
        env = dict(os.environ, CDUT_PARAM_OVERRIDE=cfg, CDUT_OUT_DIR=d, CDUT_TRIAL="1")
        t0 = time.time()
        try:
            r = subprocess.run(
                [sys.executable, "-X", "utf8", "-I", "rebuild/tools/build3d.py"],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=900,
                encoding="utf-8", errors="replace")
            result["rc"] = r.returncode
            result["log_tail"] = (r.stdout or "")[-1200:] + (r.stderr or "")[-800:]
        except subprocess.TimeoutExpired:
            result["rc"] = -9
            result["log_tail"] = "900 秒没跑完（试算中止，真源未动）"
        result["seconds"] = round(time.time() - t0, 1)

    b = jload(os.path.relpath(bj, ROOT), {}) or {}
    if b:
        result["build"] = {
            "top_m": b.get("top_m"), "z_max_m": b.get("z_max_m"),
            "storey_m": b.get("storey_m"), "floor_h_m": b.get("floor_h_m"),
            "attach": b.get("attach"), "n_nodes": b.get("n_nodes"),
            "glb_bytes": size(os.path.relpath(
                os.path.join(d, "c006_white.glb"), ROOT)),
        }
    trial_sweep()
    return result


def trial_sweep(keep=6):
    """试算目录只留最近 N 个（每次重跑会出 ~10 MB 的 obj/glb）。"""
    if not os.path.isdir(TRIAL_ROOT):
        return
    subs = [os.path.join(TRIAL_ROOT, x) for x in os.listdir(TRIAL_ROOT)]
    subs = [p for p in subs if os.path.isdir(p)]
    subs.sort(key=os.path.getmtime, reverse=True)
    for p in subs[keep:]:
        try:
            for f in os.listdir(p):
                os.remove(os.path.join(p, f))
            os.rmdir(p)
        except OSError:
            pass


class Handler(SimpleHTTPRequestHandler):
    server_version = "cdut3d-pipeline/1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8")

    def do_GET(self):                                              # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            p = os.path.join(HERE, "index.html")
            try:
                with open(p, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "index.html 不在", "text/plain; charset=utf-8")
            return
        if path in ("/floors", "/floors/"):
            p = os.path.join(HERE, "floors.html")
            try:
                with open(p, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "floors.html 不在", "text/plain; charset=utf-8")
            return
        if path in ("/pages", "/pages/"):
            p = os.path.join(HERE, "pages.html")
            try:
                with open(p, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "pages.html 不在", "text/plain; charset=utf-8")
            return
        if path in ("/flow", "/flow/"):
            p = os.path.join(HERE, "flow.html")
            try:
                with open(p, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "flow.html 不在", "text/plain; charset=utf-8")
            return
        if path == "/api/state":
            try:
                self._json(collect())
            except Exception as e:                                 # noqa: BLE001
                import traceback
                traceback.print_exc()
                self._send(500, json.dumps({"error": "%s: %s" % (type(e).__name__, e)},
                                           ensure_ascii=False),
                           "application/json; charset=utf-8")
            return
        if path.startswith("/files/"):
            self._file(urllib.parse.unquote(path[len("/files/"):]))
            return
        if path.startswith("/demo/"):
            self._file(path.lstrip("/"))
            return
        self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):                                             # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path != "/api/try":
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:                                          # noqa: BLE001
            self._send(400, "bad json", "text/plain; charset=utf-8")
            return
        if not _TRIAL_LOCK.acquire(blocking=False):
            self._send(429, json.dumps({"error": "已有一次试算在跑"},
                                       ensure_ascii=False),
                       "application/json; charset=utf-8")
            return
        try:
            self._json(trial_run(body.get("edits") or {}))
        except Exception as e:                                     # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._send(500, json.dumps({"error": "%s: %s" % (type(e).__name__, e)},
                                       ensure_ascii=False),
                       "application/json; charset=utf-8")
        finally:
            _TRIAL_LOCK.release()

    def _file(self, rel):
        """只许读项目根以下的文件（SPA 兜底那条老坑：别让 ../ 出去）。"""
        p = os.path.realpath(os.path.join(ROOT, rel.replace("/", os.sep)))
        root = os.path.realpath(ROOT)
        if os.path.normcase(os.path.commonpath([root, p])) != os.path.normcase(root):
            self._send(403, "forbidden", "text/plain; charset=utf-8")
            return
        if not os.path.isfile(p):
            self._send(404, "no file: " + rel, "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(p)[1].lower()
        ctype = MIME.get(ext) or mimetypes.guess_type(p)[0] or "application/octet-stream"
        try:
            with open(p, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError:
            self._send(404, "read failed", "text/plain; charset=utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--bind", default="127.0.0.1")
    a = ap.parse_args()
    # 先算一遍：起服务前就把「读不到件」炸出来，别等页面白屏
    st = collect()
    print("8800 · %s · %d 段 · %d 参数 · %d 件"
          % (st["building"]["name"], len(st["stages"]),
             st["counts"]["params"], st["counts"]["artifacts"]), flush=True)
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print("http://%s:%d/" % (a.bind, a.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

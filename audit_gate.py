# -*- coding: utf-8 -*-
"""结构 × 源图纸门禁 —— 把「识别 vs CAD 图纸」从管线末端提到第一位。

## 为什么要有它（2026-09-14 实测）

全仓唯一做「识别结果 vs 源图纸」数值比对的 `_dxf_audit.py` 排在
`backend/web/console_meta.py` 的 `PIPELINE` **no=9（倒数第三）**；而 `qa_structural.py`
（no=5，排在它前面）**只查内部不变量 I1–I18，完全不碰源图纸**。
⇒ **整条管线没有任何一环，会在建模前喊出「这一层少了一半墙」。**

c006 实测（全部只读量出，非推断）：

    层   漏墙率   判别(±4m平移)      房间   实况
    F1    3.1%   对齐OK(97%覆盖)      32    结构识别干净
    F0   19.6%   真缺墙(79%覆盖)      31    局部真缺 790m 墙
    F6   69.5%   真缺墙/不一致(30%)    6    **层身份错** —— 见下

F6 是**裙楼屋面层**：轮廓 5863.0㎡ 与 F0 裙楼轮廓 IoU **0.971**（F0 独有 = 0.0㎡），
而它六间房的并集 512.6㎡ **100% 落在 F7 塔楼轮廓内**。图纸 `dxf_plan/floor6.png`
（标题「7层」）外围一圈是**屋面女儿墙**。
⇒ 那 69.5% 漏墙的**主体是女儿墙**，且 F6 会被建成一个 5863㎡ 的大平层空盒子。

## 判据一律不重写（本仓铁律：一处实现，两处必漂）

  · M 漏墙 / W 糊块 / F 错位 + 人话 `flags`
        → `qa_defect_census.defect_of(name)["rows"]`（**唯一实现**）
  · 平移错位判别（对齐OK / 平移错位 / 错位+缺墙 / 真缺墙）
        → `_dxf_audit_report.classify`（**唯一实现**）

**为什么必须三元、不能只看漏墙率**：漏墙率会**奖励胖墙** —— 把内墙整体加厚一倍，
漏墙率一定降。仓内实证：`_qa/defect_c033.json` 的 `max_miss_pct = 0.0`（全库最"干净"），
而 c033 有 D0×5 + D7×5（"该层仅 1 间房占 1011.4㎡/1222.0㎡"）。**只贴漏墙率会给 c033 判绿。**

## 本脚本只加 `qa_defect_census` 没有的四件

**① G 元 · 量具自检**（抓「没量到」，最容易被漏的一件）
   `_dxf_audit.py:368` 有 `pool = [r for r in allres if r["src_m"] >= 50]` ——
   把源墙量少的层**静默剔出排名** ⇒ 「轮廓碎片 ⇒ 审计沉默」。
   **门禁不得照抄这条**（否则又变成"用门槛滤掉待检对象"，本仓已犯三次）。
   ⇒ `src_m < MIN_SRC_M` 判 **`GATE_BLIND`（ERROR 级）**：该层门禁没量到，
   **不得据此判绿**。宁可报"没看见"，不许把没看见当没问题。

**② 层身份辨识** —— 「图纸标的层」不都是可建设的楼层：
   · **D 段房号 = 地下室**（用户 2026-09-14 定：「有的地方标注的D 就是地下室，
     不是一层，可以不建设」，如 c022 `22-D1-01`）。具名口子，不放宽判据（铁律⑱）。
   · **内容集中**（`content_span = 已盖点凸包 / 轮廓 < CONTENT_SPAN`）⇒ 本层实际内容
     远小于轮廓，多半是**屋面层/退台层**。c006 F6 实测 0.21，F0 0.79、F1 0.93。
   ★ 这两类**不按漏墙率判**，但**必须显式报出**（`SUSPECT_LAYER_KIND`）——
     静默跳过就是又一次"量程滤掉待检对象"。

**③ 分级 + 基线棘轮**：FROZEN 四栋（c103/c006/c009/c104）今天就是红的，而铁律⑥
   不许批量重建 ⇒ 门禁一上线就常红 ⇒ **被整体忽略，比没有门禁更糟**（仓内原话）。
   故与 `_qa/AUDIT_BASELINE.json` 比：baseline 没红现在红 = 真回归（ERROR 阻断）；
   baseline 已红没变好 = `KNOWN_BASELINE`（不阻断，但要带**理由字符串**）。

**④ 产物 + 退出码**：逐楼 JSON（控制台可判「完成/过期」）+ 全库卷宗 + 退出码。

## 产物归属

  · `data/buildings/<name>/<name>-audit.json`  **唯一所有者 = 本脚本**。
    放这里（不是放 `_qa/`）是因为 `control.py:_resolve_artifact` **只解析 DATA 下或
    该楼目录下的相对路径** ⇒ 放 `_qa/audit_gate/` 控制台**解析不到**，于是这个阶段
    永远显示"未完成/不过期"，门禁在控制台上等于不存在。与 `{name}-building.glb`
    同构 ⇒ `control.py` 零改动即可显示完成/过期。
  · `_qa/audit_gate/summary.json`  全库卷宗（**唯一所有者 = 本脚本**）。
写盘走 tmp + os.replace（记忆 `atomic-artifact-write`：json.dump 直写会截成 0 字节）。
**门禁只读 `data/` 的 floors，一个字节都不写 floors**
（门禁变治疗器 = 一次点击改 49 栋）。

## 用法

    python -u audit_gate.py [<name> ...]    不带参数 = 全部楼
    python -u audit_gate.py --calibrate     全库跑并打印阈值标定分布（不判退出码）
    （本仓脚本多数不用 argparse，禁止用 --help 探用法）
退出码：0 PASS / 1 ERROR / 2 用法或输入错 / 3 阈值未标定（fail-closed）/ 4 门禁自身异常
"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = r"D:\gym3d"
sys.path[:0] = [os.path.join(ROOT, "backend", "web"), os.path.join(ROOT, "backend", "vision"),
                os.path.join(ROOT, "backend"), ROOT, os.path.join(ROOT, "_scratch")]

import shapely as _sh                                              # noqa: E402
import shapely.geometry as sg                                      # noqa: E402

import _dxf_audit as A                                             # noqa: E402
import _dxf_audit_report as R                                      # noqa: E402
import qa_defect_census as QC                                      # noqa: E402

BASE = os.path.join(ROOT, "data", "buildings")
OUTDIR = os.path.join(ROOT, "_qa", "audit_gate")
BASELINE = os.path.join(ROOT, "_qa", "AUDIT_BASELINE.json")

# ---------------------------------------------------------------- 阈值
# MISS_ERR = 15.0 是**沿用仓内既有口径**，不是新数字：
#   `_dxf_audit_report.py:24 THRESH = 15.0`、`qa_defect_census.py:73 MISS_PCT = 15.0`。
#   全库 49 栋 max_miss_pct 实测分布（降序）：
#     77.8 69.5 63.0 25.3 | 20.4 | 12.1 9.9 7.6 6.6 5.6 5.3 5.2 4.4 3.9 …
#   空档 12.1→20.4（8.3pp）最宽 ⇒ 15.0 落在里面。
MISS_ERR = 15.0
# MISS_WARN = 5.0 落在 4.4→5.2 这个 0.8pp 空档里。
# ★ 必须承认的局限：5.0 以下的尾巴是**连续**的（7.6 6.6 5.6 5.3 5.2 4.4），
#   没有硬空档 ⇒ WARN 档天生会误报，所以 WARN **不阻断**，只进清单。
MISS_WARN = 5.0
# G 元：源墙采样下限。低于此值 ⇒ GATE_BLIND（沿用 `_dxf_audit.py:368` 的口径，
# 但语义**反过来**：它静默剔除，这里显式报出）。
MIN_SRC_M = 50.0
# 层身份：已盖点凸包 / 轮廓 < 此值 ⇒ 内容集中（屋面层/退台层嫌疑）。
# 实测 c006：F6=0.21（集中）、F0=0.79、F1=0.93。
# ★ 2026-09-14 判例：这个阈值是拿**旧 F6** 标定的。今天补完出屋面楼梯间后 F6 的 span
#   从 0.21 涨到 1.87（内容铺满整层轮廓），于是"内容集中"这条**再也认不出它不是标准层**，
#   它掉进正常楼层判据、被「只剩外壳(内墙0.9%)」顶成 ERROR —— 而那一层 5698㎡ 里只有
#   塔楼 1058㎡ 是楼面，其余是**屋面**，屋面没有内墙本来就是设计。
#   ⇒ 不再只靠 span 这条间接启发式，改成**直接量它是不是退台屋面层**（见 _roof_terrace）。
CONTENT_SPAN = 0.35
ROOM_COVER_MAX = 0.15
# W 元里哪些 flags 算 ERROR 级（糊成一块 = 几何不可用），哪些算 WARN 级。
W_ERR = ("只剩外壳", "内墙巨块", "过覆盖")
W_WARN = ("墙占比", "外环厚", "层错位", "越界")
# D 段房号 = 地下室。匹配 `22-D1-01` / `6-D02-03` 这种「含 D+数字段」的房号。
D_SEG = re.compile(r"(?:^|-)D\d+(?:-|$)")


# ---------------------------------------------------------------- G 元：量具自检
def _blind_reason(row):
    """源墙采样是否不足以支撑任何结论。返回 None 或人话理由。"""
    src_m = row.get("src_m")
    if src_m is None:
        return "源墙量算不出（采样失败）"
    if src_m < MIN_SRC_M:
        return ("源墙仅 %.1fm < %.0fm ⇒ 门禁没量到这一层，不得据此判绿"
                % (src_m, MIN_SRC_M))
    return None


# ---------------------------------------------------------------- ② 层身份辨识
_DOC = {}          # 一栋一次：整个 DXF 读一遍太贵，逐层重读会把门禁拖成小时级


def _get_doc(name):
    """懒加载 (doc, profile)。读不到则 (None, None) —— 由调用方报 GATE_BLIND。"""
    if name not in _DOC:
        try:
            import ezdxf
            import run_step
            p = run_step.load_profile(name)
            _DOC[name] = (ezdxf.readfile(p.dxf), p)
        except Exception as e:                                     # noqa: BLE001
            print("  ERR %s 读 DXF 失败: %s" % (name, str(e)[:70]))
            _DOC[name] = (None, None)
    return _DOC[name]


def _content_span(doc, p, F, fl, box, maxp=350):
    """已盖点凸包面积 / 轮廓面积（同一把尺子：`A.WALL_DIST`）。

    已盖点 = 距识别墙/梯井覆盖区 ≤ WALL_DIST 的源墙采样点。
    返回 (span, n_cov, n_src)；几何不足时 span=None。
    """
    if doc is None or p is None:
        return None, 0, 0
    try:
        src = A._source_wall_points(doc, p, F, box)
    except Exception:                                              # noqa: BLE001
        return None, 0, 0
    if not src:
        return None, 0, 0
    cov = A._walls_geom(fl)
    if cov is None or cov.is_empty:
        return None, 0, len(src)
    pts = src[::max(1, len(src) // maxp)]
    prep = _sh.prepared.prep(cov.buffer(A.WALL_DIST))
    covp = [(x, y) for (x, y) in pts if prep.covers(sg.Point(x, y))]
    if len(covp) < 3:
        return None, len(covp), len(pts)
    try:
        hull = float(sg.MultiPoint(covp).convex_hull.area)
    except Exception:                                              # noqa: BLE001
        return None, len(covp), len(pts)
    ol = fl.get("outline") or []
    if len(ol) < 3:
        return None, len(covp), len(pts)
    try:
        g = sg.Polygon([(float(q[0]), float(q[1])) for q in ol])
        if not g.is_valid:
            g = g.buffer(0)
        oa = float(g.area)
    except Exception:                                              # noqa: BLE001
        return None, len(covp), len(pts)
    if oa <= 0:
        return None, len(covp), len(pts)
    return hull / oa, len(covp), len(pts)


def _layer_kind(fl, span, row=None):
    """这一层的**身份**：normal / basement(D段) / contained(内容集中) / roof_terrace(退台屋面层)。"""
    nums = [str(r.get("number") or "") for r in (fl.get("rooms") or [])]
    if nums and all(D_SEG.search(n) for n in nums):
        return "basement"
    if span is not None and span < CONTENT_SPAN:
        return "contained"
    if _roof_terrace(fl, row):
        return "roof_terrace"
    return "normal"


def _roof_terrace(fl, row=None):
    """退台屋面层：**有女儿墙** 且 **房间只覆盖轮廓的一小块**。

    为什么这两条一起用（c006 F6 实测，2026-09-14）：
      · 女儿墙（`type=="parapet"`）只在**屋面外缘**出现 —— 全库标准层没有；
      · 房/廓 = 513/5701 = **9.0%**（本层只有塔楼那部分是真楼面，其余是裙楼屋面）；
        而同栋标准层是 50~77%。两者一起用，把"顶层平屋面"（房间照样铺满）挡在外面。
    这一层不该按"漏墙率/内墙占比"判 —— 屋面没有内墙是**设计**，不是缺陷。
    """
    if not any(w.get("type") == "parapet" for w in (fl.get("walls") or [])):
        return False
    ol = fl.get("outline") or []
    if len(ol) < 3:
        return False
    try:
        oa = sg.Polygon([(float(p[0]), float(p[1])) for p in ol]).buffer(0).area
    except Exception:                                          # noqa: BLE001
        return False
    if oa <= 200:
        return False
    ra = 0.0
    for r in fl.get("rooms") or []:
        p = r.get("poly") or []
        if len(p) >= 3:
            try:
                ra += sg.Polygon([(float(q[0]), float(q[1])) for q in p]).buffer(0).area
            except Exception:                                  # noqa: BLE001
                pass
    cover = ra / oa
    if row is not None:
        row["_room_cover"] = cover        # 只为人话说明里印出来，不参与判据
    return cover < ROOM_COVER_MAX


# ---------------------------------------------------------------- ③ 分级
def _grade(row, kind, blind):
    """返回 (级别, 判据码, 人话说明)。级别 ∈ OK/WARN/INFO/ERROR。"""
    if blind:
        return "ERROR", "GATE_BLIND", blind
    if kind == "basement":
        return "OK", "BASEMENT_D", "D 段房号 = 地下室，用户定「可以不建设」，不入判据"
    if kind == "contained":
        return "WARN", "SUSPECT_LAYER_KIND", (
            "本层内容只集中在轮廓的一小块（已盖凸包占轮廓 %.2f < %.2f）——"
            "多半是**屋面层/退台层**，不是标准楼层；不按漏墙率判，但需人眼核"
            % (row.get("_span") or 0, CONTENT_SPAN))
    if kind == "roof_terrace":
        # ★ 2026-09-14：退台屋面层 —— 本层轮廓里只有一部分是真楼面，其余是**屋面**。
        #   「内墙占比低」「只剩外壳」在这类层上是**设计**（屋面本来没有内墙），
        #   所以不按 W/M 元判；仍把漏墙率印出来供人眼核（屋面构造线常被量具当墙）。
        return "WARN", "ROOF_TERRACE", (
            "退台屋面层（有女儿墙、房间只覆盖轮廓 %.0f%%）—— 本层大部分是屋面，"
            "内墙少是设计，不按糊块/外壳判；漏墙率 %.1f%% 仅供参考"
            % ((row.get("_room_cover") or 0) * 100, row.get("miss_pct") or 0.0))
    flags = row.get("flags") or []
    for f in flags:
        if f.startswith(W_ERR):
            return "ERROR", "W_BLOB", "W 元（糊块）：%s" % f
    m = row.get("miss_pct") or 0.0
    if m >= MISS_ERR:
        return "ERROR", "MISS_HIGH", "漏墙率 %.1f%% ≥ %.0f%%" % (m, MISS_ERR)
    if m >= MISS_WARN:
        return "WARN", "MISS_WARN", "漏墙率 %.1f%% ≥ %.0f%%" % (m, MISS_WARN)
    for f in flags:
        if f.startswith(W_WARN):
            return "WARN", "W_MILD", "W/F 元：%s" % f
    return "OK", "", ""


def _base_why(ent):
    """基线条目的理由字符串。**条目可以是 dict（结构化）也可以是纯字符串** ——
    写基线的人两种都会用，而把 dict 直接 print 出去等于没写理由（实测踩过）。"""
    if isinstance(ent, str):
        return ent
    if isinstance(ent, dict):
        d = ent.get("diag")
        if isinstance(d, list):
            return " ".join(str(x).strip() for x in d)
        for k in ("why", "note", "reason"):
            if ent.get(k):
                return str(ent[k])
    return str(ent)


def _apply_baseline(recs, base, tol=0.5):
    """基线棘轮：已红的层不再重复阻断，但必须带理由；**变差要重新报红**。

    三条口径（都是实测踩出来的）：

    ① 只豁免 **ERROR**（2026-09-14 收紧）。原写法连 WARN 一起降级成 INFO，
       于是"顺手记一笔 WARN 进基线"以后，该层的 WARN **再也不会出现在任何清单里**
       —— 这不是记账，是**把告警埋掉**（WARN 本来就不阻断，没有豁免的必要）。
       WARN 现在原样留着，只在记录上标一句"基线时它就在"。

    ② **棘轮必须双向**：baseline 只豁免"没变好"，不许豁免"变更差"。
       条目里若写了 `miss_pct`，而本层现在高出 `tol` 个百分点以上 ⇒ 判 `REGRESSED`
       并**保持 ERROR**（附上基线值做对比）。不这么写，基线就成了免罪符 ——
       一旦入册，这层再烂也不会响。这也是给用户的承诺："基线条目修完必须删除"。

    ③ 理由字符串要能直接读（dict 条目取 `diag` 拼起来，不是 print 一个 dict）。
    """
    if not base:
        return
    known = base.get("known") or {}
    for r in recs:
        if r["sev"] not in ("ERROR", "WARN"):
            continue
        key = "%s|F%d" % (r["building"], r["floor"])
        ent = known.get(key)
        if not ent:
            continue
        r["baseline_why"] = _base_why(ent)
        base_pct = ent.get("miss_pct") if isinstance(ent, dict) else None
        now = r.get("miss_pct") or 0.0
        if base_pct is not None and now > float(base_pct) + tol:
            r["baseline"] = "REGRESSED"
            r["sev_was"] = r["sev"]
            r["sev"] = "ERROR"
            r["why"] = ("★ 比基线**变差**：漏墙 %.1f%% > 基线 %.1f%% + %.1fpp "
                        "⇒ 基线不豁免变差（原判据 %s）" % (now, base_pct, tol, r["code"]))
            r["code"] = "BASELINE_REGRESSED"
            continue
        if r["sev"] == "ERROR":
            r["baseline"] = "KNOWN_BASELINE"
            r["sev_was"] = "ERROR"
            r["sev"] = "INFO"
        else:
            r["baseline"] = "KNOWN_WARN"


# ---------------------------------------------------------------- 逐栋
def gate_building(name, do_classify=True):
    d = QC.defect_of(name)
    if not d:
        return None
    fd = os.path.join(BASE, name, "floors")
    recs, err = [], None
    prev_kind = None
    for row in d["rows"]:
        F = row["F"]
        try:
            fl = json.load(open(os.path.join(fd, "floor%d.json" % F), encoding="utf-8"))
        except Exception as e:                                     # noqa: BLE001
            print("  ERR %s F%d 读楼层失败: %s" % (name, F, str(e)[:70]))
            continue
        blind = _blind_reason(row)
        # 层身份只在「可疑」时才量（凸包要重读 DXF，全库全量跑太慢）
        span = None
        if row.get("flags"):
            ol = fl.get("outline")
            if ol:
                box = (min(q[0] for q in ol), min(q[1] for q in ol),
                       max(q[0] for q in ol), max(q[1] for q in ol))
                doc, p = _get_doc(name)
                span, _nc, _ns = _content_span(doc, p, F, fl, box)
        row["_span"] = span
        kind = _layer_kind(fl, span, row)
        # ★ 2026-09-14：「层错位」的可比性前提是**相邻两层身份相同**。
        #   实测 c006：F7 的墙质心 (0.69,−2.20) 与 F8/F9/F10 **完全相同**（塔楼没歪），
        #   但拿它去比 F6 —— 裙楼**屋面**层，质心被两翼女儿墙拉到 (−0.42,6.31) ——
        #   必然差 8.58 m，于是报"层错位 8.6m"。那是拿两种身份的层在比，不是缺陷。
        #   ⇒ 身份不同即不判错位，并把原因**记下来**（不许静默丢 flag）。
        if kind != "normal" or prev_kind not in (None, "normal"):
            if any(str(f).startswith("层错位") for f in (row.get("flags") or [])):
                row["flags"] = [f for f in row["flags"] if not str(f).startswith("层错位")]
                row["_shift_skipped"] = ("相邻层身份不同（本层 %s / 下层 %s）⇒ 质心不具可比性"
                                         % (kind, prev_kind))
        prev_kind = kind
        sev, code, why = _grade(row, kind, blind)

        cls, off = "", ""
        if do_classify and (row.get("miss_pct") or 0) >= MISS_WARN:
            try:
                dd = R.classify(name, F, row)
                cls, off = dd.get("cls", ""), dd.get("off", "")
                if cls == "平移错位" and sev == "ERROR":
                    # 墙都在、只是整体错位 ⇒ 修法是改 offset，不是按图重建模。
                    # 方向完全不同，必须与「真缺墙」分开（混一类=给方向错的诊断）。
                    code, why = "SUSPECT_OFFSET", (
                        "平移后覆盖回升 %s ⇒ 疑似 offset/坐标系错位，**不是识别漏墙**；"
                        "修法是改 profile.offset 重跑，不是按图重建" % off)
            except Exception as e:                                 # noqa: BLE001
                cls = "ERR %s" % str(e)[:50]

        recs.append(dict(building=name, floor=F, sev=sev, code=code, why=why,
                         layer_kind=kind, cls=cls, off=off,
                         miss_pct=row.get("miss_pct"), miss_m=row.get("miss_m"),
                         src_m=row.get("src_m"), n_walls=row.get("n_walls"),
                         rooms=len(fl.get("rooms") or []),
                         inner_share=row.get("inner_share"),
                         content_span=None if span is None else round(span, 3),
                         flags=row.get("flags") or []))
    return dict(building=name, records=recs)


def _atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _load_baseline():
    if not os.path.exists(BASELINE):
        return None
    try:
        return json.load(open(BASELINE, encoding="utf-8"))
    except Exception:                                              # noqa: BLE001
        return None


def _calibration_report(allrecs):
    """打印阈值标定用的分布 + 空档 —— 阈值只允许取在空档里。"""
    vs = sorted((r["miss_pct"] or 0.0) for r in allrecs)
    print("\n=== 漏墙率分布（%d 层，升序）===" % len(vs))
    print("  最小 %.1f  中位 %.1f  最大 %.1f" % (vs[0], vs[len(vs) // 2], vs[-1]))
    print("\n=== 相邻空档 >0.5pp 的位置（阈值取证）===")
    for i in range(1, len(vs)):
        gap = vs[i] - vs[i - 1]
        if gap > 0.5:
            print("  %.1f%% → %.1f%%   空档 %.1fpp   %s"
                  % (vs[i - 1], vs[i], gap,
                     "★ 阈值候选" if vs[i - 1] < 25 and vs[i] > 4 else ""))
    print("\n当前 MISS_WARN=%.1f MISS_ERR=%.1f CONTENT_SPAN=%.2f"
          % (MISS_WARN, MISS_ERR, CONTENT_SPAN))
    print("落档：<%.0f%% = %d 层 | %.0f~%.0f%% = %d 层 | ≥%.0f%% = %d 层"
          % (MISS_WARN, sum(1 for v in vs if v < MISS_WARN),
             MISS_WARN, MISS_ERR, sum(1 for v in vs if MISS_WARN <= v < MISS_ERR),
             MISS_ERR, sum(1 for v in vs if v >= MISS_ERR)))


def main():
    calibrate = "--calibrate" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = sorted(d for d in os.listdir(BASE)
                   if os.path.isdir(os.path.join(BASE, d, "floors")))
    if args:
        names = [n for n in names if n in args]
        if not names:
            print("没有匹配的楼：%s" % args)
            sys.exit(2)

    base = _load_baseline()
    if not base:
        print("★ 阈值未标定（缺 %s）—— 本次只出数字，**不判绿**（fail-closed）"
              % os.path.basename(BASELINE))
    os.makedirs(OUTDIR, exist_ok=True)

    allrecs, summary = [], []
    for i, name in enumerate(names, 1):
        # 标定只要 miss_pct 的**分布**，不要「平移错位 vs 真缺墙」的细分；
        # 而 `R.classify` 内部自己 `ezdxf.readfile` 一次 ⇒ 全库标定会读上百次大 DXF。
        got = gate_building(name, do_classify=not calibrate)
        if not got:
            print("[%d/%d] %-6s 跳过（读不到 floors/profile）" % (i, len(names), name))
            continue
        recs = got["records"]
        _apply_baseline(recs, base)
        allrecs += recs
        lvl = ("ERROR" if any(r["sev"] == "ERROR" for r in recs)
               else "WARN" if any(r["sev"] == "WARN" for r in recs) else "PASS")
        summary.append(dict(building=name, level=lvl, floors=len(recs),
                            n_error=sum(1 for r in recs if r["sev"] == "ERROR"),
                            n_warn=sum(1 for r in recs if r["sev"] == "WARN"),
                            n_known=sum(1 for r in recs if r.get("baseline"))))
        # 逐楼产物放楼目录（`{name}-audit.json`，与 `{name}-building.glb` 同构）
        # ⇒ control.py:243 `_resolve_artifact` 解析得到、控制台才看得见完成/过期。
        # 同时往 OUTDIR 留一份同内容副本，供只读分析（OUTDIR 的所有者仍是本脚本）。
        art = dict(schema="audit-gate/1", building=name, level=lvl,
                   thresholds=dict(MISS_WARN=MISS_WARN, MISS_ERR=MISS_ERR,
                                   MIN_SRC_M=MIN_SRC_M, CONTENT_SPAN=CONTENT_SPAN),
                   records=recs)
        bd = os.path.join(BASE, name)
        if os.path.isdir(bd):
            _atomic_json(os.path.join(bd, "%s-audit.json" % name), art)
        _atomic_json(os.path.join(OUTDIR, "%s.json" % name), art)
        print("[%d/%d] %-6s %-5s 层%2d  E%d W%d known%d"
              % (i, len(names), name, lvl, len(recs), summary[-1]["n_error"],
                 summary[-1]["n_warn"], summary[-1]["n_known"]), flush=True)

    # ★ 2026-09-14 补单栋保护：`summary.json` 是**全库卷宗**，而 `python audit_gate.py c006`
    #   原来会把整份覆盖成"1 栋 11 层"（本脚本作者自己今天就踩了一次）。
    #   与 `_dxf_compare_render.py` 的 `_dxf_compare.html`、`_dxf_cad_render.py` 的
    #   `_dxf_index.html` 同一类活缺陷：**单栋调试不许动全库总目录**。
    #   单栋自己的 `_qa/audit_gate/<name>.json` 上面已经写了，那才是控制台要看的。
    if args:
        print("\n（单栋/点名模式：**不覆盖**全库卷宗 summary.json —— 见本文件单栋保护注释）")
    else:
        _atomic_json(os.path.join(OUTDIR, "summary.json"),
                     dict(schema="audit-gate/1", calibrated=bool(base),
                          thresholds=dict(MISS_WARN=MISS_WARN, MISS_ERR=MISS_ERR,
                                          MIN_SRC_M=MIN_SRC_M, CONTENT_SPAN=CONTENT_SPAN,
                                          ROOM_COVER_MAX=ROOM_COVER_MAX),
                          buildings=summary, records=allrecs))

    bad = [r for r in allrecs if r["sev"] in ("ERROR", "WARN")]
    bad.sort(key=lambda r: -(r["miss_pct"] or 0))
    print("\n=== 结构 × 图纸：最差 20 层 ===")
    print("%-6s %-4s %-6s %-16s %8s %8s %6s %6s %s"
          % ("楼", "层", "级别", "判据码", "漏墙率", "源墙m", "内墙%", "span", "判别"))
    for r in bad[:20]:
        print("%-6s F%-3d %-6s %-16s %7s%% %8s %6s %6s %s"
              % (r["building"], r["floor"], r["sev"], r["code"],
                 r["miss_pct"], r["src_m"],
                 "-" if r["inner_share"] is None else "%.1f" % (r["inner_share"] * 100),
                 "-" if r["content_span"] is None else "%.2f" % r["content_span"],
                 r["cls"]))

    reg = [r for r in allrecs if r.get("baseline") == "REGRESSED"]
    if reg:
        print("\n★ 比基线变差 %d 层（基线**不豁免变差**，这是真回归）：" % len(reg))
        for r in reg:
            print("   %-6s F%-3d  漏墙 %s%%  ⇐ 基线 %s%%   %s"
                  % (r["building"], r["floor"], r["miss_pct"],
                     (base.get("known") or {}).get("%s|F%d" % (r["building"], r["floor"]), {}).get("miss_pct"),
                     r["baseline_why"][:90]))
    known = [r for r in allrecs if r.get("baseline") in ("KNOWN_BASELINE", "KNOWN_WARN")]
    if known:
        print("\n已基线豁免 %d 层（不阻断，但每条都要有理由；**修完必须从基线删掉**）："
              % len(known))
        for r in known[:12]:
            print("   %-6s F%-3d %-16s %s"
                  % (r["building"], r["floor"], r["code"], r["baseline_why"][:150]))
    kinds = [r for r in allrecs if r["layer_kind"] != "normal"]
    print("\n身份非普通层 %d 层（D段=地下室 / 内容集中=屋面层嫌疑）：" % len(kinds))
    for r in kinds[:20]:
        print("   %-6s F%-3d %-10s span=%s 漏墙%s%% 判据=%s"
              % (r["building"], r["floor"], r["layer_kind"],
                 "-" if r["content_span"] is None else "%.2f" % r["content_span"],
                 r["miss_pct"], r["code"]))

    if calibrate:
        _calibration_report(allrecs)

    print("\n写 _qa/audit_gate/（%d 栋 %d 层）+ summary.json" % (len(names), len(allrecs)))
    if not base:
        sys.exit(3)
    sys.exit(1 if any(r["sev"] == "ERROR" for r in allrecs) else 0)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
r"""挑空识别：从**对照件**（手建 SketchUp 导出的 OBJ）量各层楼板的大洞 → 挑空。

为什么要有这一步（2026-10-19 用户「你先做识别这个事情」；ts4 ↔ c001 比对结论）：
  源 DXF 里**没有任何图层/文字**说这一块是空的；c001 每层楼板都是整块（洞 0 处），
  手建件 ts4 却从 2 层到屋面每层都有 300~428 m² 的中庭洞（并集 502.6 m²）。
  证据只有对照件 ⇒ 本模块只做一件事：把对照件里的**大洞**量出来、配准到模型
  坐标、逐层落盘。出件那两步（`build3d` / `export_contours`）**只读这份文件**，
  不自己判挑空（铁律 018/174：同一个量不许两个估计器）。

怎么量（不新造几何判据）：
  · 水平三角面（|法向 y| / 边长 ≥ `HORIZ`）按标高分组（`TOL_MM` = 8 mm）。
  · 同组三角面 union 后取**内环**（interiors）；面积 ≥ `MIN_HOLE_M2` 的才留。
    更小的是楼梯井/管井口 —— c001 已从梯间清空区扣过，不在这里重复扣。
  · 配准：档案 `对照件.配准`（x0 / y0）。c001 实测：x_c = x_t + x0，
    y_c = y0 − z_t（对照件 Y 向上、单位 mm）。
  · 标高对接：对照件水平面 ↔ 本栋**板顶** = 层底 z0 + `SLAB_M`（容差 `ALIGN_M`）。
    取**最近**的那个标高，不取洞最大的：实测对照件每层还有**吊顶面**（比结构板
    低 0.32~0.72 m，洞反而更大：2 层吊顶 329 m²、3 层吊顶 358 m²），取最大会
    把吊顶的洞当成楼板洞。
  · 屋面对接 `TOP_M`（屋面板块顶），**单独一项**：ts4 屋面洞 327.1 m² 比 5 层洞
    428.5 m² 小，不能拿 5 层的洞当屋面洞。
  · **只做 2 层及以上**：1 层（z0 = 0）对照件面上有个 24 m² 小洞，疑似楼梯口/
    下沉区，不是中庭；地下层同理。这两层如实印出来但不扣（`跳过` 清单）。

★ 盲区（铁律 158）：
    · 本模块**只认水平面**。阳台栏板、雨篷斜板、外立面窗都不在它的判据里——
      那些只能由 DSM/倾斜摄影给（用户 2026-10-19「通过图片或者倾斜摄影来解决
      外立面的问题」）。
    · 对照件是**手构件**，本身可能错。这里只把它当"证据"落地，不当唯一真值：
      文件里写 obj 的 sha256 与字节数，**件换了必须重跑**（sha 不符直接 rc=4）。
    · 对照件里没有对应标高的层 ⇒ `未对应` 如实列出，不猜、不补。

输出：rebuild/<栋>/02_recognize/挑空.json（字节层写盘，铁律 79）
用法：CDUT_BUILDING=c001 python -X utf8 -I rebuild/tools/recognize_voids.py
退出码：0 通过 · 2 档案无 `对照件` · 3 obj 不在 · 4 sha 不符 · 5 一层都没对上
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import building as B                                                     # noqa: E402
import build3d as B3                                                     # noqa: E402

TOL_MM = 8.0                # 同一水平面的标高散布（实测各面 < 2 mm）
HORIZ = 0.985               # |ny| / 边长 的下限（与比对脚本同口径）
MIN_HOLE_M2 = 20.0          # 只认「楼板大洞」；梯井/管井口小于它
ALIGN_M = 0.25              # 对照件标高 ↔ 本栋板顶 的对齐容差（实测差 ≤ 0.12 m）
CDUT = os.path.dirname(os.path.dirname(HERE))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _obj_path(prof):
    ref = prof.get("对照件") or {}
    p = ref.get("obj")
    if not p:
        return None, "档案 %s 没有 `对照件.obj`" % B.BID
    return (p if os.path.isabs(p) else os.path.join(CDUT, p)), None


def load_obj(path):
    verts, faces = [], []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line.startswith("v "):
                q = line.split()
                verts.append((float(q[1]), float(q[2]), float(q[3])))
            elif line.startswith("f "):
                faces.append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
    return verts, faces


def levels(verts, faces):
    """水平三角面按标高分组 → {y_mm: [Polygon...]}（并集后，带内环）。"""
    buckets = {}
    for f in faces:
        for k in range(1, len(f) - 1):
            a, b, c = verts[f[0]], verts[f[k]], verts[f[k + 1]]
            u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            w = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            cy = u[2] * w[0] - u[0] * w[2]                     # 法向的 y 分量
            ln = ((u[1] * w[2] - u[2] * w[1]) ** 2 + cy ** 2
                  + (u[0] * w[1] - u[1] * w[0]) ** 2) ** 0.5
            if ln < 1e-9 or abs(cy) / ln < HORIZ:
                continue
            key = round((a[1] + b[1] + c[1]) / 3.0 / TOL_MM) * TOL_MM
            try:
                tri = Polygon([(a[0], a[2]), (b[0], b[2]), (c[0], c[2])])
            except Exception:                                          # noqa: BLE001
                continue
            if tri.is_empty or tri.area < 1.0:
                continue
            buckets.setdefault(key, []).append(tri)
    out = {}
    for y, tris in buckets.items():
        merged = unary_union(tris)
        out[y] = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
    return out


def holes_at(geoms, x0, y0):
    """该标高上的大洞 → [{洞_m2, ring(模型坐标)}]（按面积降序）。"""
    res = []
    for g in geoms:
        for r in g.interiors:
            hp = Polygon(r)
            if hp.area / 1e6 < MIN_HOLE_M2:
                continue
            ring = [[round(float(x) + x0, 1), round(float(y0 - z), 1)]
                    for x, z in hp.exterior.coords[:-1]]
            if len(ring) >= 3:
                res.append({"洞_m2": round(hp.area / 1e6, 2), "ring": ring})
    return sorted(res, key=lambda d: -d["洞_m2"])


def targets():
    """本栋要对洞的标高 → [(键, 名, 板顶_mm, 是否扣)]；`屋面` 单独一项。"""
    out = [(nm, nm, (z + B3.SLAB_M) * 1000.0, z > 1e-6) for nm, z, _h in B3.FLOORS]
    out.append(("屋面", "屋面", B3.TOP_M * 1000.0, True))
    return out


def run():
    prof = B.profile()
    path, err = _obj_path(prof)
    if err:
        print("★ " + err); return 2
    if not os.path.exists(path):
        print("★ 对照件不在：%s（档案写的那一件，不是「本栋没有挑空」）" % path)
        return 3
    sha = _sha256(path)
    want = (prof.get("对照件") or {}).get("sha256")
    if want and want != sha:
        print("★ 对照件变了（sha256 %s… ≠ 档案 %s…）⇒ 先确认新件再更新档案，"
              "不许拿旧洞配新件" % (sha[:12], want[:12]))
        return 4
    reg = (prof.get("对照件") or {}).get("配准") or {}
    x0, y0 = float(reg.get("x0", 0.0)), float(reg.get("y0", 0.0))

    verts, faces = load_obj(path)
    lv = levels(verts, faces)
    hs = {y: holes_at(g, x0, y0) for y, g in lv.items()}
    with_h = sorted((y for y in hs if hs[y]), key=lambda y: -max(h["洞_m2"] for h in hs[y]))

    floors, used, skipped = [], set(), []
    for key, name, zmm, do in targets():
        cand = [y for y in with_h if abs(y - zmm) <= ALIGN_M * 1000.0]
        # 命中多个标高 ⇒ 取**最近**的（远的那个是吊顶面，洞更大但不是楼板）
        y = min(cand, key=lambda t: abs(t - zmm)) if cand else None
        if y is not None:
            used.add(y)
        if not do:
            if y is not None:
                skipped.append({"层": key, "对照件标高_mm": y,
                                "洞_m2": [h["洞_m2"] for h in hs[y]],
                                "原因": "1 层/地下层不扣：对照件面上的小洞是梯口/下沉，不是中庭"})
            floors.append({"层": key, "名": name, "板顶_mm": round(zmm, 1),
                           "对照件标高_mm": y, "洞": []})
            continue
        floors.append({"层": key, "名": name, "板顶_mm": round(zmm, 1),
                       "对照件标高_mm": y,
                       "差_mm": (round(y - zmm, 1) if y is not None else None),
                       "洞": (hs[y] if y is not None else [])})
    unused = [{"对照件标高_mm": y,
               "洞_m2": [h["洞_m2"] for h in hs[y]]} for y in with_h if y not in used]

    out = dict(
        栋=B.BID,
        读法=dict(
            对照件=path, sha256=sha, 字节=os.path.getsize(path),
            配准=dict(x0=x0, y0=y0, 式="x_c=x_t+x0, y_c=y0−z_t"),
            水平阈值=HORIZ, 标高分组_mm=TOL_MM, 最小洞_m2=MIN_HOLE_M2,
            对齐容差_m=ALIGN_M,
            盲区="只认水平面：阳台栏板/雨篷斜板/外立面窗一律不在识别范围；"
                 "对照件为手构件，本身可能有误，sha256 变了必须重跑",
        ),
        层=floors,
        跳过=skipped,
        未对应=unused,
    )
    p = os.path.join(B.ROOT, "02_recognize", "挑空.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8")
    with open(p, "wb") as fh:                                          # 字节层（铁律 79）
        fh.write(data)

    for f in floors:
        a = sum(h["洞_m2"] for h in f["洞"])
        print("%-4s 板顶 %7.0f mm · 对照件 %s · 洞 %d 处 %.1f m²"
              % (f["层"], f["板顶_mm"],
                 ("%7.0f mm（差 %+.0f）" % (f["对照件标高_mm"], f.get("差_mm") or 0.0))
                 if f["对照件标高_mm"] is not None else "   （无）",
                 len(f["洞"]), a))
    for s in skipped:
        print("★ 跳过：%s 对照件标高 %.0f mm 有洞 %s —— %s"
              % (s["层"], s["对照件标高_mm"], s["洞_m2"], s["原因"]))
    if unused:
        print("★ 未对应 %d 个标高（对照件有洞、本栋没标高接它；多为吊顶面）：%s%s"
              % (len(unused), [u["对照件标高_mm"] for u in unused[:6]],
                 " …" if len(unused) > 6 else ""))
    if len(used) == 0:
        print("★ 一层都没对上 ⇒ 不写「没有挑空」这种结论（对照件与档案配准/标高可能错了）")
        return 5
    print("合计 %d 层有洞 · 未对应 %d 个标高 ⇒ %s"
          % (sum(1 for f in floors if f["洞"]), len(unused), p))
    return 0


if __name__ == "__main__":
    sys.exit(run())

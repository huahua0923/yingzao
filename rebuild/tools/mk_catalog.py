# -*- coding: utf-8 -*-
r"""`contours/*.json` → **逐块清单** `c006_catalog.json`（给网页点选用）。

为什么要这一件（2026-10-14，用户原话：「**修复吧，还有一个方式就是给每各块一个名字，
我就可以快速定位和你说**」）：
  · 交付件 GLB 里每一层每一类**只合成一个 mesh**（`su_obj_to_glb.py` 按 (node, cls) 合并）⇒
    在网页上点到一面墙，只知道它是 `floor5__WALL`，**说不出是第几面墙**。
  · 而「第几块」这件事**只有 contours 里有**（`export_contours.py` 已经在每条记录上写了
    `id` = `F05-WALL-007`、`name` = `5层-墙体-007`）。本脚本把它们**原样搬**出来给浏览器，
    不在网页侧重算、也不另造一套名字（两套名字必然漂移）。
  · 网页侧用法：射线打到模型表面 → 命中点 → 换算成模型坐标 (x, y, z_mm) →
    在该层块表里按「环内 + 拉伸区间含 z」找出唯一一块 ⇒ 报它的 `name`。

坐标系（与包内件一致，**别记反**）：
  模型坐标 mm：X = 平面向右，Y = 平面进深，**Z = 竖直**（地下 1 层 −3500 → 顶上三件顶）。
  GLB（Y 朝上、glTF 惯例）：glb.x = X，glb.y = Z，glb.z = −Y。
  实测复核：GLB 包围盒平面 129.3 × 84.0（不随层高变），高度 −3.5 → **build.json 的 z_max_m**。
  ★ 2026-10-16 用户裁定「**按甲定案 · 重算整条链**」⇒ 层高回到 **4.0 m**：
    层表范围 **−3.5 → 44.0 m**（11 × 4.0），含顶上三件 ⇒ 顶 **47.0 m**（＝ `build.json::z_max_m`）。
    旧口径（2026-10-15 用户令 3.5 m）下是 41.5 m / 44.5 m —— 那两个数**已作废**，别再引用。
  ★ `frame` 里的范围**现算**（见下面的 `_zb/_zt`），且**取的是层表**（`floors[].z0_mm/h_mm`）——
    不取 `blocks[].z`（那是**层内局部标高**，跨层取 min/max 会印出一个假数，见那段注释）。

格式（`schema = cdut3d-blocks/1`）：
  floors[] : {name, node, z0_mm, h_mm, push_mm, counts{类:条数}, blocks[]}
  blocks[] : {id, name, layer, z, h, bbox:[x0,y0,x1,y1], ring:[x0,y0,x1,y1,…]}
  ★ `ring` 是**扁平数组**（不是嵌套点对）：76617 个顶点，扁平 ≈1.5 MB，嵌套要 2.5 MB。
  ★ 坐标一律 **0.1 mm** 取整（与 contours 同精度）—— 粗了「洞边贴不贴墙」就看不出来。

用法：python rebuild/tools/mk_catalog.py
"""

import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))    # `-I` 不预置脚本目录
import building as B                                              # noqa: E402
# ★ 2026-10-17：路径与件名原先写死 c006。做理化楼（c005）时必须按楼栋走
#   （`CDUT_BUILDING`/`CDUT_REBUILD_ROOT`），否则 c005 的清单会写进 c006 的件名上、
#   把 c006 那一份**静默冲掉**（铁律 017）。c006 不设环境变量时逐字同一路径。
CONT = os.path.join(B.ROOT, "06_su", "contours")
OUT = os.path.join(B.ROOT, "06_su", "%s_catalog.json" % B.BID)

# 层名 → GLB 里的节点名。这张表**必须**与 su_obj_to_glb.py 的两条正则同口径
# （楼上成 `floorK`、地下室成 `B1`）：网页是拿节点名去认层的，错一个字符就点不上。
# ★ 2026-10-17 C105：地下室名**不是**写死的「地下1层」—— c105 的标题栏叫 **D1**。
#   原来写死 ⇒ `FID.get("D1")` 落空、退回原名 ⇒ 清单里的节点叫 `D1`，而 GLB 里叫 `B1`
#   （`fc_obj_to_glb` 一律把地下室成 `B1`）⇒ 网页按节点名配不上那一层（色块/点选静默丢层）。
_bm = B.profile().get("basement")
FID = ({_bm: "B1"} if _bm else {})
for _i, _nm in enumerate(B.floor_names(), 1):
    FID[_nm] = "floor%d" % (_i - 1)


def _flat(ring):
    """[[x,y],…] → [x,y,…]，并去掉**首尾重复点**（SU 那边就是被它害得转死，见 su_step2_build.rb）。"""
    rr = list(ring)
    if len(rr) >= 2 and rr[0] == rr[-1]:
        rr.pop()
    out = []
    for pt in rr:
        out.append(round(pt[0], 1))
        out.append(round(pt[1], 1))
    return out


def main():
    idx_p = os.path.join(CONT, "index.json")
    if not os.path.exists(idx_p):
        print("缺 %s —— 先跑 rebuild/tools/export_contours.py" % idx_p)
        return 2
    idx = json.load(open(idx_p, encoding="utf-8"))
    # index.json 是**一个列表**（不是对象），每项 `{floor, z0_m, h_m, polys, per_layer, cut_in,…}`
    # —— 这里只取「逐层条数」作对账用；对账的**参照物**是它，不是本脚本自己数出来的数。
    rows = idx if isinstance(idx, list) else (idx.get("floors") or idx.get("rows") or [])
    want = {}
    for r in rows:
        nm = r.get("floor") or r.get("name")
        if nm:
            want[nm] = int(r.get("polys") or 0)

    floors, tot, tot_pts = [], 0, 0
    for fp in sorted(glob.glob(os.path.join(CONT, "*.json"))):
        nm = os.path.basename(fp)[:-5]
        if nm == "index":
            continue
        d = json.load(open(fp, encoding="utf-8"))
        push = d.get("push_mm") or {}
        blocks, counts = [], {}
        for pr in d["polys"]:
            ring = _flat(pr.get("ring") or [])
            if len(ring) < 6:                 # 少于 3 个点：退化环，export_contours 已会抛，这里只兜底
                continue
            xs, ys = ring[0::2], ring[1::2]
            lay = pr["layer"]
            counts[lay] = counts.get(lay, 0) + 1
            blocks.append({
                "id": pr["id"], "name": pr["name"], "layer": lay,
                # ★ 逐块的拉伸高度优先（2026-10-14「楼梯直接建模块替换」）：楼梯每一级的
                #   顶面标高不同，若一律填「一层的 STAIR 常数 50 mm」，网页点选时判
                #   「命中点在不在该块的 z 区间里」就会把十几级踏步全判错。其余各类
                #   不带 `h` ⇒ 一字未变。
                "z": pr["z"], "h": pr.get("h", push.get(lay, 0.0)),
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "ring": ring,
            })
        floors.append({
            "name": nm, "node": FID.get(nm, nm),
            "z0_mm": round(float(d["z0_m"]) * 1000.0, 1),
            "h_mm": round(float(d["h_m"]) * 1000.0, 1),
            "push_mm": push, "counts": counts, "blocks": blocks,
        })
        tot += len(blocks)
        tot_pts += sum(len(b["ring"]) // 2 for b in blocks)

    # ★★ 2026-10-18（用户「房屋使用的那个面和房间错开了」）：上面按**文件名**取层（`sorted(glob)`），
    #   而文件名是「10层/11层/1层…」⇒ **字典序**把 10、11 层排到了 1 层前面（c006 实测：
    #   `['10层','11层','1层',…,'9层','地下1层']`）。查看器 `nodeOfFloor(k)` 是**按下标**取
    #   `floors[k].node`，于是一层房间的全部色块被铺到十层的板面上（高 9 层、且十层塔楼平面
    #   只有 46×23 m ⇒ 色块挂在大楼外），症状正是「面和房间错开」。
    #   ⇒ `floors[]` 一律**自下而上按标高**排（不是按名字、不是按目录序），下标即层序。
    floors.sort(key=lambda fl: fl["z0_mm"])

    # ★ 2026-10-15：`frame` 里的标高**现算**（原先写死「顶 47000」—— 用户令层高 4.0→3.5 之后
    #   它就成了假数，而没有任何判据会响：铁律 103/018「手打数不能当期望值」）。
    # ★★ 2026-10-16 修这一处的**取值来源**：第一版拿 `blocks[].z` 跨层取 min/max，
    #   而 **`blocks[].z` 是「层内局部标高」**（实测取值 0.0 / 153.8 / 159.1 …，是踏步高），
    #   于是印出「地下1层 -3500 → 顶 7000」—— 与模型真实范围（-3500 → 47000）**毫无关系**。
    #   症状不是报错，是**一个看起来像结论的假数**（铁律 018）。⇒ 改成由**层表**（z0_mm/h_mm）现算：
    #   层表是 SU 真吃的那个口径，才是「模型范围」的真源。
    _zb = min((fl["z0_mm"] for fl in floors), default=0.0)
    _zt = max((fl["z0_mm"] + fl["h_mm"] for fl in floors), default=0.0)
    # ★ 顶上三件（女儿墙/楼梯房/台阶屋面板）在层表里是 **11 层的 push**，不算进 z0+h
    #   ⇒ 层表范围（-3500 → 44000）**小于**模型真实范围；两个数都印，别让读者把前者当后者。
    _push_top = 0.0
    for fl in floors:
        for cls, pz in (fl.get("push_mm") or {}).items():
            if cls in ("ROOF_STAIR", "PARAPET"):
                _push_top = max(_push_top, float(pz or 0.0))
    cat = {
        "schema": "cdut3d-blocks/1",
        "units": "mm",
        "frame": ("模型坐标：X 平面向右 / Y 平面进深 / Z 竖直（层表范围 %.0f → %.0f，"
                  "**由本表 floors[].z0_mm/h_mm 现算**）；★ 顶上三件（女儿墙/楼梯房/台阶屋面板）"
                  "是 11 层的 push，**不含**在这个范围里（含它 ⇒ 顶 %.0f；权威值见 build.json::z_max_m）。"
                  "GLB(Y 朝上) 里 glb.x=X, glb.y=Z, glb.z=-Y。" % (_zb, _zt, _zt + _push_top)),
        "source": "rebuild/06_su/contours/*.json（export_contours.py 的产物）",
        "floors": floors,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cat, f, ensure_ascii=False, separators=(",", ":"))

    # ---- 对账：清单条数必须与 contours 的读数一致（不许只报不判） ----
    bad = []
    for fl in floors:
        w = want.get(fl["name"])
        if w is not None and w != len(fl["blocks"]):
            bad.append((fl["name"], w, len(fl["blocks"])))
    print("%-8s %-7s %7s %9s  %s" % ("层", "节点", "块数", "顶点数", "逐类"))
    for fl in floors:
        print("%-8s %-7s %7d %9d  %s"
              % (fl["name"], fl["node"], len(fl["blocks"]),
                 sum(len(b["ring"]) // 2 for b in fl["blocks"]),
                 " ".join("%s:%d" % kv for kv in sorted(fl["counts"].items()))))
    print("-" * 62)
    print("合计 %d 块 / %d 顶点 ⇒ %s（%.2f MB）"
          % (tot, tot_pts, os.path.relpath(OUT, ROOT), os.path.getsize(OUT) / 1e6))
    if bad:
        print("★ 与 index.json 对不上 %d 层：%s" % (len(bad), bad))
        return 1
    print("对账：%d 层逐层条数与 index.json 一致 ⇒ PASS" % len(floors))
    return 0


if __name__ == "__main__":
    sys.exit(main())

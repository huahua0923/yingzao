# -*- coding: utf-8 -*-
"""造「模型库」：一个好件 + 三个**同形坏件**，每个坏件都声明「必须被谁按什么数抓到」。

★ 为什么要这个库（用户原话：「你不能老是自证，你自证要有依据，要有判据，要有模型库，要有标准」）：
  判据只有在对**已知坏件**报红时才算有分辨力。自己对自己的件全绿，只能说明**没炸**，
  不能说明**量得准**（铁律 137：判据名单漏掉主体则永远绿）。

★ 三条硬规矩：
  ① **期望值由程序算**（好件实测 × 变换律），不手打（铁律 103）。
  ② 好件的读数是**当场重新量的**那一份，期望值由它 + 变换律推出，坏件再被三把尺子量
     —— 期望与实测来自两次不同读数（铁律 187）。
  ③ 坏件用**字节层**写盘（铁律 79）：二进制读、二进制写，行尾原样不动，
     不经过文本模式（文本模式会把 LF 翻成 CRLF，+1 字节/行，看着像「对上了」）。

★★ 三个坏件是**故意**挑成三种「不同类型的尺子才抓得到」：
  · 放大 25.4 倍  → 包围盒尺子（三把）全抓得到；
  · 高度轴横过来  → 包围盒尺子抓得到「高度不见了」，但**要判「轴错」得靠本仓的朝向判据**；
  · 没有门头墙    → **包围盒一模一样**，三把包围盒尺子**全抓不到**，
                    只有「组数/构件计数」这条尺子抓得到。
  最后这条就是本库的意义：证明我们手里不是**一把**尺子刷三遍。

用法:
    python rebuild/模型库/make_lib.py
"""
import hashlib
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # D:/项目/cdut3d
sys.path.insert(0, HERE)

from obj_text_metrics import metrics, parse_group    # noqa: E402

GOOD = os.path.join(ROOT, "rebuild", "06_su", "c006_su.obj")
SCALE = 25.4                      # 英寸→毫米，SU 那条老坑的倍数（见 06_su/README.md §3）
TOL_REL = 1e-6


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _fmt(x: float) -> str:
    return "%.6f" % x


def transform(src: str, dst: str, kind: str) -> dict:
    """字节层重写：只按 kind 改 v 行 / 丢 LINTEL 组的 g+f 行，其余字节原样。

    返回计数（程序算，不手打）：丢了几条 g、几条 f。
    """
    n_g_drop = n_f_drop = 0
    in_lintel = False
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for raw in fi:
            if raw.startswith(b"g "):
                _lay, cls = parse_group(raw[2:].decode("utf-8", "replace").strip())
                in_lintel = (cls == "LINTEL")
                if kind == "drop_lintel" and in_lintel:
                    n_g_drop += 1
                    continue
            elif raw.startswith(b"f ") and kind == "drop_lintel" and in_lintel:
                n_f_drop += 1
                continue

            if kind in ("scale", "swap") and raw.startswith(b"v "):
                body = raw.rstrip(b"\r\n")
                end = raw[len(body):]
                p = body.split(b" ")
                x, y, z = float(p[1]), float(p[2]), float(p[3])
                if kind == "scale":
                    x, y, z = x * SCALE, y * SCALE, z * SCALE
                else:                                   # 高度轴横过来：y <-> z
                    y, z = z, y
                raw = b"v " + " ".join(_fmt(v) for v in (x, y, z)).encode("ascii") + end

            fo.write(raw)
    return {"n_g_drop": n_g_drop, "n_f_drop": n_f_drop}


def count_lintel(path: str) -> tuple:
    """数 LINTEL 组的 g 行与它名下的 f 行（供「没有门头墙」这件算期望值）。"""
    n_g = n_f = 0
    in_lintel = False
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("g "):
                _lay, cls = parse_group(line[2:].strip())
                in_lintel = (cls == "LINTEL")
                if in_lintel:
                    n_g += 1
            elif line.startswith("f ") and in_lintel:
                n_f += 1
    return n_g, n_f


def main() -> int:
    if not os.path.exists(GOOD):
        sys.stderr.write("SKIP: 找不到正式件 %s\n" % GOOD)
        return 4

    good = metrics(GOOD)
    gs = good["size"]
    counts = {"n_v": good["n_v"], "n_vt": good["n_vt"], "n_vn": good["n_vn"],
              "n_f": good["n_f"], "n_g": good["n_g"]}
    n_g_lintel, n_f_lintel = count_lintel(GOOD)
    good_sha = sha256(GOOD)

    pieces = []

    # ── 好件：指向交付件本体（不复制），把 sha256 钉住；交付件一漂就红
    pieces.append({
        "名": "好件",
        "path": os.path.relpath(GOOD, ROOT).replace("\\", "/"),
        "sha256": good_sha,
        "造法": "交付件本体，原样",
        "期望": {"size": gs, "bbox_min": good["bbox_min"], "bbox_max": good["bbox_max"], **counts},
        "必须抓到": [{"量具": "三把", "字段": "size/n_v",
                      "为什么": "三把尺子读同一份件，尺寸三分量与文本 v 数必须两两一致（相对 <1e-6）"}],
    })

    # ── 坏件 1：放大 25.4 倍
    dst = os.path.join(HERE, "坏_放大25.4倍.obj")
    transform(GOOD, dst, "scale")
    pieces.append({
        "名": "坏_放大25.4倍",
        "path": os.path.relpath(dst, ROOT).replace("\\", "/"),
        "sha256": sha256(dst),
        "造法": "每个 v 行三分量 ×25.4（SU「裸数字是英寸」那条坑）",
        "期望": {"size": [None if x is None else x * SCALE for x in gs],
                 "bbox_min": [x * SCALE for x in good["bbox_min"]],
                 "bbox_max": [x * SCALE for x in good["bbox_max"]], **counts},
        "必须抓到": [{"量具": "blender/three/文本", "字段": "size",
                      "为什么": "三把包围盒尺子都必须报出 ×25.4 的尺寸；报不出来说明尺子没在量"},
                     {"量具": "本仓 J-10.8-02", "字段": "尺寸 129.3×84.0",
                      "为什么": "本仓判据声明的是 129.3 m ⇒ 必须报红"}],
    })

    # ── 坏件 2：高度轴横过来（y<->z）
    dst = os.path.join(HERE, "坏_高度轴横过来.obj")
    transform(GOOD, dst, "swap")
    pieces.append({
        "名": "坏_高度轴横过来",
        "path": os.path.relpath(dst, ROOT).replace("\\", "/"),
        "sha256": sha256(dst),
        "造法": "每个 v 行的 y 与 z 对调（把「高度」挪到水平轴上）",
        "期望": {"size": [gs[0], gs[2], gs[1]],
                 "bbox_min": [good["bbox_min"][0], good["bbox_min"][2], good["bbox_min"][1]],
                 "bbox_max": [good["bbox_max"][0], good["bbox_max"][2], good["bbox_max"][1]], **counts},
        "必须抓到": [{"量具": "blender/three/文本", "字段": "size",
                      "为什么": "必须报出 size=…×45000×84000（高度 45000 不在第 3 分量）"},
                     {"量具": "本仓朝向判据", "字段": "高度落在哪根轴",
                      "为什么": "包围盒尺子只能说「数变了」，判「轴错」得靠朝上轴判据（06_su/README §6）"}],
    })

    # ── 坏件 3：没有门头墙
    dst = os.path.join(HERE, "坏_没有门头墙.obj")
    transform(GOOD, dst, "drop_lintel")
    pieces.append({
        "名": "坏_没有门头墙",
        "path": os.path.relpath(dst, ROOT).replace("\\", "/"),
        "sha256": sha256(dst),
        "造法": "丢掉全部 LINTEL 组的 g 行与 f 行（v/vt/vn 原样留着）",
        "期望": {"size": gs, "bbox_min": good["bbox_min"], "bbox_max": good["bbox_max"],
                 "n_v": good["n_v"], "n_vt": good["n_vt"], "n_vn": good["n_vn"],
                 "n_f": good["n_f"] - n_f_lintel, "n_g": good["n_g"] - n_g_lintel},
        "必须抓到": [{"量具": "blender/three/文本 · 包围盒", "字段": "size",
                      "为什么": "★ 三把包围盒尺子**都抓不到**（尺寸一字不变）—— 这是本条要证明的事"},
                     {"量具": "文本计数 / 本仓 J-10.9-01", "字段": "n_g / 门头墙计数",
                      "为什么": "只有计数组数（该丢 %d 组、%d 面）的那条尺子抓得到" % (n_g_lintel, n_f_lintel)}],
    })

    # ── 断言表：逐条声明「哪个量具的哪个字段应当动 / 应当不动」。
    #    ★ 这才是**反自证**的那一环：我若写「包围盒抓不到这一件」，
    #      闸就必须当场证明它**真的**没动 —— 我说错，闸就红。
    assert_map = {
        "坏_放大25.4倍": {"blender.size": "变", "three.size": "变", "文本.size": "变",
                          "blender.n_tri": "不变", "three.n_mesh": "不变", "文本.n_g": "不变"},
        "坏_高度轴横过来": {"blender.size": "变", "three.size": "变", "文本.size": "变",
                            "blender.n_tri": "不变", "three.n_mesh": "不变", "文本.n_g": "不变"},
        "坏_没有门头墙": {"blender.size": "不变", "three.size": "不变", "文本.size": "不变",
                          "blender.n_tri": "变", "three.n_mesh": "变", "文本.n_g": "变"},
    }
    for p in pieces:
        p["断言"] = assert_map.get(p["名"], {})

    manifest = {
        "生成时刻": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "好件": {"path": os.path.relpath(GOOD, ROOT).replace("\\", "/"), "sha256": good_sha},
        "容差": {"计数": "必须完全相等", "长度_mm": "相对 < %g" % TOL_REL,
                 "说明": "%.6f 格式往返最多差 5e-7 mm"},
        "件": pieces,
    }
    out = os.path.join(HERE, "件.json")
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(manifest, ensure_ascii=False, indent=1))

    print("好件: %s\n      v=%d  f=%d  g=%d  size=%s" % (GOOD, good["n_v"], good["n_f"], good["n_g"], gs))
    print("LINTEL: %d 组 / %d 面" % (n_g_lintel, n_f_lintel))
    for p in pieces[1:]:
        print("造出 %-18s sha256=%s" % (p["名"], p["sha256"][:12]))
    print("→ %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

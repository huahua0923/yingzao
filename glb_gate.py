# -*- coding: utf-8 -*-
"""GLB 阶段门禁 —— 给建模链末端（`floors/*.json` → `<name>-building.glb`）补上唯一一道判据。

## 为什么要有它（2026-09-26）

`backend/web/console_meta.py` 的 `PIPELINE` 里 `glb` 是 no=10（倒数第二），
而**全仓每一条门禁都只看 `floors/*.json`，没有一条看 GLB**：
`qa_structural.py`（I1–I18）、`_dxf_audit.py`、`audit_gate.py` …… 全部到 floors 为止。
⇒ **GLB 是一个"造出来就算完"的阶段**：它是**交付给用户的最终产物**，
却没有任何一环会在它坏掉、缺件、与 floors 不一致时喊一声。
c006 的 15 条视觉缺陷全部在"全绿"的判据下通过，根因就在这里。

本脚本是**只读门禁**：判 GLB 与它自己的两个上游（`floors/*.json`、`profile.json`/`spec.json`）
是否自洽。它**不修、不重建、不写 `data/` 一个字节**。

## 判据（6 条 + 1 条量具自检）

  G 元 · 量具自检（`_gauge_checks`）
      ① `_srgb_to_linear()` 复刻的期望色，必须等于**从真 GLB 字节里量出来的**三个字面量
         （玻璃 (48,85,122) / 框 (138,146,157) / 楼板 (214,202,183)）。
         ★ 为什么这条必须有：GLB 的 COLOR_0 存**线性**空间，而 `glb_common.C_GLASS`
         是 **sRGB**。把 sRGB 字面量直接拿去比，会在 **94 栋上全假红**。
         这三个字面量是**独立来源**（不是用本脚本的公式算的），所以它是对公式的真检查，
         不是自证（自证与待检对象同源 ⇒ 两边一起错，本仓铁律 57）。

  ① `WIN_DECL_VS_GLB`（双向，ERROR）
       期望窗数 `E = nwin_built if glb_windows else (nwin_built - nsyn_built)`
         · `E > 0` 而 GLB 里 C_GLASS 或 C_FRAME 顶点为 0 ⇒ **声明有窗，交付件里没有窗**
         · `E == 0` 而 GLB 里有玻璃/框 ⇒ **声明无窗，交付件里却有窗**
         · `E == 0` 且 GLB 里也没有 ⇒ **`NA`，不是 `PASS`**
           ★ 分母为 0 时屏幕上必须长得和"通过"不一样（本仓铁律 60）。
           c004f2 实测 `glb_windows=true` 而 `nwin=0` ⇒ 不这样的话它会**假红**。
      本判据**不需要部件名** —— GLB 是一整块无名合并网格（实测 `len(meshes)==1`），
      所以只认颜色。

      ★ 两个方向的样本史（引用产物状态 = 引用一次带时刻的测量，本仓铁律 50/99）：
        · 正向（声明有窗、GLB 无色）：**实测样本 = c006 的旧 GLB**
          （`c006-building.glb.bak-cleanup-20260926_090331`，15,569,804 B，
           sha256[:16]=`7723949bae07`，8 色、玻璃 0 顶点）。`--selftest` 的 A 用它。
        · 反向（声明无窗、GLB 有色）：**2026-09-26 09:13 之前 c006 是活的实测样本**，
          之后那份 `profile.json` 被对齐成 `glb_windows=true`（GLB 18,179,228 B，mtime 09:14:32）
          ⇒ **这个方向的实测样本已经不存在了**，现在只由 `--selftest` 的 B
          **在内存里构造**覆盖。报告里不许把它写成"实测命中"。

  ② `WIN_COUNT`（ERROR）
       `glass_verts / 8 == frame_verts / 32 == E`
       实测（95/95 逐位成立）：**一扇窗恰好 8 个玻璃顶点 + 32 个框顶点**。
       两条腿互相印证；余数不为 0 ⇒ 量具前提破了 ⇒ `GATE_BLIND`，不硬判。

  ③ `FILE_HEALTH`（GATE_BLIND，ERROR 级）
       文件缺 / **0 字节** / 解析失败 / 顶点数 0 / 无 COLOR_0。
       ★ **0 字节单独一条码 `GLB_ZERO_BYTES`**，不许混进"✓"：
         `sha256("")` 是常数，空文件与"没被碰过"在屏幕上是同一行字（本仓铁律 43）。

  ④ `LADDER_TOP`（ERROR）
       `y_max == n_built * spec.floor_h + spec.parapet_h`（容差 0.02 m）
       `n_built = |floors/floor*.json 的层号| − |profile.skip_floors|`
       ★ `skip_floors` 必须减：c103 声明 `skip_floors=[5]`，不减就会**假红**（差 4.2 m）。

  ⑤ `LADDER_SLABS`（ERROR）
       每个 `i*floor_h`（`i = 0..n_built-1`）都要有楼板色顶点。
       实测 455/455 平面、95/95 栋齐。分母逐栋打进输出。

  ⑥ `STALE`（WARN，不阻断）
       `floors/floor*.json` 里有文件比 GLB **新** ⇒ 墙/窗可能是重识别后没重建。
       逐条点出**是哪几层、新了多少**，不是只报一个数。

  ⑦ `FACADE_COLOR`（INFO）
       `spec.json` 的 `style.facade` / `style.roof` / `style.parapet` 算出的线性色
       必须出现在 GLB 里。实测 95/95 全在。**饱和判据 ⇒ 没有分辨力**（本仓铁律 23(a)），
       所以它是 INFO 不是 ERROR，但**必须打印**（它一红就说明 GLB 是用别的 spec 建的）。

## 退出码

  0 PASS | 1 ERROR | 2 用法或输入错 | 3 阈值未标定（fail-closed） | 4 门禁自身异常

## 产物归属

  · `_qa/glb_gate/<name>.json`  逐栋（**唯一所有者 = 本脚本**）
  · `_qa/glb_gate/summary.json` 全库卷宗（**单栋模式不覆盖**，同 audit_gate.py 的保护）
  · `_qa/GLB_BASELINE.json`     基线棘轮
  ★ **与 `audit_gate.py` 的一处有意偏离**：它把逐栋产物写进
    `data/buildings/<name>/<name>-audit.json`，本脚本**不写 `data/` 一个字节**
    （门禁变治疗器 = 一次点击改 95 栋）。代价要如实说：`control.py:_resolve_artifact`
    因此在楼目录里找不到本门禁的产物 ⇒ 控制台看不到它的"完成/过期"。
    想恢复那个可见性，得由**写 `data/` 的那一侧**（build 脚本或 run_step）去写，
    不是门禁自己写。

## 用法

  python -u glb_gate.py                 # 全库 95 栋
  python -u glb_gate.py c006 c001       # 点名单栋（不覆盖 summary.json）
  python -u glb_gate.py --calibrate     # 打阈值分布 + 空档 + 饱和判据清单
  python -u glb_gate.py --selftest      # 量具自证：拿真 GLB 造出会红的输入，确认真会红
"""
import os
import sys
import json
import glob
import time
import struct

ROOT = r"D:\gym3d"
sys.path[:0] = [os.path.join(ROOT, "backend", "modeling"),
                os.path.join(ROOT, "backend"), ROOT]

import numpy as np                                                  # noqa: E402
import glb_common as G                                              # noqa: E402

# ★ reconfigure 必须放在**所有 import 之后**：`build_standard_glb.py:20` 在模块级
#   也调了一次 `sys.stdout.reconfigure(...)`（不带 line_buffering），谁后调谁说了算。
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE = os.path.join(ROOT, "data", "buildings")
OUTDIR = os.path.join(ROOT, "_qa", "glb_gate")
BASELINE = os.path.join(ROOT, "_qa", "GLB_BASELINE.json")

# ---------------------------------------------------------------- 阈值
# Y_TOL = 0.02 m：一层层高 3.5~4.2 m 是它的 175~210 倍（层高变了必红），
# 而 float32 里 y 的表示误差 ≤ 1e-5 m、trimesh 顶点无重算 ⇒ 0.02 只用来容浮点。
Y_TOL = 0.02
# 一扇窗的顶点数。实测 95/95 逐位成立（玻璃恰 8、框恰 32），两条腿独立互证。
VERTS_PER_GLASS = 8
VERTS_PER_FRAME = 32
# STALE_WARN_H = 1.0 h：全库 max(floors_mtime − glb_mtime) 升序实测
#   0.00 … 0.05 0.06 0.13 | 6.89 6.89 … 7.47 7.66 7.68 7.69 7.70 38.18
# 空档 0.13 → 6.89（6.76 h）最宽，1.0 落在里面。
# ★ 必须承认的局限：6.89 那一档有 27 栋（同一批重识别后没重建 GLB），
#   是**真陈旧**不是噪声；而 0.13 以下那几栋只是同一次构建里 floors 晚写几秒。
STALE_WARN_H = 1.0
# 低于 STALE_WARN_H 但仍晚于 GLB ⇒ INFO，**必须打印**（不许静默）：
# 本仓铁律"量不到与通过必须不是同一行字"的同族 —— 晚 3 分钟也是晚，只是不阻断。
STALE_INFO_H = 0.02           # ≈72 s
# 色差容差（线性空间 0~255）。取 2：转换用同一个 round，真值应当逐位相等；
# 留 2 是给"如果哪天真换了转换公式"留一格可见的余量，而不是给浮点误差。
COL_TOL = 2
# `spec.json` 缺 floor_h / parapet_h 时不猜默认值（`build_standard_glb.load_spec`
# 里那份 fallback 是**给构建用的**，门禁借用它就会把"配置缺失"读成"符合预期"）。
PARAPET_H_FALLBACK = None     # = 不回落；缺就 GATE_BLIND

# 本脚本复刻的 sRGB→线性 公式（源：`backend/modeling/glb_common.py:779-781`，
# `export_glb` 里那段 `lin = np.where(c <= 0.04045, …)`）。
# ★ 与真 GLB 字节比过的独立字面量（见 _gauge_checks），不是自证。
_GAUGE_TRUTH = {
    "C_GLASS": (48, 85, 122),
    "C_FRAME": (138, 146, 157),
    "C_SLAB": (214, 202, 183),
}

_CT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
       5125: ("I", 4), 5126: ("f", 4)}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _srgb_to_linear(v):
    """sRGB 字节 → 线性字节。与 `glb_common.export_glb` 同一个式子。"""
    c = np.asarray(v, dtype=float) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return tuple(int(x) for x in np.round(lin * 255.0))


def _hex_to_rgb(h):
    """`#rrggbb` → [r,g,b]。与 `build_standard_glb.py:75 hex_to_rgb` 同口径
    （含缺省 `#888888`）。**不 import 那个模块**：它在模块级
    `sys.stdout.reconfigure(...)`，还会拉起 shapely/trimesh/recognizer 整条链 ——
    门禁为了一个 6 行 hex 解析去付那些代价、还把自己的 stdout 交给别人配，不划算。"""
    h = (h or "#888888").lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _key(rgb):
    return int(rgb[0]) * 65536 + int(rgb[1]) * 256 + int(rgb[2])


def _close(a, b, tol=COL_TOL):
    return all(abs(int(x) - int(y)) <= tol for x, y in zip(a, b))


# ---------------------------------------------------------------- GLB 读取
def _load_glb(path):
    """读 GLB。返回 (json, bin, version, declared_len, file_len)。
    坏文件一律抛异常，由调用方归入 GATE_BLIND —— 这里不吞错。"""
    raw = open(path, "rb").read()
    if len(raw) < 12:
        raise ValueError("文件只有 %d 字节，装不下 12 字节 GLB 头" % len(raw))
    magic, ver, declared = struct.unpack("<III", raw[:12])
    if magic != 0x46546C67:
        raise ValueError("magic=0x%08X 不是 glTF（应为 0x46546C67）" % magic)
    if ver != 2:
        raise ValueError("glTF 版本 %d（本门禁只认 2）" % ver)
    off, js, bin_ = 12, None, None
    while off + 8 <= len(raw):
        clen, ctype = struct.unpack("<II", raw[off:off + 8])
        if off + 8 + clen > len(raw):
            raise ValueError("chunk 声明 %d 字节，文件只剩 %d ⇒ 截断"
                             % (clen, len(raw) - off - 8))
        chunk = raw[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_ = chunk
        off += 8 + clen
    if js is None:
        raise ValueError("没有 JSON chunk")
    if bin_ is None:
        raise ValueError("没有 BIN chunk")
    return js, bin_, ver, declared, len(raw)


def _accessor(j, bin_, i):
    a = j["accessors"][i]
    if "sparse" in a:
        raise ValueError("accessor %d 是 sparse，本读取器不支持（宁可不读，不许读错）" % i)
    n, nc = a["count"], _NC[a["type"]]
    fmt, sz = _CT[a["componentType"]]
    bv = j["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or (nc * sz)
    if stride == nc * sz:
        arr = np.frombuffer(bin_, dtype=np.dtype("<" + fmt), count=n * nc, offset=base)
        return arr.reshape(n, nc) if nc > 1 else arr
    out = np.empty((n, nc), dtype=np.dtype("<" + fmt))
    for k in range(n):
        out[k] = np.frombuffer(bin_, dtype=np.dtype("<" + fmt), count=nc,
                               offset=base + k * stride)
    return out


# ---------------------------------------------------------------- G 元：量具自检
def _gauge_checks():
    """返回 [(是否通过, 人话)]。任何一条不过 ⇒ 门禁自己不可信，全部判据 GATE_BLIND。

    这三条比的是**独立来源的字面量**：它们是从真 GLB 的 COLOR_0 字节里读出来的，
    不是用本脚本的公式算出来的 ⇒ 它能抓住"我把公式抄错了"，
    而"用公式算一遍再和公式算的值比"抓不住（本仓铁律 57/18）。

    ★ 自证专用开关 `GLB_GATE_SELFPROOF=break-gauge`：只把**期望字面量**改坏一位，
      用来证明"量具坏了 ⇒ 真的会走 exit 4"这条**退出码路径**是接上的（不是只写了文档）。
      它只可能让门禁**更严**（fail-closed），不可能让任何东西变绿 ——
      所以它跑偏时的代价是"报错停手"，不是"假绿"。正式跑**不要设**。
    """
    truth = dict(_GAUGE_TRUTH)
    if os.environ.get("GLB_GATE_SELFPROOF") == "break-gauge":
        k0 = sorted(truth)[0]
        truth[k0] = tuple((v + 1) % 256 if i == 0 else v
                          for i, v in enumerate(truth[k0]))
        print("★ GLB_GATE_SELFPROOF=break-gauge 已生效：期望字面量 %s 被故意改坏 ⇒ 只验退出码 4"
              % k0)
    out = []
    for k in sorted(truth):
        got = _srgb_to_linear(getattr(G, k))
        out.append((got == truth[k],
                    "%s: sRGB %s → 线性 %s（真 GLB 实测 %s）%s"
                    % (k, getattr(G, k), got, truth[k],
                       "" if got == truth[k] else "  ★ 公式与真产物不符 ⇒ 全部颜色判据不可信")))
    return out


# ---------------------------------------------------------------- 事实采集（只读）
def collect(name):
    """把一栋楼的事实**全部读出来**，一个判断都不做（判断在 judge 里）。
    任何读失败都记进 facts，不抛 —— 让 judge 去决定它是哪一档。"""
    bd = os.path.join(BASE, name)
    f = {"name": name, "glb_path": os.path.join(bd, "%s-building.glb" % name)}

    # ---- profile / spec
    f["profile_ok"] = False
    f["glb_windows"] = None
    f["skip_floors"] = set()
    pp = os.path.join(bd, "profile.json")
    if os.path.exists(pp):
        try:
            prof = json.load(open(pp, encoding="utf-8"))
            f["profile_ok"] = True
            f["glb_windows"] = prof.get("glb_windows", None)
            f["skip_floors"] = set(int(v) for v in (prof.get("skip_floors") or []))
        except Exception as e:                                       # noqa: BLE001
            f["profile_err"] = "%s: %s" % (type(e).__name__, e)

    f["spec_ok"] = False
    f["floor_h"] = None
    f["parapet_h"] = None
    f["style"] = {}
    sp = os.path.join(bd, "spec.json")
    if os.path.exists(sp):
        try:
            spec = json.load(open(sp, encoding="utf-8"))
            f["spec_ok"] = True
            f["floor_h"] = spec.get("floor_h")
            f["parapet_h"] = spec.get("parapet_h")
            f["style"] = spec.get("style") or {}
        except Exception as e:                                       # noqa: BLE001
            f["spec_err"] = "%s: %s" % (type(e).__name__, e)

    # ---- floors
    # ★ 窗数**按建成的那几层**汇总（跳过 skip_floors）：
    #   c103 实测 profile 声明 skip_floors=[5]，而 floor5.json 里有 246 扇窗
    #   ⇒ 用"全部层"去比会**假红 246 扇**（实测：323+314+312+312+312 = 1573 = 玻璃/8，逐位吻合）。
    #   口径来源：`build_standard_glb.py:782` 的 `for i, floor in enumerate(floors)` +
    #   `run_step.py:step_glb` 把 SKIP_FLOORS 交给构建侧。
    fl = sorted(glob.glob(os.path.join(bd, "floors", "floor*.json")))
    skip = f.get("skip_floors") or set()
    f["n_floor_files"] = len(fl)
    f["floor_nums"] = []
    nwin = nsyn = nwin_b = nsyn_b = 0
    f["newer_floors"] = []
    gm = None
    if os.path.exists(f["glb_path"]):
        gm = os.path.getmtime(f["glb_path"])
    f["glb_mtime"] = gm
    for p in fl:
        try:
            num = int(os.path.basename(p)[5:-5])
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:                                       # noqa: BLE001
            # 不静默：读不出来的层要留痕，否则它会安静地从分母里消失
            f.setdefault("floor_read_err", []).append(
                "%s: %s: %s" % (os.path.basename(p), type(e).__name__, e))
            continue
        f["floor_nums"].append(num)
        w = d.get("windows") or []
        nwin += len(w)
        nsyn += sum(1 for x in w if x.get("synthetic"))
        if num not in skip:
            nwin_b += len(w)
            nsyn_b += sum(1 for x in w if x.get("synthetic"))
        if gm is not None:
            dm = os.path.getmtime(p) - gm
            if dm > STALE_INFO_H * 3600.0:
                f["newer_floors"].append((os.path.basename(p), dm / 3600.0, num))
    f["nwin_all"] = nwin
    f["nsyn_all"] = nsyn
    f["nwin_built"] = nwin_b
    f["nsyn_built"] = nsyn_b

    # ---- GLB
    f["glb_exists"] = os.path.exists(f["glb_path"])
    f["glb_size"] = os.path.getsize(f["glb_path"]) if f["glb_exists"] else 0
    f["parse_ok"] = False
    f["n_verts"] = 0
    f["has_color0"] = False
    f["y_min"] = f["y_max"] = None
    f["colcnt"] = {}
    f["colors"] = set()
    f["slab_hits"] = None
    if f["glb_exists"] and f["glb_size"] > 0:
        try:
            j, bin_, ver, declared, flen = _load_glb(f["glb_path"])
            f["parse_ok"] = True
            f["declared_len"] = declared
            f["file_len"] = flen
            f["n_meshes"] = len(j.get("meshes", []))
            if f["n_meshes"] > 0:
                prim = j["meshes"][0]["primitives"][0]
                pos = _accessor(j, bin_, prim["attributes"]["POSITION"])
                f["n_verts"] = int(pos.shape[0])
                f["y_min"] = float(pos[:, 1].min())
                f["y_max"] = float(pos[:, 1].max())
                if "COLOR_0" in prim["attributes"]:
                    col = _accessor(j, bin_, prim["attributes"]["COLOR_0"])
                    f["has_color0"] = True
                    cc = col.astype(np.int64)
                    key = cc[:, 0] * 65536 + cc[:, 1] * 256 + cc[:, 2]
                    uq, ct = np.unique(key, return_counts=True)
                    f["colcnt"] = {int(k): int(v) for k, v in zip(uq, ct)}
                    f["colors"] = set(f["colcnt"])
                    # ---- 楼板平面：**y 与颜色必须一起看**，所以要单独取一次带色顶点的 y
                    # （判据⑤）。放在 collect 里而不是 main 里，是为了 --selftest 能拿同一份
                    # facts 走到同一段判断代码 —— 否则自证验的是"另一条路"（本仓铁律 26）。
                    if f.get("floor_h"):
                        built = [x for x in f["floor_nums"] if x not in skip]
                        m = key == _key(_srgb_to_linear(G.C_SLAB))
                        sy = pos[m][:, 1]
                        f["slab_hits"] = [ii for ii in range(len(built))
                                          if np.any(np.abs(sy - ii * f["floor_h"]) <= Y_TOL)]
        except Exception as e:                                       # noqa: BLE001
            f["parse_err"] = "%s: %s" % (type(e).__name__, e)
    return f


# ---------------------------------------------------------------- 判据
def judge(f):
    """纯函数：拿 facts 出记录。**不碰盘** —— 所以 `--selftest` 能拿假 facts 验它。"""
    recs = []

    def add(code, sev, state, why, **extra):
        r = {"building": f.get("name"), "code": code, "sev": sev, "state": state, "why": why}
        r.update(extra)
        recs.append(r)

    blind = None
    if not f.get("glb_exists"):
        blind = "GLB 不存在：%s ⇒ 这一阶段根本没有产物" % f.get("glb_path")
    elif f.get("glb_size") == 0:
        # ★ 单独一条码：0 字节不许混进"✓"（本仓铁律 43）
        blind = ("GLB 是 **0 字节**（存在但没有内容）⇒ 不构成任何判据；"
                 "注意：0 字节与「文件没被碰过」在屏幕上是同一行字，必须分开报")
    elif not f.get("parse_ok"):
        blind = "GLB 解析失败：%s" % f.get("parse_err", "未知")
    elif f.get("n_verts", 0) == 0:
        blind = "GLB 解析成功但 POSITION 顶点数 = 0 ⇒ 没量到几何"

    # ---- ③ FILE_HEALTH / GATE_BLIND
    if blind:
        code = "GLB_ZERO_BYTES" if f.get("glb_exists") and f.get("glb_size") == 0 else "GATE_BLIND"
        add(code, "ERROR", "GATE_BLIND", blind)
        return recs

    if f.get("declared_len") is not None and f["declared_len"] != f["file_len"]:
        add("GLB_LEN_MISMATCH", "ERROR", "FAIL",
            "GLB 头声明 %d 字节，盘上是 %d ⇒ 文件内部不自洽，读数不作数"
            % (f["declared_len"], f["file_len"]),
            metric=abs(f["declared_len"] - f["file_len"]))
    else:
        add("GLB_HEADER", "OK", "PASS",
            "%d 字节，头/长度自洽，顶点 %d，网格 %d 块"
            % (f["glb_size"], f["n_verts"], f.get("n_meshes", -1)),
            size=f["glb_size"], n_verts=f["n_verts"])

    # ---- 窗数：期望值（口径来自 build_standard_glb.py:362 / su_spec_floors_fleet.py:455-468）
    gw = f.get("glb_windows")
    floor_nums = f.get("floor_nums") or []
    built = [x for x in floor_nums if x not in (f.get("skip_floors") or set())]
    n_built = len(built)
    # 每层的窗数要按"建成的那几层"求和 ⇒ 重读一遍太贵，改由 collect 给出**逐层**窗数
    nwin_built = f.get("nwin_built")
    nsyn_built = f.get("nsyn_built")
    exp = None
    exp_why = ""
    if not f.get("profile_ok") or gw is None:
        exp = None
        exp_why = "profile.json 读不到或没有 glb_windows 键 ⇒ 不知道声明口径"
    elif nwin_built is None:
        exp = None
        exp_why = "逐层窗数没采到"
    else:
        exp = nwin_built if gw else (nwin_built - nsyn_built)
        exp_why = ("glb_windows=%s ⇒ 应有 %d 扇 = 建成的 %d 层共 %d 扇%s"
                   % (gw, exp, n_built, nwin_built,
                      "" if gw else "（全是合成窗，扣掉 %d 扇）" % nsyn_built))

    if exp is None or not f.get("has_color0"):
        why = (exp_why if exp is None
               else "GLB 没有 COLOR_0 属性 ⇒ 本门禁看不见颜色，不判窗（不是通过）")
        add("WIN_DECL_VS_GLB", "ERROR", "GATE_BLIND", why)
        add("WIN_COUNT", "ERROR", "GATE_BLIND", why)
    else:
        gk = _key(_srgb_to_linear(G.C_GLASS))
        fk = _key(_srgb_to_linear(G.C_FRAME))
        gv = f["colcnt"].get(gk, 0)
        fv = f["colcnt"].get(fk, 0)
        has_g, has_f = gv > 0, fv > 0

        # ---- ① 声明 vs 颜色（双向）
        if exp > 0:
            if not has_g or not has_f:
                add("WIN_DECL_VS_GLB", "ERROR", "FAIL",
                    "声明有 %d 扇窗（%s），而 GLB 里 C_GLASS 顶点 %d、C_FRAME 顶点 %d "
                    "⇒ 窗没进交付件" % (exp, exp_why, gv, fv),
                    metric=float(exp - gv // VERTS_PER_GLASS), expected=exp)
            else:
                add("WIN_DECL_VS_GLB", "OK", "PASS",
                    "声明 %d 扇，GLB 里玻璃 %d 顶点(=%d 扇)、框 %d 顶点(=%d 扇) ⇒ 一致"
                    % (exp, gv, gv // VERTS_PER_GLASS, fv, fv // VERTS_PER_FRAME),
                    expected=exp)
        else:
            if has_g or has_f:
                add("WIN_DECL_VS_GLB", "ERROR", "FAIL",
                    "声明**不需要窗**（%s），而 GLB 里有玻璃 %d 顶点(=%d 扇)、"
                    "框 %d 顶点(=%d 扇) ⇒ 交付件与 profile 相反"
                    % (exp_why, gv, gv // VERTS_PER_GLASS, fv, fv // VERTS_PER_FRAME),
                    metric=float(gv // VERTS_PER_GLASS), expected=0)
            else:
                add("WIN_DECL_VS_GLB", "OK", "NA",
                    "应有 0 扇、实有 0 扇（%s）—— 两数相等，但**这是「无对象可判」"
                    "不是「通过」**" % exp_why)

        # ---- ② 窗数恒等式（两条腿互证）
        rg, rf = gv % VERTS_PER_GLASS, fv % VERTS_PER_FRAME
        if rg or rf:
            add("WIN_COUNT", "ERROR", "GATE_BLIND",
                "玻璃 %d 顶点 %% %d = %d、框 %d 顶点 %% %d = %d ⇒ 不整除，"
                "「一扇窗 8+32 顶点」这个前提不成立，本判据不硬判"
                % (gv, VERTS_PER_GLASS, rg, fv, VERTS_PER_FRAME, rf))
        elif exp == 0 and gv == 0 and fv == 0:
            add("WIN_COUNT", "OK", "NA",
                "应有 0 扇、实有 0 扇 ⇒ 分母为 0，本判据不适用（不是通过）")
        elif gv // VERTS_PER_GLASS == fv // VERTS_PER_FRAME == exp:
            add("WIN_COUNT", "OK", "PASS",
                "玻璃 %d/%d = %d、框 %d/%d = %d、应有 %d ⇒ 三条腿逐位相等"
                % (gv, VERTS_PER_GLASS, gv // VERTS_PER_GLASS,
                   fv, VERTS_PER_FRAME, fv // VERTS_PER_FRAME, exp),
                expected=exp)
        else:
            add("WIN_COUNT", "ERROR", "FAIL",
                "应有 %d 扇（%s），玻璃腿说 %d 扇、框腿说 %d 扇 ⇒ 交付件里的窗数对不上"
                % (exp, exp_why, gv // VERTS_PER_GLASS, fv // VERTS_PER_FRAME),
                metric=float(abs(exp - gv // VERTS_PER_GLASS)), expected=exp)

    # ---- ④ 阶梯顶
    if f.get("floor_h") is None or f.get("parapet_h") is None or not f.get("spec_ok"):
        add("LADDER_TOP", "ERROR", "GATE_BLIND",
            "spec.json 缺 floor_h / parapet_h ⇒ 不知道应有的总高（不猜默认值："
            "猜了就把「配置缺失」读成「符合预期」）")
    elif n_built == 0:
        add("LADDER_TOP", "ERROR", "GATE_BLIND",
            "floors/ 里一层都没有（或全被 skip_floors 跳掉）⇒ 算不出应有总高")
    else:
        expect = n_built * f["floor_h"] + f["parapet_h"]
        d = f["y_max"] - expect
        if abs(d) <= Y_TOL:
            add("LADDER_TOP", "OK", "PASS",
                "y_max=%.3f = %d 层 × %.2f + 女儿墙 %.2f ⇒ 逐位吻合（差 %+.4f m）"
                % (f["y_max"], n_built, f["floor_h"], f["parapet_h"], d),
                expected=expect, metric=abs(d))
        else:
            add("LADDER_TOP", "ERROR", "FAIL",
                "y_max=%.3f，应为 %d 层 × %.2f + %.2f = %.3f，差 %+.3f m "
                "（≈ %.2f 个层高）⇒ 层数或层高对不上"
                % (f["y_max"], n_built, f["floor_h"], f["parapet_h"], expect, d,
                   d / f["floor_h"]),
                expected=expect, metric=abs(d))

    # ---- ⑤ 楼板平面
    if not f.get("has_color0"):
        add("LADDER_SLABS", "ERROR", "GATE_BLIND",
            "GLB 没有 COLOR_0 ⇒ 看不见楼板色，不判（不是通过）")
    elif f.get("floor_h") is None or n_built == 0:
        add("LADDER_SLABS", "ERROR", "GATE_BLIND", "缺 floor_h 或没有建成的楼层")
    else:
        got = f.get("slab_hits")
        if got is None:
            add("LADDER_SLABS", "ERROR", "GATE_BLIND",
                "楼板平面的 y 坐标没采到（collect 里那一步没跑到）⇒ 不比")
        else:
            miss = [i for i in range(n_built) if i not in got]
            if not miss:
                add("LADDER_SLABS", "OK", "PASS",
                    "楼板色顶点在 %d/%d 个标高（i=0..%d × %.2f m）全部出现"
                    % (len(got), n_built, n_built - 1, f["floor_h"]),
                    found=len(got), denom=n_built)
            else:
                add("LADDER_SLABS", "ERROR", "FAIL",
                    "应有 %d 个楼板标高，只在 %d 个上找到楼板色顶点；缺 i=%s "
                    "（对应 y=%s m）⇒ 这几层没有楼板"
                    % (n_built, len(got), miss[:8],
                       [round(i * f["floor_h"], 2) for i in miss[:8]]),
                    found=len(got), denom=n_built, metric=float(len(miss)))

    # ---- ⑥ 陈旧
    nf = f.get("newer_floors") or []
    if not nf:
        add("STALE", "OK", "PASS", "floors/*.json 没有比 GLB 新的文件")
    else:
        worst = max(x[1] for x in nf)
        detail = "、".join("%s 新 %.2f h" % (n, d) for n, d, _ in
                          sorted(nf, key=lambda x: -x[1])[:5])
        if worst >= STALE_WARN_H:
            add("STALE", "WARN", "WARN",
                "%d 个 floors 文件比 GLB 新（最 %.2f h ≥ %.2f h）⇒ 识别重跑过而 GLB 没重建：%s"
                % (len(nf), worst, STALE_WARN_H, detail),
                metric=worst, n_newer=len(nf))
        else:
            add("STALE", "INFO", "INFO",
                "%d 个 floors 文件比 GLB 新，但都 < %.2f h（最 %.2f h）⇒ 同一次构建里的写入次序，"
                "不阻断；**列在这里是为了不静默**：%s" % (len(nf), STALE_WARN_H, worst, detail),
                metric=worst, n_newer=len(nf))

    # ---- ⑦ 立面/屋面/女儿墙色（饱和判据 ⇒ INFO）
    if f.get("has_color0") and f.get("spec_ok"):
        checks = [("facade", f["style"].get("facade")),
                  ("roof", f["style"].get("roof")),
                  ("parapet", f["style"].get("parapet") or f["style"].get("roof"))]
        missc = []
        for label, hx in checks:
            if not hx:
                continue
            k = _key(_srgb_to_linear(_hex_to_rgb(hx)))
            if k not in f["colors"]:
                missc.append("%s=%s" % (label, hx))
        if missc:
            add("FACADE_COLOR", "WARN", "WARN",
                "spec 里声明、GLB 里找不到的颜色：%s ⇒ 这一份 GLB 可能是用别的 spec 建的"
                % "、".join(missc), metric=float(len(missc)))
        else:
            add("FACADE_COLOR", "INFO", "PASS",
                "spec 声明的 facade/roof/parapet 三色都在 GLB 里（实测 95/95 栋全在 ⇒ "
                "本判据**饱和**、没有分辨力，只当回归守卫用）")
    return recs


# ---------------------------------------------------------------- 基线棘轮
def _base_why(ent):
    """基线条目的理由字符串。条目可以是 str 也可以是 dict（写基线的人两种都会用，
    把 dict 直接 print 出去等于没写理由 —— audit_gate.py 踩过，这里沿用它的写法）。"""
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
    """基线棘轮。三条口径（沿用 audit_gate.py 的实测结论）：

    ① **只豁免 ERROR**。WARN 本来就不阻断，顺手记进基线等于把告警埋掉。
    ② **棘轮双向**：基线只豁免"没变好"，不豁免"变更差"。条目里带 `metric` 的，
       现值比基线值更差超过 tol ⇒ `BASELINE_REGRESSED` 并**保持 ERROR**。
       不这么写，基线就成了免罪符（一旦入册，再烂也不会响）。
    ③ 理由字符串要能直接读。
    """
    if not base:
        return
    known = base.get("known") or {}
    for r in recs:
        if r["sev"] != "ERROR":
            continue
        key = "%s|%s" % (r["building"], r["code"])
        ent = known.get(key)
        if not ent:
            continue
        r["baseline_why"] = _base_why(ent)
        bm = ent.get("metric") if isinstance(ent, dict) else None
        now = r.get("metric")
        if bm is not None and now is not None and float(now) > float(bm) + tol:
            r["baseline"] = "REGRESSED"
            r["sev_was"] = r["sev"]
            r["sev"] = "ERROR"
            r["why"] = ("★ 比基线**变差**：%s = %s > 基线 %s + %.2f ⇒ 基线不豁免变差"
                        "（原判据 %s）" % (r.get("metric_name") or "metric", now, bm, tol, r["code"]))
            r["code"] = "BASELINE_REGRESSED"
            continue
        r["baseline"] = "KNOWN_BASELINE"
        r["sev_was"] = "ERROR"
        r["sev"] = "INFO"
        r["state"] = "KNOWN_BASELINE"


# ---------------------------------------------------------------- 产物
def _atomic_json(path, obj):
    """先写 .tmp 再 os.replace —— 原子，读者永远看不到半份 JSON。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _load_baseline():
    if not os.path.exists(BASELINE):
        return None
    try:
        return json.load(open(BASELINE, encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        return None


# ---------------------------------------------------------------- 标定报告
def _calibration_report(recs, facts):
    print("\n=== 标定：阈值取证与饱和自检 ===")
    dist = sorted(max([x[1] for x in (f_.get("newer_floors") or [])], default=0.0)
                  for f_ in facts)
    print("\n-- 陈旧（每栋 max(floors_mtime − glb_mtime)，h，升序，>0 的才显示）--")
    nz = [v for v in dist if v > 0]
    if nz:
        print("   最小 %.3f  中位 %.3f  最大 %.3f  （%d/%d 栋 >0）"
              % (nz[0], nz[len(nz) // 2], nz[-1], len(nz), len(dist)))
        print("   相邻空档 >0.5h 的位置（阈值只许取在空档里）：")
        for i in range(1, len(nz)):
            g = nz[i] - nz[i - 1]
            if g > 0.5:
                print("     %.3f → %.3f   空档 %.3f h   %s"
                      % (nz[i - 1], nz[i], g, "★ 候选" if nz[i - 1] < 2 < nz[i] else ""))
    else:
        print("   一栋都没有（全部 glb 不比 floors 旧）")
    print("   当前 STALE_WARN_H=%.2f  STALE_INFO_H=%.2f" % (STALE_WARN_H, STALE_INFO_H))

    print("\n-- 逐判据：分母 / 通过 / 是否饱和 --")
    print("   %-18s %6s %6s %6s %6s %6s  %s"
          % ("判据码", "分母", "PASS", "NA", "FAIL", "BLIND", "饱和?"))
    codes = ["GLB_HEADER", "WIN_DECL_VS_GLB", "WIN_COUNT", "LADDER_TOP",
             "LADDER_SLABS", "STALE", "FACADE_COLOR"]
    for c in codes:
        rs = [r for r in recs if r["code"] == c]
        n = len(rs)
        if n == 0:
            print("   %-18s %6d  —— 一条都没有（这条判据根本没被跑到！）" % (c, 0))
            continue
        p = sum(1 for r in rs if r["state"] == "PASS")
        na = sum(1 for r in rs if r["state"] == "NA")
        fl = sum(1 for r in rs if r["state"] == "FAIL")
        bl = sum(1 for r in rs if r["state"] == "GATE_BLIND")
        sat = ""
        if (p + na) == n:
            sat = ("★ 饱和：全 %d 个样本都通过 ⇒ **没有分辨力**，"
                   "只能当回归守卫，不能当质量证据" % n)
        print("   %-18s %6d %6d %6d %6d %6d  %s" % (c, n, p, na, fl, bl, sat))

    print("\n-- 期望窗数口径抽查 --")
    for r in recs:
        if r["code"] == "WIN_DECL_VS_GLB" and r.get("expected") == 0:
            print("   %-8s 期望 0 扇（%s）" % (r["building"], r["state"]))


# ---------------------------------------------------------------- 自证
def _selftest():
    """量具自证：**拿真 GLB 造出"应当会红"的输入，确认它真的会红**。

    全部在内存里做（改的是 facts dict），**一个字节都不写盘**。
    每条都同时断言 `sev == ERROR`（即它真的会进退出码）。
    """
    print("=== glb_gate --selftest：判据自证 ===")
    fails, total = [], [0]

    def check(tag, cond, msg):
        total[0] += 1
        print("  [%s] %s  %s" % ("✓" if cond else "✗", tag, msg))
        if not cond:
            fails.append(tag)

    # ---- G 元 量具自检
    for ok, msg in _gauge_checks():
        check("量具自检", ok, msg)

    def recs_of(f_, code):
        return [r for r in judge(f_) if r["code"] == code]

    def state_of(f_, code):
        rs = recs_of(f_, code)
        return (rs[0]["state"], rs[0]["sev"]) if rs else ("<缺>", "<缺>")

    # A 正向自证：**用 c006 的旧 GLB 备份**（8 色、零玻璃）+ 内存里把 glb_windows 改成 True
    #   ⇒ 必须报「声明有窗但 GLB 无色」。
    bak = os.path.join(BASE, "c006", "c006-building.glb.bak-cleanup-20260926_090331")
    if os.path.exists(bak):
        f_ = collect("c006")
        f_["glb_path"] = bak
        f_["glb_size"] = os.path.getsize(bak)
        j, b, v, d, l = _load_glb(bak)
        prim = j["meshes"][0]["primitives"][0]
        pos = _accessor(j, b, prim["attributes"]["POSITION"])
        col = _accessor(j, b, prim["attributes"]["COLOR_0"])
        cc = col.astype(np.int64)
        k = cc[:, 0] * 65536 + cc[:, 1] * 256 + cc[:, 2]
        uq, ct = np.unique(k, return_counts=True)
        f_["n_verts"] = int(pos.shape[0])
        f_["has_color0"] = True
        f_["colcnt"] = {int(a): int(c) for a, c in zip(uq, ct)}
        f_["colors"] = set(f_["colcnt"])
        f_["y_min"], f_["y_max"] = float(pos[:, 1].min()), float(pos[:, 1].max())
        f_["glb_windows"] = True                 # ← 只在内存里改
        st, sev = state_of(f_, "WIN_DECL_VS_GLB")
        gk = f_["colcnt"].get(_key(_srgb_to_linear(G.C_GLASS)), 0)
        check("A 声明有窗/旧GLB无色 ⇒ 必须红",
              st == "FAIL" and sev == "ERROR",
              "c006 旧 GLB（%d 色、玻璃 %d 顶点）+ 内存 glb_windows=True ⇒ state=%s sev=%s"
              % (len(f_["colors"]), gk, st, sev))
    else:
        check("A 声明有窗/旧GLB无色 ⇒ 必须红", False,
              "找不到 c006 的旧 GLB 备份（%s）⇒ **这一条没验成**，不是通过" % bak)

    # B 反向自证（**内存构造**）：现盘 c006 的 GLB（有玻璃）+ 内存里把 glb_windows 翻成 False
    #   ⇒ 必须报「声明无窗、交付件里有窗」。
    #   ★ 为什么是构造而不是实测样本：本条判据**曾经**有一个真样本（c006 的 profile 当时是
    #     False），但 2026-09-26 09:13 那份 profile 已被对齐成 True（GLB 18,179,228 B，
    #     09:14:32）⇒ 真样本**已经不存在了**。这是"引用一份产物状态=引用一次带时刻的测量"
    #     的实例（本仓铁律 50/99），所以这里如实写"构造"，不许写成"c006 实测"。
    f_ = collect("c006")
    st_r, sev_r = state_of(f_, "WIN_DECL_VS_GLB")     # 现盘真值（应当 PASS）
    f2 = dict(f_)
    f2["glb_windows"] = False
    st2, sev2 = state_of(f2, "WIN_DECL_VS_GLB")
    gv = f_.get("colcnt", {}).get(_key(_srgb_to_linear(G.C_GLASS)), 0)
    check("B 声明无窗/GLB有色 ⇒ 必须红（内存构造，非实测样本）",
          st2 == "FAIL" and sev2 == "ERROR",
          "现盘 c006（玻璃 %d 顶点、glb_windows=%s）内存改成 False ⇒ state=%s sev=%s"
          % (gv, f_["glb_windows"], st2, sev2))

    # C 阴性对照：同一份 GLB、**只把 glb_windows 翻回去** ⇒ 必须转绿。
    #   这一对（B 红 / C 绿）差的就是 glb_windows 这一个变量（本仓铁律 26）。
    check("C 阴性对照：只把 glb_windows 翻回 True ⇒ 必须转绿",
          st_r == "PASS", "state=%s sev=%s（若仍红 ⇒ B 那一行的红不是 glb_windows 造成的）"
          % (st_r, sev_r))

    # D 分母为 0 的守卫：nwin=0 且 GLB 无色 ⇒ NA，不许 PASS 也不许 FAIL
    f3 = dict(f_)
    f3["glb_windows"] = True
    f3["nwin_built"] = 0
    f3["nsyn_built"] = 0
    f3["colcnt"] = {}
    f3["colors"] = set()
    st3, sev3 = state_of(f3, "WIN_DECL_VS_GLB")
    check("D 应有 0 扇/实有 0 扇 ⇒ NA（不是通过也不是失败）",
          st3 == "NA", "state=%s sev=%s" % (st3, sev3))

    # E 窗数恒等式：c001 真值通过，把应有数 +1 ⇒ 必须红
    f4 = collect("c001")
    st4, sev4 = state_of(f4, "WIN_COUNT")
    f5 = dict(f4)
    f5["nwin_built"] = (f4.get("nwin_built") or 0) + 1
    st5, sev5 = state_of(f5, "WIN_COUNT")
    check("E 窗数恒等式：真值 PASS、应有数 +1 则 FAIL",
          st4 == "PASS" and st5 == "FAIL" and sev5 == "ERROR",
          "真值 state=%s；+1 后 state=%s sev=%s" % (st4, st5, sev5))

    # F 阶梯：c001 真值通过，把 y_max +4.2（正好一层）⇒ 必须红
    f6 = collect("c001")
    st6, _ = state_of(f6, "LADDER_TOP")
    f7 = dict(f6)
    f7["y_max"] = f6["y_max"] + f6["floor_h"]
    st7, sev7 = state_of(f7, "LADDER_TOP")
    check("F 阶梯：真值 PASS、y_max +1 个层高则 FAIL",
          st6 == "PASS" and st7 == "FAIL" and sev7 == "ERROR",
          "真值 state=%s；+%.1f m 后 state=%s sev=%s"
          % (st6, f6["floor_h"], st7, sev7))

    # G 楼板平面：c001 真值通过，挖掉一个平面 ⇒ 必须红
    f8 = collect("c001")
    st8, _ = state_of(f8, "LADDER_SLABS")
    f9 = dict(f8)
    hits = list(f8.get("slab_hits") or [])
    if hits:
        f9["slab_hits"] = hits[:-1]
    st9, sev9 = state_of(f9, "LADDER_SLABS")
    check("G 楼板平面：真值 PASS、少一个平面则 FAIL",
          st8 == "PASS" and st9 == "FAIL" and sev9 == "ERROR",
          "真值 state=%s；少一个后 state=%s sev=%s" % (st8, st9, sev9))

    # H 0 字节 ⇒ 单独一条码，且必须是 GATE_BLIND（ERROR 级）
    fh = dict(f4)
    fh["glb_size"] = 0
    rs = judge(fh)
    codes = [(r["code"], r["state"], r["sev"]) for r in rs]
    check("H 0 字节 ⇒ GLB_ZERO_BYTES + GATE_BLIND",
          len(rs) == 1 and rs[0]["code"] == "GLB_ZERO_BYTES"
          and rs[0]["state"] == "GATE_BLIND" and rs[0]["sev"] == "ERROR",
          "judge 出 %s（必须是**唯一**一条：0 字节时后面所有判据都不许再判）" % codes)

    # I 解析失败 ⇒ GATE_BLIND
    fi = dict(f4)
    fi["parse_ok"] = False
    fi["parse_err"] = "（自证构造）"
    rs = judge(fi)
    check("I 解析失败 ⇒ GATE_BLIND",
          len(rs) == 1 and rs[0]["state"] == "GATE_BLIND" and rs[0]["sev"] == "ERROR",
          "%s" % [(r["code"], r["state"]) for r in rs])

    # J 无 COLOR_0 ⇒ **只有**颜色判据盲，阶梯仍要出数（逐判据盲，不许一盲全盲）
    fj = dict(f4)
    fj["has_color0"] = False
    fj["colcnt"] = {}
    fj["colors"] = set()
    rs = judge(fj)
    byl = {r["code"]: r["state"] for r in rs}
    check("J 无 COLOR_0 ⇒ 颜色判据 BLIND、阶梯仍 PASS",
          byl.get("WIN_DECL_VS_GLB") == "GATE_BLIND"
          and byl.get("LADDER_TOP") == "PASS",
          "逐判据状态 = %s" % byl)

    # K 退出码联动：任何 FAIL / GATE_BLIND 都必须让 sev==ERROR
    bad = [r for r in judge(f_) if r["state"] in ("FAIL", "GATE_BLIND") and r["sev"] != "ERROR"]
    check("K 退出码联动：FAIL/GATE_BLIND ⇒ sev==ERROR",
          not bad, "违例 %d 条" % len(bad))

    print("\n%s（共 %d 条自证，失败 %d 条）"
          % ("★ 自证通过" if not fails else "★ 自证**失败**：" + "、".join(fails),
             total[0], len(fails)))
    return 1 if fails else 0


# ---------------------------------------------------------------- 主流程
def main():
    global BASE, OUTDIR
    argv = sys.argv[1:]
    do_cal = "--calibrate" in argv
    do_self = "--selftest" in argv
    args = [a for a in argv if not a.startswith("--")]

    if do_self:
        # ★ 自证必须跑**真库**：`--base=` 在这里有意不生效（自证要拿真 c001/c006 的
        #   真产物当输入，指向夹具树就变成自证自己造的输入了 —— 那是循环论证）。
        sys.exit(_selftest())

    # `--base=` / `--out=`：**只给自证夹具用**（把门禁指向 _scratch 里一棵造出来的树，
    # 好让"0 字节 GLB ⇒ exit 1"这条**真实退出码路径**被跑到）。
    # ★ 它不改变只读性质：门禁对 --base 指的目录同样一个字节都不写。
    for a in argv:
        if a.startswith("--base="):
            BASE = os.path.abspath(a.split("=", 1)[1])
        elif a.startswith("--out="):
            OUTDIR = os.path.abspath(a.split("=", 1)[1])

    names = sorted(d for d in os.listdir(BASE)
                   if os.path.isdir(os.path.join(BASE, d, "floors")))
    if args:
        names = [n for n in names if n in args]
        if not names:
            print("没有匹配的楼：%s" % args)
            sys.exit(2)

    gauge = _gauge_checks()
    for ok, msg in gauge:
        print("%s %s" % ("[量具自检 ✓]" if ok else "[量具自检 ✗]", msg))
    gauge_ok = all(ok for ok, _ in gauge)
    if not gauge_ok:
        # ★ **就地停手**，不往下判：量具自己坏了的时候，屏幕上继续打出几十行 PASS，
        #   是最坏的形态（本仓铁律 16：量具坏了与通过长得一样）。
        print("★ 量具自检不过 ⇒ 立即退出码 4（门禁自身异常）。"
              "**本次一条判据都没有判** —— 不是因为它们通过，是因为尺子不可信。")
        sys.exit(4)

    base = _load_baseline()
    if not base:
        print("★ 阈值未标定（缺 %s）—— 本次只出数字，**不判绿**（fail-closed）"
              % os.path.basename(BASELINE))
    os.makedirs(OUTDIR, exist_ok=True)

    allrecs, facts, summary = [], [], []
    for i, name in enumerate(names, 1):
        f = collect(name)
        if f.get("floor_read_err"):
            print("   ★ %s 有 %d 个 floors 文件读不出来（这批层没进分母）：%s"
                  % (name, len(f["floor_read_err"]), f["floor_read_err"][:2]))
        recs = judge(f)
        _apply_baseline(recs, base)
        allrecs += recs
        facts.append(f)
        lvl = ("ERROR" if any(r["sev"] == "ERROR" for r in recs)
               else "WARN" if any(r["sev"] == "WARN" for r in recs) else "PASS")
        code_of = ";".join("%s:%s" % (r["code"], r["state"]) for r in recs
                           if r["state"] in ("FAIL", "GATE_BLIND", "KNOWN_BASELINE"))
        summary.append(dict(building=name, level=lvl, n_records=len(recs),
                            n_error=sum(1 for r in recs if r["sev"] == "ERROR"),
                            n_warn=sum(1 for r in recs if r["sev"] == "WARN"),
                            n_known=sum(1 for r in recs if r.get("baseline")),
                            flags=code_of))
        art = dict(schema="glb-gate/1", building=name, level=lvl,
                   thresholds=dict(Y_TOL=Y_TOL, STALE_WARN_H=STALE_WARN_H,
                                   STALE_INFO_H=STALE_INFO_H, COL_TOL=COL_TOL,
                                   VERTS_PER_GLASS=VERTS_PER_GLASS,
                                   VERTS_PER_FRAME=VERTS_PER_FRAME),
                   gauge=dict(ok=gauge_ok,
                              expected_linear=dict(
                                  glass=list(_srgb_to_linear(G.C_GLASS)),
                                  frame=list(_srgb_to_linear(G.C_FRAME)),
                                  slab=list(_srgb_to_linear(G.C_SLAB)))),
                   records=recs)
        # ★ 只写 OUTDIR —— **一个字节都不写 data/**（见文件头「产物归属」）
        _atomic_json(os.path.join(OUTDIR, "%s.json" % name), art)
        print("[%d/%d] %-8s %-5s %s"
              % (i, len(names), name, lvl, code_of or "全部判据通过"), flush=True)

    if args:
        print("\n（单栋/点名模式：**不覆盖**全库卷宗 summary.json —— 同 audit_gate.py 的保护）")
    else:
        _atomic_json(os.path.join(OUTDIR, "summary.json"),
                     dict(schema="glb-gate/1", calibrated=bool(base), gauge_ok=gauge_ok,
                          thresholds=dict(Y_TOL=Y_TOL, STALE_WARN_H=STALE_WARN_H,
                                          STALE_INFO_H=STALE_INFO_H, COL_TOL=COL_TOL,
                                          VERTS_PER_GLASS=VERTS_PER_GLASS,
                                          VERTS_PER_FRAME=VERTS_PER_FRAME),
                          buildings=summary, records=allrecs))

    # ★ 这里必须打印 **所有非 PASS / 非 NA** 的记录，不只是 ERROR/WARN：
    #   陈旧是 INFO 级（低于 1.0 h 但仍晚于 GLB），而"必须打印"是它的存在理由 ——
    #   只打 ERROR/WARN 会让它在屏幕上**彻底消失**（本仓铁律 76：不打印的那一行，
    #   与"验过了没问题"是同一行字）。
    bad = [r for r in allrecs if r["state"] not in ("PASS", "NA")]
    print("\n=== 需要看的每一行（非 PASS / 非 NA，共 %d 条；最多列 40）===" % len(bad))
    print("%-8s %-18s %-6s %-6s %s" % ("楼", "判据码", "级别", "状态", "说明"))
    for r in bad[:40]:
        print("%-8s %-18s %-6s %-6s %s"
              % (r["building"], r["code"], r["sev"], r["state"], r["why"][:110]))

    known = [r for r in allrecs if r.get("baseline") in ("KNOWN_BASELINE",)]
    if known:
        print("\n已基线豁免 %d 条（不阻断，但每条都要有理由；**修完必须从基线删掉**）：" % len(known))
        for r in known:
            print("   %-8s %-18s %s" % (r["building"], r["code"], r["baseline_why"][:140]))

    na = [r for r in allrecs if r["state"] == "NA"]
    print("\n判据**不适用**（分母为 0 —— 这不是通过，是「没有对象可判」）%d 条：" % len(na))
    for r in na:
        print("   %-8s %-18s %s" % (r["building"], r["code"], r["why"][:120]))

    if do_cal:
        _calibration_report(allrecs, facts)

    print("\n写 _qa/glb_gate/（%d 栋 %d 条）%s"
          % (len(names), len(allrecs),
             "+ summary.json" if not args else "（未覆盖 summary.json）"))
    if not base:
        sys.exit(3)
    sys.exit(1 if any(r["sev"] == "ERROR" for r in allrecs) else 0)


if __name__ == "__main__":
    main()

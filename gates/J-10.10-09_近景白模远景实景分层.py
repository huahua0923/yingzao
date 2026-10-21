# -*- coding: utf-8 -*-
r"""J-10.10-09 近景白模 / 远景实景 —— 分层件（步 5 ②，对应建设方案 §7.4.1）

【判据】`tools/place_white_model.py` 出的**分层件**，必须真的分成两层、真的同帧，
  而且**贴图没有被重编码弄胖**。逐条：

    A **落位交叉核对**：`_layers/layers_c006/layers_c006.json::model_placement` 的
      θ / tr_en / 平面质心 / IoU / 边界中位差，必须与 `gates/_out/J-10.10-08.json::placement`
      的同一批量**逐位一致**（≤ `TOL_M`）。
      ★ 两个文件是**两趟不同的代码、不同的日子**写出来的（铁律 187：基线与期望值必须来自
      两次不同读数）—— 拿自己刚写的那份去比自己，等于没比。
    B **盘上件 == 账本**：三个出件 glb 由 trimesh **重新读进来**数面，必须与账本里的
      `white.n_faces` / `reality.faces_far` / `reality.faces_fill` 逐位相等。
    C **两层互补且各自非空**：`faces_far + faces_fill == faces_kept`（账本那把尺子）；
      且 `far_glb + fill_glb == faces_kept`（**独立重读**那把尺子）。两把都过才认。
    D **贴图字节没被重存**：出件两层的图像字节合计**不得超过**源三块 glb 的图像字节合计，
      且出件里出现的 mimeType 必须都在源里出现过。
      ★ 这把尺子拦的是**面数看不出来**的那类错：2026-10-16 实测过一次 ——
      两层**面数一个字没错**，贴图却从 **172.6 MB 涨到 663.0 MB**
      （`PIL.Image.copy()` 丢 `.format` ⇒ trimesh 判不出 JPEG ⇒ 按 PNG 重存，每张涨 7~8 倍）。
      **面数尺子对它全盲**（对照·戊 把这件事复现成证据）。
    E **「糊面」真的是楼身上那一层**：把出件两层的**面心**反解回 (E, N)，用**独立来源**的
      模型 1 层轮廓（取 `J-10.10-08.json::placement.outline_en`，172 点）判内外 ——
      fill 层的面心**必须全在轮廓内**，far 层的面心**必须全在轮廓外**。
      ★ 这条才是「近景用白模替换实景糊面」这句话的几何含义；只核面数会被「随便切两半」蒙过去。
    F **白模落在裁剪盒里**：白模在公共局部帧里的**平面**范围反解回 EN，必须完全落在
      `reality.clip_lo_en / clip_hi_en` 内（否则网页上白模会探出实景之外）。
    G **浏览器上真的换了层**：`demo/layers.html` 用**真浏览器**打开，读**渲染后的 DOM** ——
      锁定近景 ⇒ `fillVisible="false"`、`whiteVisible="true"`、`farVisible="true"`；
      锁定远景 ⇒ `fillVisible="true"`、`whiteVisible="false"`；自动 ＋ 阈值两侧 ⇒ 跟着切。
      ★ 远景时 `farVisible` **恒须为 true**：换的是**楼身上那一层**，不是把实景整个藏掉
      （藏掉连楼周围的地面也没了，看着像模型悬空）。

【量具】
  · `trimesh 5.1` 重读三个出件：面数、包围盒、面心。
  · `open(path,"rb")` **直读 glb 的 JSON 头**数 `images[].bufferView.byteLength` ——
    **不碰 bin 块**，与 trimesh 是两把互不依赖的尺子。
  · `matplotlib.path.Path.contains_points`（C 实现）判内外；bbox 先做排除以省时间。
  · **python playwright（chromium）**在本机 `127.0.0.1:<临时端口>` 打开页面、读
    `document.body.dataset`（照 `gates/J-10.9-04_对照页-viewer.py` 的口径：端口写 **0** 由内核
    分配、用完即关、**不另起常驻服务器**、**不碰**已在跑的 8155）。
  · 阈值 `TOL_M = 1e-6` m：**「复算 == 盘上那份」的浮点口径**，与 `J-10.10-08` 同口径，
    不是手挑的数。D 条用的「不得超过」是**结构性**的（出件是源件的子集，只会更小）。
  · `F32_ULP_M = 3.1e-5` m：glTF 的 `POSITION` 是 **float32**；本件坐标经帧原点平移后
    ~±150 m，单精度在 150 m 处的间隔 = 150 × 2⁻²³ ≈ **1.8e-5 m**，取 3.1e-5 作上界。
    ★ 两处用它：① E 条给「恰好压线、被 float32 舍入翻面」的点留一条窄缝；
    ② 丁条整体平移 1 m 的读数容差 —— **1 m 平移进 float32 后本身就有 ~2e-5 m 的舍入**，
    拿 1e-6 当阈会把「量具自己的精度」误判成「读数没跟着变」。**这条阈值是算出来的，不是挑的。**
  · `MAX_OFFEND_DIST_N = 50000`：E 条算「离边界多远」只在**落点不多于这个数**时算；
    超过 ⇒ `worst_m=None` 并出「没量到最远距离（只报个数）」—— ★ **绝不悄悄截断**（铁律 197）。

【量具盲区】本闸对下面这几类**一个字都不给结论**：
  · **不判「近景换上去好不好看」**：白模**没有 UV、没有贴图**（实测 0 material / 0 image），
    换上去是一块素色几何。本闸只判「层真的换了」，**不判视觉质量**。
  · **不判两层之间的竖向残差**：实景的 h 来自瓦片锚（约定 B），白模的 h 来自 h0，是
    **两个独立来源**；而 h0 本身还有**两个候选**（差 `vertical_anchor.delta_m = 3.602966 m`），
    本闸**不挑**、也不判谁对 —— 那是**用户的决定**（`J-10.10-08` 已单独报出）。
    ⇒ E 条**只用平面两轴**，与 h 无关：两个候选下 E 的读数**完全相同**。
  · **不判裁剪盒够不够大**：`--margin-m 60` 是工具的参数；本闸只核「白模在盒里」。
    实测**裁剪盒四角被实景覆盖 3/4** —— 缺的那一角是**真的没拍到/没转**，不是坏件；
    本闸如实记这个读数，**不因此判红**（那是实景源的覆盖面，不是本件的事）。
  · **不判纹理内容对不对**：D 只核**字节量级与格式**，不核像素。贴图是不是那块墙的颜色，
    本闸看不见（2024 没有原片可比，已在方案 §7 写死）。
  · **面心判内外**：跨轮廓面的**面心**在里侧就归 fill、在外侧就归 far ⇒ 边界上会有**半个面**
    的归属差。本闸量的是**面心**，不是面本身是否被切开（工具口径同此，见其 docstring 盲区 ②）。
  · **`white_local.glb` 的整体包围盒含地下 1 层**（实测 y ∈ [−3.5, 0]）⇒ F 条用的是**平面**范围，
    与 h 无关；G 条读的是**渲染开关**，与几何无关。
  · ★ **G 条的时序**：页面要先把 ~170 MB 的件载进 three.js 才谈得上「换了层」。
    载不完 / 浏览器没装 / 页面上报错**分开报**（铁律 199）：页面取不到或没载完 ⇒ **rc=4「没量到」**；
    载完了却 `dataset.layer == "error"` ⇒ **rc=1**（那个错误块是**量到的读数**）。
  · 本闸**不开** `demo/layers.html` 之外的页面；**不判**页面上的散文/版面/配色。

【正对照】（每条落**读数**不只落 bool）
  ★ 计划文件里逐字点名的那条是「**把模型整体平移 1 m ⇒ 偏差读数必须跟着变**」，本闸把它落在 **丁**。
  甲 真件 —— 基线：A~G **全绿**才算这条正对照「按预期表现」。
  乙 账本 `reality.faces_kept` 改 1 ⇒ **C 红**（两把尺子都去比这个数），而 **B 不动**
     （B 比的是 `white.n_faces` / `faces_far` / `faces_fill` 三个字段，与 `faces_kept` 无关）
     ⇒ 证明 B 与 C 是**两条不同的判据**、不是在数同一个东西。
     ★ 先说清一条：改 `faces_far` / `faces_fill`（而不是 `faces_kept`）会**同时**打红 B 与 C
     —— 那两个字段**两个量具都读**，这是它俩真实的重叠面，不掩。
  丙 账本 `model_placement.tr_en` 平移 **1.000 m** ⇒ **A 的差读数恰好 = 1.000000 m**
     （读数跟着变 ＝ 计划点名那条），而 **D/E 纹丝不动**（贴图与分层跟落位无关）
     ⇒ 分开「量具拍到东西了」与「量具自己在乱动」（铁律 183 的后半句）。
  丁 **白模 glb 整体 +1.000 m** ⇒ 白模包围盒**中心**读数**恰好动 1.000 m**（容差取 float32 那一档）；
     ★ 如实记：F 条那个 bool **不动** —— 1 m 相对 ~160 m 的裁剪盒太小，
     **这条量具在 1 m 尺度上不敏感**，这就是它的代价，写在旁边。
  戊 用「**丢掉 `.format` 的旧写法**」重存一遍 fill 层 ⇒ **D 会红**，A/B/C/E **不动**。
     ★ 判据本身必须是**同作用域的比**：把 fill 换成旧写法的件，于是「出件总量」＝
       `far 现值 ＋ fill 旧值`，再拿它去比**源总量**（＝ D 自己的算式）。
     ★ 这里踩过一次「**部分比整体**」的坑（铁律 194 那一族，同一个量两个不同作用域的估计器）：
       第一版拿 `fill 旧值` 去比 `far ＋ fill 现值`，得 99.97 MB > 101.46 MB 为假 ⇒
       贴图**明明涨了 6.32×** 却报「没按预期」。改成同作用域一比就对了。
     ★ 它同时是**根因证明**：涨了 ⇒「修的是那个因」成立；**不涨 ⇒ 我对根因的说法是错的**，
       本闸如实报出、不掩盖。★ 幅度（实测 **6.32×**）只当**读数**记，**不当阈值** ——
       判据用的是「旧值 > 新值」＋「换上之后 D 的算式成立」这两个**结构性**条件，不手挑倍数。

三态：`RC_PASS=0 / RC_FAIL=1 / RC_NOGAUGE=4`。
"""
import functools
import gc
import hashlib
import http.server
import json
import os
import shutil
import socketserver
import struct
import sys
import threading

import numpy as np
import trimesh
from matplotlib.path import Path as MplPath

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
OUTDIR = os.path.join(HERE, "_out")

GID = "J-10.10-09"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

LAY = os.path.join(ROOT, "过程/_layers", "layers_c006")
JSONP = os.path.join(LAY, "layers_c006.json")
WHITE = os.path.join(LAY, "white_local.glb")
FAR = os.path.join(LAY, "reality_local.glb")
FILL = os.path.join(LAY, "reality_fill_local.glb")
J08 = os.path.join(OUTDIR, "J-10.10-08.json")
SRC_DIR = os.path.join(ROOT, "过程/_layers", "reality_c006")
PAGE = "demo/layers.html"
TMP = os.path.join(OUTDIR, "_layers_probe")

TOL_M = 1e-6               # 「复算 == 盘上那份」的浮点口径（与 J-10.10-08 同口径）
F32_ULP_M = 3.1e-5         # float32 在 ~150 m 处的间隔上界（见 docstring【量具】）
MAX_OFFEND_DIST_N = 50000  # E 条「最远距离」的算力上限；超了报 None，不悄悄截断
PAGE_TIMEOUT_MS = 300000   # 页面要载 ~170 MB 的件；载不完 ⇒ rc=4，不判红
_GLB_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A

_LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def _write_json(rc, **kv):
    d = {"pass": rc == 0, "rc": rc, "gid": GID}
    d.update(kv)
    os.makedirs(OUTDIR, exist_ok=True)
    p = os.path.join(OUTDIR, GID + ".json")
    with open(p, "wb") as f:                      # 字节层写盘（铁律 79）
        f.write(json.dumps(d, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8"))
    log("  写出:", p)


def _finish(rc, verdict, **kv):
    log("===== 判词 =====")
    log("%s 总判 : %s" % (GID, verdict))
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")
    _write_json(rc, verdict=verdict, **kv)
    return rc


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# ─────────────────────── 尺子一：直读 glb 的 JSON 头（不碰 bin） ───────────────────────
def _glb_images(path):
    """返回 `(n_images, {mime: n}, 图像字节合计, bufferViews 总字节)`。

    ★ 只读前两块（JSON 头），**一个 bin 字节都不读** ⇒ 146 MB 的件也是毫秒级。
      与 trimesh 那条路（真把几何解出来）是**两把互不依赖的尺子**。
    """
    with open(path, "rb") as f:
        magic, _ver, _tot = struct.unpack("<III", f.read(12))
        if magic != _GLB_MAGIC:
            raise ValueError("不是 glb（magic 不对）: %s" % path)
        ln, ty = struct.unpack("<II", f.read(8))
        if ty != _JSON_CHUNK:
            raise ValueError("glb 第一块不是 JSON chunk: %s" % path)
        h = json.loads(f.read(ln).decode("utf-8"))
    bv = h.get("bufferViews", [])
    tot = n = 0
    mimes = {}
    for im in h.get("images", []):
        if "bufferView" not in im:
            continue
        n += 1
        tot += int(bv[im["bufferView"]].get("byteLength", 0))
        m = im.get("mimeType", "?")
        mimes[m] = mimes.get(m, 0) + 1
    return n, mimes, tot, int(sum(int(b.get("byteLength", 0)) for b in bv))


def _faces_of(sc):
    return int(sum(len(g.faces) for g in sc.geometry.values()))


def _centers_local(sc):
    """出件各 geometry 的**面心**，仍是公共局部帧 `(xl, yl, zl)`。"""
    xs, ys, zs = [], [], []
    for g in sc.geometry.values():
        v = np.asarray(g.vertices, dtype=np.float64)
        f = np.asarray(g.faces, dtype=np.int64)
        if not len(f):
            continue
        c = v[f].mean(axis=1)
        xs.append(c[:, 0])
        ys.append(c[:, 1])
        zs.append(c[:, 2])
    return (np.concatenate(xs), np.concatenate(ys), np.concatenate(zs))


def _local_xy_to_en(xl, zl, OE, ON):
    """公共局部帧 → (E, N)。`xl = E − OE`、`zl = −(N − ON)` ⇒ 两个水平轴都是**纯平移**。"""
    return OE + np.asarray(xl, dtype=np.float64), ON - np.asarray(zl, dtype=np.float64)


def _bboxes(en, nn):
    return [float(en.min()), float(nn.min())], [float(en.max()), float(nn.max())]


# ─────────────────────── 尺子二：判内外（bbox 先排除，再交给 C 实现） ───────────────────────
def _inside(poly, E, N):
    """返回 `(inside, out_of_bbox)`。`out_of_bbox` 的点**必然在轮廓外**（轮廓的 bbox 之外）。"""
    p = np.asarray(poly, dtype=np.float64)
    P = np.c_[np.asarray(E, dtype=np.float64), np.asarray(N, dtype=np.float64)]
    lo = np.array([p[:, 0].min(), p[:, 1].min()])
    hi = np.array([p[:, 0].max(), p[:, 1].max()])
    out_box = (P[:, 0] < lo[0]) | (P[:, 0] > hi[0]) | (P[:, 1] < lo[1]) | (P[:, 1] > hi[1])
    inside = np.zeros(len(P), dtype=bool)
    if (~out_box).any():
        inside[~out_box] = MplPath(p).contains_points(P[~out_box])
    return inside, out_box


def _dist_to_poly(poly, E, N):
    """点到多边形**边界**的最短距离。★ 只用在小批量落点上，别拿它跑 1.7M 点。"""
    p = np.asarray(poly, dtype=np.float64)
    a = p
    b = np.roll(p, -1, axis=0)
    Q = np.c_[np.asarray(E, dtype=np.float64), np.asarray(N, dtype=np.float64)]
    ab = b - a
    L2 = (ab * ab).sum(axis=1)
    L2[L2 == 0] = 1.0
    best = np.full(len(Q), np.inf)
    for i in range(len(a)):
        t = np.clip(((Q - a[i]) @ ab[i]) / L2[i], 0.0, 1.0)
        proj = a[i] + t[:, None] * ab[i]
        best = np.minimum(best, np.linalg.norm(Q - proj, axis=1))
    return best


def _worst_m(poly, E, N, mask):
    """落点里离轮廓边界**最远**的那个距离；落点太多 ⇒ `None`（＝没量到，不截断报小值）。"""
    n = int(mask.sum())
    if n == 0:
        return 0.0, 0, False
    if n > MAX_OFFEND_DIST_N:
        return None, n, True
    return float(_dist_to_poly(poly, E[mask], N[mask]).max()), n, False


# ─────────────────────── 页面侧：临时端口 + 真浏览器读渲染后 DOM ───────────────────────
class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if isinstance(e, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        socketserver.ThreadingTCPServer.handle_error(self, request, client_address)


def _serve(root):
    srv = _Srv(("127.0.0.1", 0), functools.partial(_Quiet, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


DOM_JS = r"""() => {
  const d = document.body.dataset || {};
  const o = window.__layers || {};
  const miss = document.getElementById('miss');
  const g = v => (v === undefined || v === null) ? null : v;
  return {
    layer: g(d.layer), white: g(d.whiteVisible), fill: g(d.fillVisible), far: g(d.farVisible),
    anchor: g(d.anchor), mode: g(d.mode), threshold: g(d.threshold),
    delta: g(d.delta), whiteY: g(d.whiteY),
    loaded: !!o.loaded, counts: o.counts || null,
    prov_ok: !!(o.prov && o.prov.schema),
    miss: (miss && miss.hidden === false)
          ? (miss.textContent || '').replace(/\s+/g, ' ').trim() : null,
    err: o.error || null
  };
}"""

SET_JS = r"""(a) => {
  const sel = document.querySelector('input[name=mode][value="' + a.mode + '"]');
  if (sel) { sel.checked = true; sel.dispatchEvent(new Event('change', {bubbles: true})); }
  const t = document.getElementById('thr');
  if (t) { t.value = String(a.thr); t.dispatchEvent(new Event('input', {bubbles: true})); }
  const an = document.querySelector('input[name=anc][value="' + a.anc + '"]');
  if (an) { an.checked = true; an.dispatchEvent(new Event('change', {bubbles: true})); }
  return true;
}"""


def _probe(root, page_rel):
    """返回 `(dom, err_kind, console)`；`err_kind` 非空 ⇒ **没量到**（rc=4 那条路）。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:                                     # noqa: BLE001
        return None, "没装 playwright（%s）" % e, []
    console = []
    srv, port = _serve(root)
    try:
        log("  临时端口 %d（127.0.0.1，用完即关；不用 8155）→ %s" % (port, page_rel))
        url = "http://127.0.0.1:%d/%s" % (port, page_rel)
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                pg = b.new_page()
                pg.on("console", lambda m: console.append("%s: %s" % (m.type, m.text)))
                pg.on("pageerror", lambda e: console.append("pageerror: %s" % e))
                r = pg.goto(url, timeout=PAGE_TIMEOUT_MS)
                if r is None or r.status >= 400:
                    return None, "HTTP %s（%s）" % (r.status if r else "?", url), console
                try:
                    pg.wait_for_function(
                        "() => (window.__layers && window.__layers.loaded === true)"
                        " || (document.body && document.body.dataset"
                        "     && document.body.dataset.layer === 'error')",
                        timeout=PAGE_TIMEOUT_MS)
                except Exception as e:                          # noqa: BLE001
                    return None, "%d ms 内页面没载完（%s）" % (PAGE_TIMEOUT_MS, e), console
                out = {"dom": pg.evaluate(DOM_JS)}
                for tag, mode, thr, anc in (("near", "near", 180, "ground"),
                                            ("far", "far", 180, "ground"),
                                            ("auto_low", "auto", 1, "ground"),
                                            ("auto_high", "auto", 600, "ground"),
                                            ("near_roof", "near", 180, "roof")):
                    pg.evaluate(SET_JS, {"mode": mode, "thr": thr, "anc": anc})
                    pg.wait_for_timeout(400)          # 让 tick() 至少跑一帧
                    out[tag] = pg.evaluate(DOM_JS)
                return out, "", console
            finally:
                b.close()
    except Exception as e:                                      # noqa: BLE001
        return None, "浏览器起不来/打不开（%s）" % e, console
    finally:
        srv.shutdown()


# ─────────────────────── 正对照要用的两个「变坏件」 ───────────────────────
def _white_shifted(dst, dx=1.0):
    """★ 把白模**整体**平移 `dx` 米（局部 x 轴，＝ E 方向），写出一个新 glb。
    这条是计划文件点名要的正对照：**整体平移 1 m ⇒ 读数必须跟着变**。"""
    sc = trimesh.load(WHITE, force="scene")
    out = trimesh.Scene()
    for name, g in sc.geometry.items():
        ng = g.copy()
        ng.vertices = np.asarray(g.vertices, dtype=np.float64) + np.array([dx, 0.0, 0.0])
        out.add_geometry(ng, node_name=name, geom_name=name)
    with open(dst, "wb") as f:
        f.write(out.export(file_type="glb"))
    return dst


def _resave_old_way(src, dst):
    """★ 复现 2026-10-16 抓到的暗伤：`Trimesh.copy()` → `TextureVisuals.copy()` →
    `PBRMaterial.copy()` → `PIL.Image.copy()`，PIL 那一次 copy **不带 `.format`** ⇒
    trimesh 的 `_append_image` 认不出 `image/jpeg`、走 PNG 分支。
    ★ 它**同时是根因证明**：它涨 ⇒「修的是那个因」成立；**不涨 ⇒ 本闸对根因的说法是错的**。"""
    sc = trimesh.load(src, force="scene")
    out = trimesh.Scene()
    for name, g in sc.geometry.items():
        out.add_geometry(g.copy(), node_name=name, geom_name=name)
    with open(dst, "wb") as f:
        f.write(out.export(file_type="glb"))
    return dst


# ────────────────────────────────────── main ──────────────────────────────────────
def main():
    log("%s 近景白模 / 远景实景 —— 分层件（步 5 ②）" % GID)
    log("  仓:", ROOT)
    for p in (JSONP, WHITE, FAR, FILL):
        if not os.path.exists(p):
            return _finish(RC_NOGAUGE, "NOGAUGE",
                           reason="缺件，尺子没立起来：%s" % p,
                           blind=["缺件 ⇒ 本闸拒绝出任何读数，不拿半个答案顶替"])
    if not os.path.exists(J08):
        return _finish(RC_NOGAUGE, "NOGAUGE",
                       reason="缺独立读数 `%s`（A 条要靠它做两次不同读数的交叉核对）" % J08,
                       blind=["没有第二份读数 ⇒ A 条会降级成自己比自己，本闸不做"])

    with open(JSONP, encoding="utf-8") as f:
        AJ = json.load(f)
    with open(J08, encoding="utf-8") as f:
        J8 = json.load(f)
    mp = AJ["model_placement"]
    re_ = AJ["reality"]
    wh = AJ["white"]
    va = AJ["vertical_anchor"]
    OE, ON, OH = [float(x) for x in AJ["local_frame"]["origin_en_h"]]
    # ★ 2026-10-20：`J-10.10-08` 现在是 rc=4（同类构件顶标高不唯一）⇒ 它的出件里**没有**
    #   `placement`。这里原来直接 `J8["placement"]` ⇒ KeyError traceback，
    #   症状是 rc=1「不符」，与「没量到」同形（铁律 199）。第二份读数缺键就如实报 NOGAUGE，
    #   并把「谁为什么没给」写进理由——本闸一个人也量不了 A 条。
    if "placement" not in J8:
        return _finish(RC_NOGAUGE, "NOGAUGE",
                       reason="独立读数 %s 里没有 `placement`（它自己 rc=%s：%s）"
                              % (os.path.basename(J08), J8.get("rc"),
                                 (J8.get("reason") or J8.get("判词") or "未写理由")),
                       blind=["第二份读数缺 A 条要用的键 ⇒ A 条量不了；不拿自己比自己顶替"])
    p8 = J8["placement"]
    log("  账本 %s ｜ 独立读数 %s（rc=%s）" % (os.path.basename(JSONP),
                                              os.path.basename(J08), J8.get("rc")))

    fail = []
    rec = {}

    # ── A 落位交叉核对（两个文件、两趟代码、两次不同读数） ──
    cross = {
        "theta_deg": [float(mp["theta_deg"]), float(p8["theta_deg"])],
        "tr_en": [list(map(float, mp["tr_en"])), list(map(float, p8["tr_en"]))],
        "plan_ctr_m": [list(map(float, mp["plan_ctr_m"])),
                       list(map(float, p8["model_ctr_m_from_mm_origin"]))],
        "best_iou": [float(mp["best_iou"]), float(p8["best_iou"])],
        "boundary_median_m": [float(mp["boundary_median_m"]), float(p8["boundary_median_m"])],
    }
    a_max = 0.0
    for k, (x, y) in cross.items():
        d = float(np.abs(np.asarray(x, dtype=float) - np.asarray(y, dtype=float)).max())
        cross[k] = {"ledger": x, "indep": y, "max_abs_diff": d}
        a_max = max(a_max, d)
    a_ok = a_max <= TOL_M
    log("  A 落位交叉核对：两文件最大差 %.3e m（阈 %.0e）⇒ %s" % (a_max, TOL_M, "过" if a_ok else "**红**"))
    if not a_ok:
        fail.append("A 落位交叉核对：%s 与 %s 对不上，最大差 %.6g m" % (
            os.path.basename(JSONP), os.path.basename(J08), a_max))
    rec["placement_cross"] = {"items": cross, "max_abs_diff_m": a_max, "tol_m": TOL_M, "ok": a_ok}

    # ── 读三个出件（trimesh：面数 / 包围盒 / 面心） ──
    log("  读三个出件…")
    sc_far = trimesh.load(FAR, force="scene")
    sc_fill = trimesh.load(FILL, force="scene")
    sc_wh = trimesh.load(WHITE, force="scene")
    n_far, n_fill, n_wh = _faces_of(sc_far), _faces_of(sc_fill), _faces_of(sc_wh)
    log("    盘上件面数：白模 %d ｜ 远景 %d ｜ 近景糊面 %d" % (n_wh, n_far, n_fill))

    # ── B 盘上件 == 账本 ──
    b_items = {
        "white.n_faces": [int(wh["n_faces"]), n_wh],
        "reality.faces_far": [int(re_["faces_far"]), n_far],
        "reality.faces_fill": [int(re_["faces_fill"]), n_fill],
    }
    b_bad = [k for k, (x, y) in b_items.items() if int(x) != int(y)]
    b_ok = not b_bad
    if b_ok:
        log("  B 盘上件 vs 账本：过")
    else:
        log("  B 盘上件 vs 账本：**红** → %s" % ", ".join(
            "%s 账本 %d ≠ 盘上 %d" % (k, b_items[k][0], b_items[k][1]) for k in b_bad))
        fail.append("B 盘上件与账本对不上：" + ", ".join(
            "%s 账本 %d ≠ 盘上 %d" % (k, b_items[k][0], b_items[k][1]) for k in b_bad))
    rec["files"] = {
        "white": {"path": os.path.relpath(WHITE, ROOT), "bytes": os.path.getsize(WHITE),
                  "sha256": _sha256(WHITE), "faces_glb": n_wh, "faces_json": int(wh["n_faces"])},
        "far": {"path": os.path.relpath(FAR, ROOT), "bytes": os.path.getsize(FAR),
                "sha256": _sha256(FAR), "faces_glb": n_far, "faces_json": int(re_["faces_far"])},
        "fill": {"path": os.path.relpath(FILL, ROOT), "bytes": os.path.getsize(FILL),
                 "sha256": _sha256(FILL), "faces_glb": n_fill, "faces_json": int(re_["faces_fill"])},
        "items": {k: {"json": v[0], "glb": v[1]} for k, v in b_items.items()},
        "ok": b_ok,
    }

    # ── C 两层互补且各自非空 ──
    kept = int(re_["faces_kept"])
    c_nonempty = (n_far > 0) and (n_fill > 0) and (n_wh > 0)
    c_json = (int(re_["faces_far"]) + int(re_["faces_fill"])) == kept
    c_glb = (n_far + n_fill) == kept
    c_ok = c_nonempty and c_json and c_glb
    log("  C 互补/非空：远 %d ＋ 糊 %d = %d（账本 faces_kept %d）｜非空 %s ⇒ %s" % (
        n_far, n_fill, n_far + n_fill, kept, c_nonempty, "过" if c_ok else "**红**"))
    if not c_ok:
        why = []
        if not c_nonempty:
            why.append("有层是空的（远 %d / 糊 %d / 白 %d）—— 空的层会让本判据恒真" % (n_far, n_fill, n_wh))
        if not c_json:
            why.append("账本自洽被破：%d + %d ≠ %d（kept）" % (
                int(re_["faces_far"]), int(re_["faces_fill"]), kept))
        if not c_glb:
            why.append("盘上件面数与 faces_kept 对不上：%d + %d ≠ %d" % (n_far, n_fill, kept))
        fail.append("C " + "；".join(why))
    rec["complement"] = {"faces_kept": kept, "far_glb": n_far, "fill_glb": n_fill,
                         "sum_glb": n_far + n_fill, "json_self_consistent": c_json,
                         "nonempty": c_nonempty, "ok": c_ok}

    # ── E 分层在几何上真的分开了（先算面心的 EN，再放掉两个大场景） ──
    xf, _yf, zf = _centers_local(sc_far)
    Ef, Nf = _local_xy_to_en(xf, zf, OE, ON)
    xi, _yi, zi = _centers_local(sc_fill)
    Ei, Ni = _local_xy_to_en(xi, zi, OE, ON)
    wl = np.vstack([np.asarray(g.vertices, dtype=np.float64) for g in sc_wh.geometry.values()])
    del sc_far, sc_fill, sc_wh, xf, zf, xi, zi
    gc.collect()

    poly = p8["outline_en"]
    ins_f, outbox_f = _inside(poly, Ef, Nf)
    ins_i, outbox_i = _inside(poly, Ei, Ni)
    # far 的「错侧」＝ 面心落在轮廓**内**；fill 的「错侧」＝ 面心落在轮廓**外**
    bad_far = ins_f
    bad_fill = (~ins_i) | outbox_i          # 同一件事的两种来源，并成一支
    worst_far, n_bad_far, far_trunc = _worst_m(poly, Ef, Nf, bad_far)
    worst_fill, n_bad_fill, fill_trunc = _worst_m(poly, Ei, Ni, bad_fill)
    trunc = far_trunc or fill_trunc
    e_ok = (not trunc) and (worst_far is not None) and (worst_fill is not None) \
        and worst_far <= F32_ULP_M and worst_fill <= F32_ULP_M
    if trunc:
        log("  E 分层分离：落点太多（远 %d / 糊 %d，阈 %d）⇒ **最远距离没量到**（只报个数）"
            % (n_bad_far, n_bad_fill, MAX_OFFEND_DIST_N))
        fail.append("E 错侧落点超出量程（远 %d / 糊 %d > %d）—— 分层明显没分开，"
                    "且最远距离这一读数**没量到**" % (n_bad_far, n_bad_fill, MAX_OFFEND_DIST_N))
    else:
        log("  E 分层分离：远景 %d 个面心落在轮廓内(最远 %.3e m)｜糊面 %d 个面心落在轮廓外"
            "(最远 %.3e m) ⇒ %s" % (n_bad_far, worst_far, n_bad_fill, worst_fill,
                                    "过" if e_ok else "**红**"))
        if not e_ok:
            fail.append("E 分层在几何上没分开：远景 %d 个面心在轮廓内（最远 %.4g m）、"
                        "近景糊面 %d 个面心在轮廓外（最远 %.4g m）"
                        % (n_bad_far, worst_far, n_bad_fill, worst_fill))
    rec["separate"] = {
        "outline_src": "%s::placement.outline_en" % os.path.basename(J08),
        "outline_n": int(len(poly)), "json_outline_n": int(re_.get("outline_n", -1)),
        "far": {"n": n_far, "n_centers_inside_outline": n_bad_far, "worst_m": worst_far},
        "fill": {"n": n_fill, "n_centers_outside_outline": n_bad_fill, "worst_m": worst_fill},
        "f32_ulp_m": F32_ULP_M, "dist_truncated": bool(trunc),
        "max_offend_dist_n": MAX_OFFEND_DIST_N, "ok": e_ok,
    }

    # ── D 贴图字节（直读 glb 头） ──
    src_tot, src_mimes, src_per = 0, {}, []
    for blk in re_["blocks"]:
        bp = os.path.join(SRC_DIR, blk["block"], blk["block"] + ".glb")
        if not os.path.exists(bp):
            return _finish(RC_NOGAUGE, "NOGAUGE",
                           reason="源主件不在，字节尺子立不起来：%s" % bp,
                           blind=["源件不在 ⇒ D 条没有比较对象；本闸不拿出件自己比出件"])
        n_i, mim, tot, _bv = _glb_images(bp)
        src_tot += tot
        for k, v in mim.items():
            src_mimes[k] = src_mimes.get(k, 0) + v
        src_per.append({"block": blk["block"], "n_images": n_i, "img_bytes": tot, "mimes": mim})
    out_tot, out_mimes, out_per = 0, {}, {}
    for tag, p in (("far", FAR), ("fill", FILL)):
        n_i, mim, tot, bv = _glb_images(p)
        out_tot += tot
        for k, v in mim.items():
            out_mimes[k] = out_mimes.get(k, 0) + v
        out_per[tag] = {"n_images": n_i, "img_bytes": tot, "mimes": mim, "buffer_bytes": bv}
    alien = sorted(set(out_mimes) - set(src_mimes))
    d_ok = (out_tot <= src_tot) and (not alien)
    log("  D 贴图字节：源三块 %.1f MB（%s）→ 出件两层 %.1f MB（%s）比值 %.3f ⇒ %s"
        % (src_tot / 1e6, src_mimes, out_tot / 1e6, out_mimes,
           out_tot / max(1.0, src_tot), "过" if d_ok else "**红**"))
    if not d_ok:
        why = []
        if out_tot > src_tot:
            why.append("贴图被重存胖了：出件 %.1f MB > 源 %.1f MB（涨 %.2f 倍）"
                       % (out_tot / 1e6, src_tot / 1e6, out_tot / max(1.0, src_tot)))
        if alien:
            why.append("出件里出现了源里没有的图片格式 %s ⇒ 有贴图被重编码" % alien)
        fail.append("D " + "；".join(why))
    rec["texture_bytes"] = {
        "src": {"per_block": src_per, "total_bytes": src_tot, "mimes": src_mimes},
        "out": {"per_layer": out_per, "total_bytes": out_tot, "mimes": out_mimes},
        "ratio": out_tot / max(1.0, src_tot), "alien_mimes": alien, "ok": d_ok,
        "why": "出件是源件的面子集 ⇒ 图像只会更少或相等；涨了就是被重存过",
    }

    # ── F 白模平面范围落在裁剪盒内 ──
    wE, wN = _local_xy_to_en(wl[:, 0], wl[:, 2], OE, ON)
    wlo, whi = _bboxes(wE, wN)
    clo = [float(x) for x in re_["clip_lo_en"]]
    chi = [float(x) for x in re_["clip_hi_en"]]
    f_ok = (wlo[0] >= clo[0] and wlo[1] >= clo[1] and whi[0] <= chi[0] and whi[1] <= chi[1])
    log("  F 白模在裁剪盒内：白模 E[%.1f,%.1f] N[%.1f,%.1f] ⊂ 盒 E[%.1f,%.1f] N[%.1f,%.1f] ⇒ %s"
        % (wlo[0], whi[0], wlo[1], whi[1], clo[0], chi[0], clo[1], chi[1],
           "过" if f_ok else "**红**"))
    if not f_ok:
        fail.append("F 白模平面范围探出裁剪盒：白模 E[%.3f,%.3f] N[%.3f,%.3f] vs 盒 "
                    "E[%.3f,%.3f] N[%.3f,%.3f]" % (wlo[0], whi[0], wlo[1], whi[1],
                                                   clo[0], chi[0], clo[1], chi[1]))
    rec["white_in_clip"] = {"white_en_lo": wlo, "white_en_hi": whi,
                            "clip_lo_en": clo, "clip_hi_en": chi, "ok": f_ok,
                            "corners_covered_by_reality": int(re_.get("corners_covered", -1)),
                            "corners_note": "四角有一角没被实景盖住 = 实景源真的没拍到那一片；"
                                            "本闸如实记，**不因此判红**"}

    # ── G 浏览器上真的换了层（真浏览器，读渲染后的 DOM） ──
    dom, gerr, console = _probe(ROOT, PAGE)
    g_rec = {"page": PAGE, "timeout_ms": PAGE_TIMEOUT_MS, "console_tail": console[-8:]}
    if dom is None:
        log("  G 浏览器：**没量到** —— %s" % gerr)
        return _finish(RC_NOGAUGE, "NOGAUGE",
                       reason="G 条没量到（%s）" % gerr,
                       placement_cross=rec["placement_cross"], files=rec["files"],
                       complement=rec["complement"], separate=rec["separate"],
                       texture_bytes=rec["texture_bytes"], white_in_clip=rec["white_in_clip"],
                       browser=g_rec,
                       blind=["G 条没量到 ⇒ 本闸**只**在这一条上 rc=4，别的条不跟着降级"])
    if dom["dom"].get("layer") == "error" or dom["dom"].get("miss"):
        log("  G 浏览器：页面画出来了，但报错 ⇒ **红**：%s"
            % (dom["dom"].get("miss") or dom["dom"].get("err")))
        fail.append("G 页面画出来了却报「读不到数据文件 / 载不动」：%s"
                    % (dom["dom"].get("miss") or dom["dom"].get("err")))
    g_cases = [
        ("near", "near", True, False),
        ("far", "far", False, True),
        ("auto_low", "far", False, True),
        ("auto_high", "near", True, False),
        ("near_roof", "near", True, False),
    ]
    g_items = {}
    for tag, want_layer, want_white, want_fill in g_cases:
        d = dom[tag]
        ok = (d.get("layer") == want_layer and d.get("white") == ("true" if want_white else "false")
              and d.get("fill") == ("true" if want_fill else "false") and d.get("far") == "true")
        g_items[tag] = {"layer": d.get("layer"), "whiteVisible": d.get("white"),
                        "fillVisible": d.get("fill"), "farVisible": d.get("far"),
                        "want_layer": want_layer, "want_white": want_white, "want_fill": want_fill,
                        "threshold": d.get("threshold"), "anchor": d.get("anchor"),
                        "whiteY": d.get("whiteY"), "ok": ok}
        if not ok:
            fail.append("G[%s] 页面的层没照预期切：拿到 layer=%s white=%s fill=%s far=%s，"
                        "期望 layer=%s white=%s fill=%s far=true"
                        % (tag, d.get("layer"), d.get("white"), d.get("fill"), d.get("far"),
                           want_layer, want_white, want_fill))
    cts = dom["dom"].get("counts") or {}
    cnt_ok = (cts.get("far") == n_far and cts.get("fill") == n_fill and cts.get("white") == n_wh)
    if not cnt_ok:
        fail.append("G 页面上数出来的面数与 trimesh 对不上：页面 %s vs trimesh "
                    "{white:%d, far:%d, fill:%d}" % (cts, n_wh, n_far, n_fill))
    dy_raw = dom["near_roof"].get("whiteY")
    dy = float(dy_raw) if dy_raw is not None else None
    anc_ok = dy is not None and abs(dy - float(va["delta_m"])) <= 1e-6
    if not anc_ok:
        fail.append("G 竖向锚切换不是 delta 的纯 Y 平移：页面 whiteY=%s，delta=%r"
                    % (dy_raw, va["delta_m"]))
    g_ok = all(v["ok"] for v in g_items.values()) and cnt_ok and anc_ok
    log("  G 浏览器分层：5 例全过 %s ｜ 面数对账 %s ｜ 锚平移 %s ⇒ %s"
        % (all(v["ok"] for v in g_items.values()), cnt_ok, anc_ok, "过" if g_ok else "**红**"))
    g_rec.update({"cases": g_items, "counts": cts,
                  "counts_expected": {"white": n_wh, "far": n_far, "fill": n_fill},
                  "counts_ok": cnt_ok, "anchor_shift_ok": anc_ok,
                  "delta_m": float(va["delta_m"]), "ok": g_ok})

    # ─────────────────────── 正对照 ───────────────────────
    log("  正对照：")
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)
    ctl = []
    n_fail_at_baseline = len(fail)

    def rec_ctl(case, expect, fired, **kw):
        ctl.append(dict(case=case, expect=expect, fired=bool(fired), **kw))
        log("    %s 期望 %-40s ⇒ %s" % (case, expect, "按预期" if fired else "**没按预期**"))

    # 甲 基线
    rec_ctl("甲", "基线：真件 A~G 全绿", n_fail_at_baseline == 0,
            n_fail=n_fail_at_baseline, fail=list(fail),
            note="基线本身不该额外「触发」什么；它「按预期」就是 A~G 一条都不红")

    # 乙 账本 faces_kept 改 1 ⇒ C 红，B 不动
    kept2 = kept + 1
    c_json2 = (int(re_["faces_far"]) + int(re_["faces_fill"])) == kept2
    c_glb2 = (n_far + n_fill) == kept2
    b_unchanged2 = (int(wh["n_faces"]) == n_wh and int(re_["faces_far"]) == n_far
                    and int(re_["faces_fill"]) == n_fill)
    rec_ctl("乙", "C 红（两把尺子都比这个数）、B 不动",
            (not c_json2) and (not c_glb2) and b_unchanged2,
            faces_kept_modified=kept2, far_plus_fill=n_far + n_fill,
            json_self_consistent=c_json2, glb_vs_kept=c_glb2, b_fields_unchanged=b_unchanged2,
            note="改 faces_far/faces_fill 会**同时**打红 B 与 C（那两个字段两个量具都读）；"
                 "改 faces_kept 才是 C 单独那条 —— 本对照用的是后者")

    # 丙 账本 tr_en 平移 1.000 m
    tr2 = [float(mp["tr_en"][0]) + 1.0, float(mp["tr_en"][1])]
    d3 = float(np.abs(np.asarray(tr2, dtype=float)
                      - np.asarray(p8["tr_en"], dtype=float)).max())
    rec_ctl("丙", "A 的差读数恰好 1.000000 m", abs(d3 - 1.0) <= 1e-9,
            max_abs_diff_m=d3, note="★ 计划点名的那条：**模型整体平移 1 m ⇒ 偏差读数必须跟着变**；"
                                    "同时 D/E 必须纹丝不动（贴图与分层跟落位无关）")

    # 丁 白模 glb 整体 +1 m
    wsp = _white_shifted(os.path.join(TMP, "white_shift1m.glb"), 1.0)
    sw = trimesh.load(wsp, force="scene")
    wl2 = np.vstack([np.asarray(g.vertices, dtype=np.float64) for g in sw.geometry.values()])
    del sw
    gc.collect()
    wE2, wN2 = _local_xy_to_en(wl2[:, 0], wl2[:, 2], OE, ON)
    lo2, hi2 = _bboxes(wE2, wN2)
    c1 = np.array([(wlo[0] + whi[0]) / 2, (wlo[1] + whi[1]) / 2])
    c2 = np.array([(lo2[0] + hi2[0]) / 2, (lo2[1] + hi2[1]) / 2])
    d_center = float(np.abs(c2 - c1).max())
    f_ok2 = (lo2[0] >= clo[0] and lo2[1] >= clo[1] and hi2[0] <= chi[0] and hi2[1] <= chi[1])
    rec_ctl("丁", "白模 +1 m ⇒ 中心读数恰好动 1.000 m", abs(d_center - 1.0) <= F32_ULP_M,
            center_before=c1.tolist(), center_after=c2.tolist(), center_shift_m=d_center,
            tol_m=F32_ULP_M, clip_bool_before=f_ok, clip_bool_after=f_ok2,
            note="容差取 float32 那一档：1 m 平移写进 glb 本身就有 ~2e-5 m 舍入。"
                 "★ 如实记：F 条那个 bool **1 m 下不动**（1 m 相对 ~160 m 的盒太小）"
                 "—— 这条量具在 1 m 尺度上不敏感，这就是它的代价")

    # 戊 旧写法重存 fill 层 ⇒ 贴图必须涨，且**换上之后 D 的算式会红**
    bloated = _resave_old_way(FILL, os.path.join(TMP, "fill_old_way.glb"))
    _n, _m, tot_old, _bv = _glb_images(bloated)
    ratio_old = tot_old / max(1.0, out_per["fill"]["img_bytes"])
    # ★ 同作用域：把 fill 换成旧写法的件，「出件总量」才是 far＋fill_旧，拿它去比源总量。
    #   拿 fill_旧 直接比 far＋fill_现 = **部分比整体**，涨得再多也会被判成「没动」。
    out_tot_old = out_per["far"]["img_bytes"] + tot_old
    d_would_fail = out_tot_old > src_tot
    rec_ctl("戊", "旧写法下 D 会红（出件总量 > 源总量）",
            (tot_old > out_per["fill"]["img_bytes"]) and d_would_fail,
            old_way_fill_img_bytes=tot_old, fixed_fill_img_bytes=out_per["fill"]["img_bytes"],
            ratio=round(ratio_old, 2),
            out_total_if_fill_old=out_tot_old, src_total=src_tot, d_would_fail=d_would_fail,
            note="★ 它同时是**根因证明**：涨 ⇒「修的是那个因」成立；不涨 ⇒ 本闸对根因的说法是错的。"
                 "★ 幅度只当读数、不当阈值；判据是「旧值 > 新值」＋「换上后 D 会红」")
    shutil.rmtree(TMP, ignore_errors=True)

    n_ctl_fired = sum(1 for c in ctl if c["fired"])
    log("  正对照 %d/%d 按预期" % (n_ctl_fired, len(ctl)))

    blind = [
        "不判「近景换上去好不好看」：白模 0 material / 0 image（实测）⇒ 换上去是素色几何；本闸只判层换了",
        ("不判两层之间的竖向残差：实景 h 来自瓦片锚、白模 h 来自 h0，两个独立来源；h0 还有两个候选"
         "（差 %.6f m），本闸不挑、也不判谁对 —— 那是用户的决定（J-10.10-08 已单独报出）"
         " ⇒ E 条只用平面两轴，两个候选下读数**完全相同**" % float(va["delta_m"])),
        ("不判裁剪盒够不够大；只核「白模在盒里」。四角被实景覆盖 %d/4 —— 缺的那一角是实景源真的"
         "没拍到/没转，本闸如实记，不因此判红" % int(re_.get("corners_covered", -1))),
        "不判纹理内容：D 只核字节量级与格式，不核像素（2024 没有原片可比）",
        "面心判内外：跨轮廓面按**面心**归属 ⇒ 边界上有半个面的归属差；本闸量面心，不量面是否被切开",
        ("F/G 与 h 无关（F 用平面范围、G 读渲染开关）⇒ white_local.glb 里那层地下 1 层（y∈[−3.5,0]）"
         "不参与这两条"),
        ("G 的时序：页面要先把 ~170 MB 的件载进 three.js；载不完/浏览器没装 ⇒ rc=4「没量到」，"
         "载完了却 dataset.layer=='error' ⇒ rc=1（分开报，铁律 199）"),
        "本闸只开 demo/layers.html 这一页；不判版面、配色、散文",
    ]

    ok = (not fail) and n_ctl_fired == len(ctl)
    if fail:
        log("  ↓ 红在：")
        for x in fail:
            log("    · " + x)
    if n_ctl_fired != len(ctl):
        log("  ↓ 正对照没按预期触发的：")
        for c in ctl:
            if not c["fired"]:
                log("    · %s 期望 %s" % (c["case"], c["expect"]))
    return _finish(RC_PASS if ok else RC_FAIL, "PASS" if ok else "FAIL",
                   n_fail=len(fail), fail=fail,
                   n_controls=len(ctl), n_controls_fired=n_ctl_fired, controls=ctl,
                   local_frame={"origin_en_h": [OE, ON, OH]},
                   vertical_anchor={"chosen": va.get("chosen"), "delta_m": float(va["delta_m"]),
                                    "h0_ground_m": float(va["h0_ground_m"]),
                                    "h0_roof_m": float(va["h0_roof_m"])},
                   placement_cross=rec["placement_cross"], files=rec["files"],
                   complement=rec["complement"], separate=rec["separate"],
                   texture_bytes=rec["texture_bytes"], white_in_clip=rec["white_in_clip"],
                   browser=g_rec, blind=blind)


if __name__ == "__main__":
    sys.exit(main())

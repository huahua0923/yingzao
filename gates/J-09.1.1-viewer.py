# -*- coding: utf-8 -*-
"""判据 J-09.1.1：**查看器的三种手势真的各干各的、且滚轮按滚动量缩放**（案 §9.1.1 演示件）。

为什么单开一条：
  · 用户判词 2026-10-12「中键滚轮没用好，摁住能拖动就好了」—— 这是**交互**缺陷，不是几何缺陷；
    几何判据（IoU / 层对齐）对它全盲。
  · 交付的查看器是**手搓**控制器（不是 OrbitControls），改一行就可能三种手势互相串。

量什么：**相机状态**（注视点 LOOK / 方位 theta / 俯仰 phi / 距离 radius）。四件套（§10.0.1）：
  ① 量交付件本身 —— 起一个**自己的** http 服务，加载 `demo/index.html`，在真页面上派发真事件
  ② 量具写明      —— 本脚本；读数取自页面唯一的**只读**探针 `window.__cdutView()`
  ③ 盲区声明      —— 见下
  ④ 正对照必配    —— **五条**（E2/F2/J2 实跑旧式实现与计数器；H2/I2 解析对照）
                     ※ A/B/C/D/G 是**负刺激与解析解**（给已知的 0 或已知的 120px×k），
                       不是正对照，别与上面五条混算。

★ 判据（全部为真才算过）：
  A. **中键按住拖 = 平移**：|ΔLOOK| 必须 == `120 px × k`（k = 2·radius·tan(fov/2)/视口高，
     已知刺激的**解析解**，不是手调常数），且 theta/radius **不动**
  B. **右键按住拖 = 平移**：同上（用户要的「摁住拖动」两个钮都要有）
  C. **左键拖 = 旋转**：theta **必须变**，而 LOOK **必须不动**（A/B 与 C 必须被分开）
  D. **零位移中键 ⇒ LOOK 不动**（负对照：不给已知量为 0 的刺激，A 条的读数不算数）
  E. **滚轮按滚动量**：deltaY=80 与 160 的**因子必须不同**，且各等于 `exp(d·K)`（K 从页面读）
  F. **滚轮可逆**：+100 再 −100 ⇒ radius 相对误差 == 0
  G. **双击复位到开场那一帧**：pan 走再双击 ⇒ LOOK/theta/phi/radius 四项全部回到 `home`
  H. **滚轮朝指针缩放，锚点是「射线打到的那块表面」**（用户判词 2026-10-12「可以无限放大」的落地）：
     指针（偏离画布中心 +220/−140 px）下先 `__cdutPick` 取到表面点 P，滚轮推近后**在同一位像素
     再取一次** ⇒ 两点位移 ≤ 1 mm（P 必须仍钉在指针下），且 LOOK 必须**朝 P 靠近**。
     ★ 不变量：P 的屏幕位置只由 (P−LOOK) 在相机右/上轴的分量决定、尺度 ∝ 1/radius
     ⇒ 要 P 不动需 LOOK 同步朝 P 走。★ 本条**必须**用射线取点而不是靶平面：靶平面没有
     「模型在那儿」这个概念（见下）。
  I. **指针在模型外 ⇒ 只缩不挪**（本条的病灶来自实测）：指针指到**打不到模型**的像素上时，
     `__cdutPick` 必须返回 null，滚轮**只改 radius、LOOK 一位不动**（≤1e-9）。
     ★ 这条针对的正是**靶平面口径**的实测缺陷：_scratch/probe_zoom_cursor.py 用差分尺量到
     指针在 (+360,−60) 推近 ⇒ 相机朝空处飞、画面里模型占 **0.00%**。
  J. **拾取限流真的生效**（真交付件 37 万面、无 BVH ⇒ 一次命中求交要 ~25 ms，量见
     过程/_scratch/probe_pick.py：命中 min/avg/max = 2.4/22.3/29.0 ms，落空 0.1 ms）。
     ★ 判据**不看墙钟**（机器忙闲会把它变噪声），只看页面自报的求交**次数** `__cdutPickN`：
     一次拨动（同一像素连发 30 个滚轮事件）只许算 **≤2** 次；指针挪 >4 px、或静置 >150 ms
     之后必须**再算**（否则限流就变成「永远只算第一次」）。常数从 `__cdutPickThrottle` 读。

★ 正对照（必须触发，不响则本判据无分辨力）：
  E2/F2. 把**旧式实现**（`radius *= 1 + Math.sign(deltaY)*0.09`）喂给同一条判据：
         ⇒ E 必须**变红**（80 与 160 得同一因子 1.09 = 对滚动量全盲）、
            F 必须**变红**（+9% 再 −9% ⇒ 0.9919 ≠ 1）。
         ★ 这是「已知坏的刺激」：它就是本仓**改之前**真正在跑的那一行。
  H2.    **「只缩不挪 LOOK」**（= 靶平面口径的旧滚轮）下的对照量：指针下那点会滑走
         `|偏移px| × (r₀/r₁ − 1)` 像素（纯解析，不依赖页面）。本条要求它 **> 30 px** ——
         否则指针偏移选得太靠中心，H 分不开「朝指针缩」与「朝楼心缩」。★ 这一条正是
         「放开 rMin 而不改滚轮 ⇒ 只会往楼心钻、钻进黑屋子」的可判形式（量见
         `_scratch/probe_zoom_floor2.py`：radius 0.6~4.6 m 时模型占画面 99.3% 但亮度仅 23/255）。
  I2.    **靶平面口径在「指针在模型外」时会挪 LOOK 多少**（同为纯解析）：指针偏移 260 px、
         因子 0.774 ⇒ 旧口径下 LOOK 会挪 ≥1 m。⇒ 判据若把 I 写成「LOOK 不动 = 通过」，
         必须先证「旧口径**会**动」，否则 I 条把「朝空处飞」与「原地缩」**分不开**（铁律 137）。
  J2.    **计数器必须有分辨力**：连调 `__cdutPick` 30 次 ⇒ 计数必须 **+30**。
         ★ 不这么量的话，「一次拨动只算 ≤2 次」可能只是因为**计数器根本不会涨**而恒绿
         （铁律 137：判据名单漏掉主体则永远绿）。这条是**实测**，不是算式。
  ★ E2/F2/J2 是**实跑**；H2/I2 是按页面读数算出的**解析对照**（I2 的经验依据在画面侧：
    `_scratch/probe_zoom_cursor.py` 量到旧口径在 (+360,−60) 处模型占画面 **0.00%**）。
    **五条对照都必须按预期**，否则本判据没有分辨力。

★ 盲区（必须声明，盲区内的判词不算证据）：
  ① 探针读的是**相机状态**，不是**画面**。⇒「画面看起来对不对」本条**不判**
     （WebGL 画布读回是空的，见 memory；那要截屏量，另一条）。
  ② 事件是**合成派发**（`dispatchEvent`），不是真人鼠标 ⇒ `setPointerCapture` 的真实路径、
     浏览器默认行为、以及「手感」（多快算快、惯性曲线顺不顺）本条**全不量**。
  ③ 只量**鼠标钮位**；触摸**双指捏合**不量（需多点触控模拟）。⇒ 本条对手机端**全盲**。
  ④ 判据**跑不起来**（页面无探针）与**判红**（跑了但不达标）是两回事，分别用 **rc=4** 与 **rc=1**
     报出，不许并成一个数（铁律：崩溃的 rc 与「没量到」同形）。
  ⑤ 本判据依赖 `demo/index.html` 里的哨位名 `__cdutView` / `__cdutWheelK` / `__cdutPick` /
     `__cdutPickN` / `__cdutPickThrottle`；改名即失效（rc=4 报出）。
  ⑥ H 条的容差是 **1 mm**，不是解析 0：缩放后**重打的那条射线**可能落在相邻三角面上
     （射线按构造过 P，但首次命中未必是同一片），点位差一点。⇒ 「≤1 mm」是**同一块表面
     上**的判词；若射线途中被别的构件挡住（相机挪近后新出现的遮挡），本条会判红而**不是**
     报「量不到」—— 本判据分不开这两种，**这是 H 条的盲区**。
  ⑦ J 条只量**次数**，不量**墙钟**：限流把 25 ms×N 压成 25 ms×1 这件事本身没被直接量到
     （机器忙闲会把墙钟变成噪声）。⇒ 「不卡顿」本判据**不判**，只判「求交次数被压住了」。
  ⑧ 拾取耗时只在本机这台机器的这一个模型上量过（37 万面、无 BVH）。换模型/换机器要重新量。

用法: python gates/J-09.1.1-viewer.py [--json gates/_out/J-09.1.1-viewer.json]
"""
import sys
import os
import json
import atexit
import threading
import argparse
import functools
import http.server

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WHEEL_K_EXPECT = 0.0016          # 与页面 `WHEEL_K` 同值；页面另通过 `__cdutWheelK` 自报，两者须一致
PAN_PX = 120.0                   # A 条已知刺激（横向像素）
PAN_PX_Y = 90.0                  # B 条已知刺激（纵向像素）
TOL_REL = 1e-6                   # 读数容差（相对）
RC_OK, RC_FAIL, RC_NOGAUGE = 0, 1, 4

PROBE_JS = r"""
async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 100; i++) {
    const v = window.__cdutView && window.__cdutView();
    if (v && v.home) break;
    await wait(250);
  }
  if (typeof window.__cdutView !== 'function' || typeof window.__cdutWheelK !== 'number')
    return { gauge: 'absent' };
  if (typeof window.__cdutPick !== 'function' || typeof window.__cdutPickN !== 'function' ||
      typeof window.__cdutPickThrottle !== 'object')
    return { gauge: 'absent_nopick' };        // ★旧版 demo（无拾取探针）落这里 ⇒ rc=4 而不是判红
  const cv = document.getElementById('gl');
  const r = cv.getBoundingClientRect();
  const cx = Math.round(r.left + r.width / 2), cy = Math.round(r.top + r.height / 2);
  const mk = (t, o) => new PointerEvent(t, Object.assign({
    bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse',
    clientX: cx, clientY: cy, isPrimary: true }, o));
  const dragBy = async (button, dx, dy) => {
    const btn = button === 0 ? 1 : (button === 1 ? 4 : 2);
    cv.dispatchEvent(mk('pointerdown', { button, buttons: btn }));
    cv.dispatchEvent(mk('pointermove', { button: -1, buttons: btn, clientX: cx + dx, clientY: cy + dy }));
    cv.dispatchEvent(mk('pointerup', { button, buttons: 0 }));
    await wait(40);
  };
  const wheelAt = async (dy, ox = 0, oy = 0) => {          // ox/oy = 相对画布中心的像素偏移
    cv.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: dy, deltaMode: 0,
      clientX: Math.round(r.left + r.width / 2 + ox), clientY: Math.round(r.top + r.height / 2 + oy) }));
    await wait(30);
  };
  const reset = async () => { cv.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); await wait(30); };
  const view = () => window.__cdutView();
  const d3 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  const fov = 42;

  const a0 = view(); await dragBy(1, __PAN_PX__, 0); const a1 = view();
  const b0 = view(); await dragBy(2, 0, __PAN_PX_Y__); const b1 = view();
  const c0 = view(); await dragBy(0, 100, 0);    const c1 = view();
  const z0 = view(); await dragBy(1, 0, 0);      const z1 = view();

  await reset(); const r0 = view().radius;
  await reset(); await wheelAt(80);  const r80 = view().radius;
  await reset(); await wheelAt(160); const r160 = view().radius;
  await reset(); await wheelAt(100); await wheelAt(-100); const rBack = view().radius;

  // G：先 pan 走 + 转走，再双击 ⇒ 必须回到 home
  await reset();
  await dragBy(1, 140, 70); await dragBy(0, 60, 20);
  const gAway = view();
  await reset();
  const gBack = view();

  // H 滚轮**朝指针**缩放：指针下**射线打到的那块表面**必须钉住不动
  // ★ 指针位置由探针探出来（不能凭猜）：拿一个**打不到模型**的点当锚点，
  //   量到的是「页面没动」，不是「锚点没挪」（2026-10-12 实测踩过一次）。
  // ★★ 2026-10-14 **重探**（旧记录已过期，见下），两个刺激都是重探值、不是沿用旧值。
  //   为什么过期：那天件被搬离了画面中心（查看器一个搬件 bug，已修），画面下方空着，
  //   所以「(+300,+160)/(0,-260) 打不到模型」成立；件归位后**它们全打在模型上**
  //   （(0,-260) 打在 12 层件的屋面 y=39.72 上）⇒ 旧值当 I 的刺激会把那条逼成「没量到」。
  // ★ 量具：_scratch/probe_pick.py（逐点打射线）＋ 过程/_scratch/_probe_grid.py（网格扫描）。
  //   ★★ 顺手量出**画布只有 810×845**，不是视口 1280×900 ⇒ 偏移 |dx|>405 / |dy|>422
  //   就**出了画布**，那样的「空」是**指到屏幕外**，不是指着空处 ⇒ 选点必须留在画布内
  //   （2026-10-14 实测：(±600,∓420) ndc=±1.48、(0,-430) ndc=-1.02，全是这种假空）。
  // ★ 重探结果（开场帧 · 画布 810×845 · 网格步长 45 px）：模型占画面中部，
  //   **下方偏右**是一大片空区。(-320,+140) 仍在模型上 ⇒ H 的锚点不用改。
  const HX = -320, HY = 140;
  await reset(); const h0 = view();
  const Hcx = Math.round(r.left + r.width / 2 + HX), Hcy = Math.round(r.top + r.height / 2 + HY);
  const ax = Hcx - (r.left + r.width / 2), ay = Hcy - (r.top + r.height / 2);
  const q0 = window.__cdutPick(Hcx, Hcy);
  let H = { picked: !!q0.point, pickMs: q0.ms, dxPix: ax, dyPix: ay };
  if (q0.point){
    const P0 = q0.point;
    cv.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -160, deltaMode: 0,
      clientX: Hcx, clientY: Hcy }));
    await wait(30);
    const h1 = view();
    const q1 = window.__cdutPick(Hcx, Hcy);       // 推近后**同一位像素**再打一次
    const rf = h1.radius / h0.radius;
    H = Object.assign(H, {
      anchorMoved: q1.point ? d3(P0, q1.point) : null,
      radiusFrac: rf, lookMoved: d3(h0.look, h1.look),
      dist0: d3(h0.look, P0), dist1: d3(h1.look, P0),
      // 解析对照（H2）：LOOK 不动时，指针下那点按 (P−LOOK)/radius ∝ 走 ⇒ 偏移乘 r₀/r₁
      frozenPix: Math.hypot(ax, ay) * (h0.radius / h1.radius - 1),
    });
  }

  // I 指针**打不到模型**（模型外）⇒ 只缩不挪
  // ★★ 2026-10-14 换的刺激：原值 (0,-260) 是**建在旧取景上的**（件当时被顶高、画面下方空着），
  //   搬件 bug 修好、件归位后那个点**打在 12 层件的屋面上**（y=39.72）⇒ 判据自己报「没量到」。
  //   现值由 过程/_scratch/_probe_grid.py 在**开场帧、画布 810×845 内**（|ndc|<1）扫网格得来：
  //   ndc=(+0.667,-0.639)，离最近的模型命中 ≥2 格（90 px）、离画布右边 135 px、离底边 152 px。
  //   ⇒ 它是「指着空处」，不是「指到屏幕外」；判词一个字没动，只换了刺激。
  const OX = 270, OY = -270;
  await reset(); const o0 = view();
  const Ocx = Math.round(r.left + r.width / 2 + OX), Ocy = Math.round(r.top + r.height / 2 + OY);
  const oax = Ocx - (r.left + r.width / 2), oay = Ocy - (r.top + r.height / 2);
  const qo = window.__cdutPick(Ocx, Ocy);
  cv.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -160, deltaMode: 0,
    clientX: Ocx, clientY: Ocy }));
  await wait(30);
  const o1 = view();
  const ko = 2 * o0.radius * Math.tan(fov * Math.PI / 360) / cv.clientHeight;
  const I = { picked: !!qo.point, pickMs: qo.ms, dxPix: oax, dyPix: oay,
              lookMoved: d3(o0.look, o1.look), radiusFrac: o1.radius / o0.radius,
              // 解析对照（I2）：靶平面口径在此处**必定**挪 LOOK，量 = |偏移| · |1 − r₂/r₁|
              planeWouldMove: Math.hypot(oax, oay) * ko * Math.abs(1 - o1.radius / o0.radius) };

  // J 拾取限流：一次拨动只许算几次（看**次数**，不看墙钟）
  const th = window.__cdutPickThrottle;
  await reset(); const j0 = view();
  const Jx = Math.round(r.left + r.width / 2 + 40), Jy = Math.round(r.top + r.height / 2 + 30);
  const nBefore = window.__cdutPickN();
  for (let i = 0; i < 30; i++)                    // 同一像素连发 30 个事件（同一 JS 轮次，时间几乎不走）
    cv.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -8, deltaMode: 0,
      clientX: Jx, clientY: Jy }));
  const nBurst = window.__cdutPickN() - nBefore;
  await wait(th.ms + 120);                        // 静置超时后同像素再发一个 ⇒ 必须重算
  const nA = window.__cdutPickN();
  cv.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -8, deltaMode: 0,
    clientX: Jx, clientY: Jy }));
  const nIdle = window.__cdutPickN() - nA;
  cv.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -8, deltaMode: 0,
    clientX: Jx + th.px + 10, clientY: Jy}));     // 指针挪过阈值 ⇒ 必须重算
  const nMoved = window.__cdutPickN() - nA - nIdle;
  const nC = window.__cdutPickN();
  for (let i = 0; i < 30; i++) window.__cdutPick(Jx, Jy);   // 对照（J2）：计数器本身有没有分辨力
  const nCtl = window.__cdutPickN() - nC;
  const jLookMoved = d3(j0.look, view().look);     // 拨动**真的**缩了（否则「只算 1 次」是没动，不是限流）

  const K = window.__cdutWheelK;
  const k = 2 * a0.radius * Math.tan(fov * Math.PI / 360) / cv.clientHeight;
  return {
    gauge: 'ok', K, viewportH: cv.clientHeight, fov, throttleMs: th.ms, throttlePx: th.px,
    A: { moved: d3(a0.look, a1.look), expect: __PAN_PX__ * k,
         thetaSame: a0.theta === a1.theta, radiusSame: a0.radius === a1.radius },
    B: { moved: d3(b0.look, b1.look), expect: __PAN_PX_Y__ * k, thetaSame: b0.theta === b1.theta },
    C: { thetaDelta: c1.theta - c0.theta, lookMoved: d3(c0.look, c1.look) },
    D: { lookMoved: d3(z0.look, z1.look) },
    E: { f80: r80 / r0, f160: r160 / r0,
         exp80: Math.exp(80 * K), exp160: Math.exp(160 * K) },
    F: { relErr: Math.abs(rBack / r0 - 1) },
    G: { awayMoved: d3(gAway.look, gBack.look) > 1e-9 || Math.abs(gAway.theta - gBack.theta) > 1e-9,
         lookSame: d3(gBack.look, gBack.home.look),
         thetaSame: gBack.theta === gBack.home.theta,
         phiSame: gBack.phi === gBack.home.phi,
         radiusSame: gBack.radius === gBack.home.radius },
    H: H,
    I: I,
    J: { burst: nBurst, idle: nIdle, moved: nMoved, ctl: nCtl, events: 30, lookMoved: jLookMoved },
    home: a0.home,
  };
}
"""


def serve(directory):
    """起一个**本判据自己的** http 服务（不依赖外部常驻服务，判据才能独立重跑）。"""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):        # 不把 GET 访问日志灌进判据的原始输出
            pass

    handler = functools.partial(Quiet, directory=directory)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    atexit.register(srv.shutdown)
    return srv.server_address[1]


def controls():
    """E2/F2 正对照：把**旧式规则**（本仓改之前真正在跑的那一行）喂给同一条判据。
    ★ 不是模拟页面，是把**已知坏的实现**在同一套算式下跑出来 —— 判据必须对它变红。"""
    old = lambda ds: functools.reduce(lambda a, d: a * (1 + (1 if d > 0 else (-1 if d < 0 else 0)) * 0.09), ds, 1.0)
    new = lambda ds: functools.reduce(
        lambda a, d: a * pow(2.718281828459045, max(-160.0, min(160.0, d)) * WHEEL_K_EXPECT), ds, 1.0)
    return {"old_f80": old([80]), "old_f160": old([160]), "old_rev": old([100, -100]),
            "new_rev": new([100, -100])}


class _Tee:
    """把本判据的全部原始输出同时留一份（§10.0.5：判据须自存**原始运行输出**，不许只存结论）。"""
    def __init__(self, real):
        self.real, self.buf = real, []

    def write(self, s):
        self.buf.append(s)
        self.real.write(s)
        return len(s)

    def flush(self):
        self.real.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(HERE, "_out", "J-09.1.1-viewer.json"))
    a = ap.parse_args()

    real, tee = sys.stdout, _Tee(sys.stdout)
    sys.stdout = tee
    try:
        return _run(a)
    finally:
        sys.stdout = real
        if a.json:
            os.makedirs(os.path.dirname(a.json), exist_ok=True)
            run = os.path.splitext(a.json)[0] + ".run.txt"
            with open(run, "w", encoding="utf-8", newline="\n") as f:
                f.write("".join(tee.buf))


def _run(a):
    fails, unmeasured = [], []
    print("判据 J-09.1.1  查看器手势（案 §9.1.1）")
    port = serve(ROOT)
    url = "http://127.0.0.1:%d/demo/index.html?gate=J-09.1.1" % port
    print("  起服务 %s（本判据自己的，随进程退出）" % url)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        try:
            pg = br.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(url, wait_until="load")
            m = pg.evaluate(PROBE_JS.replace("__PAN_PX__", repr(PAN_PX))
                                     .replace("__PAN_PX_Y__", repr(PAN_PX_Y)))
        finally:
            br.close()

    if m.get("gauge") != "ok":
        print("\n  ★ 页面里**没有探针**（`__cdutView`/`__cdutWheelK`）⇒ 本条**跑不起来**（rc=4）——")
        print("    这不是判红，是**量不了**（盲区④/⑤）。旧版 demo（无探针）就落在这里。")
        return RC_NOGAUGE

    K = m["K"]
    if abs(K - WHEEL_K_EXPECT) > 1e-12:
        fails.append("页面自报的 WHEEL_K=%r ≠ 判据期望的 %r ⇒ 常数被改过，后面的期望值作废" % (K, WHEEL_K_EXPECT))
    print("  竖直视口 %d px · fov %d° · 页面上报 WHEEL_K=%r" % (m["viewportH"], m["fov"], K))

    # ---- A/B 平移：命中已知刺激的解析解 ----
    for tag, key in (("A 中键", "A"), ("B 右键", "B")):
        d = m[key]
        rel = abs(d["moved"] - d["expect"]) / d["expect"] if d["expect"] else 9e9
        ok = rel <= TOL_REL and d["thetaSame"]
        print("\n== %s按住拖 = 平移 ==" % tag)
        print("   |ΔLOOK| %.4f m / 期望 %.4f m（相对误差 %.2e）· theta 未变 %s ⇒ %s"
              % (d["moved"], d["expect"], rel, d["thetaSame"], "✓" if ok else "✗"))
        if not ok:
            fails.append("%s 平移：位移 %.4f ≠ 期望 %.4f（θ 未变=%s）" % (tag, d["moved"], d["expect"], d["thetaSame"]))
    if not m["A"]["radiusSame"]:
        fails.append("A 平移把 radius 也改了（平移不该改距离）")

    # ---- C 左键旋转，且 LOOK 不动 ----
    c = m["C"]
    ok_c = abs(c["thetaDelta"]) > 1e-6 and c["lookMoved"] <= 1e-9
    print("\n== C 左键拖 = 旋转 ==")
    print("   Δtheta %+.4f rad（必须非 0）· |ΔLOOK| %.2e m（必须为 0）⇒ %s"
          % (c["thetaDelta"], c["lookMoved"], "✓" if ok_c else "✗"))
    if not ok_c:
        fails.append("C 左键：Δtheta=%.6f / |ΔLOOK|=%.2e ⇒ 平移与旋转没分开" % (c["thetaDelta"], c["lookMoved"]))

    # ---- D 零位移负对照 ----
    z = m["D"]
    print("\n== D 负对照：中键零位移 ⇒ LOOK 必须不动 ==")
    print("   |ΔLOOK| %.2e m ⇒ %s" % (z["lookMoved"], "✓" if z["lookMoved"] <= 1e-9 else "✗"))
    if z["lookMoved"] > 1e-9:
        fails.append("D 零位移中键竟移动了 LOOK %.2e m ⇒ A 条读数来源不明" % z["lookMoved"])

    # ---- E 按滚动量 ----
    e = m["E"]
    sep = abs(e["f80"] - e["f160"]) > 1e-3
    hit = (abs(e["f80"] / e["exp80"] - 1) <= TOL_REL) and (abs(e["f160"] / e["exp160"] - 1) <= TOL_REL)
    print("\n== E 滚轮按**滚动量**（80 与 160 的因子必须不同）==")
    print("   实测 f80=%.6f f160=%.6f（差 %.4f，必须 >0）· 期望 exp(80K)=%.6f exp(160K)=%.6f ⇒ %s"
          % (e["f80"], e["f160"], abs(e["f80"] - e["f160"]), e["exp80"], e["exp160"],
             "✓" if (sep and hit) else "✗"))
    if not sep:
        fails.append("E 滚动量 80 与 160 得到同一因子（%.6f）⇒ 对滚动幅度全盲" % e["f80"])
    if not hit:
        fails.append("E 实测因子与 exp(d·K) 不符（f80=%.6f/exp=%.6f）" % (e["f80"], e["exp80"]))

    # ---- F 可逆 ----
    f = m["F"]
    print("\n== F 滚轮可逆（+100 再 −100 ⇒ 回原位）==")
    print("   相对误差 %.2e ⇒ %s" % (f["relErr"], "✓" if f["relErr"] <= 1e-12 else "✗"))
    if f["relErr"] > 1e-12:
        fails.append("F 滚轮不可逆（相对误差 %.2e）" % f["relErr"])

    # ---- G 复位到开场那一帧 ----
    g = m["G"]
    ok_g = g["awayMoved"] and g["lookSame"] <= 1e-12 and g["thetaSame"] and g["phiSame"] and g["radiusSame"]
    print("\n== G 双击复位 = 开场那一帧（pan/转 走后再双击）==")
    print("   曾离开 %s · 复位后 |ΔLOOK| %.2e · theta 同 %s · phi 同 %s · radius 同 %s ⇒ %s"
          % (g["awayMoved"], g["lookSame"], g["thetaSame"], g["phiSame"], g["radiusSame"],
             "✓" if ok_g else "✗"))
    if not ok_g:
        fails.append("G 双击未回到开场帧（look=%.2e θ=%s φ=%s r=%s）"
                     % (g["lookSame"], g["thetaSame"], g["phiSame"], g["radiusSame"]))

    # ---- H 滚轮朝指针缩放：指针下的**表面点**钉住不动 ----
    h = m["H"]
    ANCHOR_TOL_M = 1e-3            # 1 mm：不是解析 0（重打的射线可能落到相邻面上），但远低于可见尺度
    CTRL_MIN_PX = 30.0             # 对照（LOOK 不动）必须让那点滑走 ≥30 px，否则 H 没分辨力
    if not h.get("picked"):
        print("\n  ★ H 条**没量到**：探针选的像素下**打不到模型**（`__cdutPick` 返回 null）——")
        print("    这是**尺子的错**（刺激选错），不是页面判红。像素要用 过程/_scratch/probe_pick.py 先探明。")
        unmeasured.append("H 的刺激像素落在模型外")
    else:
        ok_h = (h["anchorMoved"] is not None and h["anchorMoved"] <= ANCHOR_TOL_M
                and h["frozenPix"] > CTRL_MIN_PX and h["lookMoved"] > 1e-3 and h["dist1"] < h["dist0"])
        print("\n== H 滚轮朝**指针**缩放（指针下的表面点须钉住；锚点=射线命中点）==")
        print("   指针偏移 (%.1f, %.1f) px · 首次求交 %.1f ms · 半径比 %.6f（=exp(−160K)）"
              % (h["dxPix"], h["dyPix"], h["pickMs"], h["radiusFrac"]))
        print("   推近后指针下那点挪了 %.3e m（必须 ≤ %.0e m）· LOOK 挪了 %.4f m（必须 > 0）"
              % (h["anchorMoved"], ANCHOR_TOL_M, h["lookMoved"]))
        print("   到锚点距离 %.4f → %.4f m（必须**变小**=真的朝指针靠）" % (h["dist0"], h["dist1"]))
        print("   对照 H2（解析）：若 LOOK 不动，那点会滑走 %.2f px（必须 > %.0f）⇒ %s"
              % (h["frozenPix"], CTRL_MIN_PX, "✓" if ok_h else "✗"))
        if h["anchorMoved"] is None or h["anchorMoved"] > ANCHOR_TOL_M:
            fails.append("H 指针下的表面点在缩放后挪了 %s m ⇒ 滚轮不是朝指针缩的" % h["anchorMoved"])
        if h["frozenPix"] <= CTRL_MIN_PX:
            fails.append("H 的对照量太小（%.2f px）⇒ 指针偏移太靠中心，H 条没有分辨力" % h["frozenPix"])
        if h["lookMoved"] <= 1e-3:
            fails.append("H LOOK 一位没动（%.3e m）⇒ 这是「只缩不挪」，不是朝指针缩" % h["lookMoved"])
        if h["dist1"] >= h["dist0"]:
            fails.append("H 相机没朝锚点靠近（%.4f → %.4f m）" % (h["dist0"], h["dist1"]))

    # ---- I 指针在模型外：只缩不挪 ----
    i = m["I"]
    if i["picked"]:
        print("\n  ★ I 条**没量到**：探针选的像素 (%.0f, %.0f) px 竟**打到了**模型（求交 %.1f ms）——"
              % (i["dxPix"], i["dyPix"], i["pickMs"]))
        print("    刺激选错（尺子的错），不是页面判红；换像素要先用 过程/_scratch/probe_pick.py 探。")
        unmeasured.append("I 的刺激像素落在模型上")
    else:
        ok_i = i["lookMoved"] <= 1e-9 and i["radiusFrac"] < 1.0 and i["planeWouldMove"] > 1.0
        print("\n== I 指针**在模型外** ⇒ 只缩不挪（不许朝空处飞）==")
        print("   该像素求交落空 %.1f ms · 半径比 %.6f（必须 < 1 = 确实缩了）· LOOK 挪了 %.2e m（必须 == 0）"
              % (i["pickMs"], i["radiusFrac"], i["lookMoved"]))
        print("   对照 I2（解析）：靶平面口径在此处**会**把 LOOK 挪走 %.3f m（必须 > 1.0 m，否则 I 没分辨力）⇒ %s"
              % (i["planeWouldMove"], "✓" if ok_i else "✗"))
        if i["lookMoved"] > 1e-9:
            fails.append("I 指针在模型外时 LOOK 竟挪了 %.3e m ⇒ 会朝空处飞" % i["lookMoved"])
        if i["radiusFrac"] >= 1.0:
            fails.append("I 滚轮在模型外**没缩放**（半径比 %.6f）⇒ 这条量不到东西" % i["radiusFrac"])
        if i["planeWouldMove"] <= 1.0:
            fails.append("I 的对照量太小（%.3f m）⇒ 指针太靠中心，I 条分不开「朝空处飞」与「原地缩」"
                         % i["planeWouldMove"])

    # ---- J 拾取限流（看**次数**，不看墙钟）----
    j = m["J"]
    ok_j = (j["burst"] <= 2 and j["ctl"] == 30 and j["idle"] >= 1 and j["moved"] >= 1
            and j["lookMoved"] > 1e-9)
    print("\n== J 拾取限流（同一像素连发 %d 个滚轮事件）==" % j["events"])
    print("   一次拨动求交 **%d** 次（必须 ≤ 2）· 静置 %d ms 后同像素 +%d 次（必须 ≥ 1）· "
          "指针挪 %d px 后 +%d 次（必须 ≥ 1）· 拨动确实缩了 %.4f m"
          % (j["burst"], m["throttleMs"], j["idle"], m["throttlePx"] + 10, j["moved"], j["lookMoved"]))
    print("   对照 J2：连调探针 30 次 ⇒ 计数 +%d（必须 == 30，证明计数器**涨得动**）⇒ %s"
          % (j["ctl"], "✓" if ok_j else "✗"))
    if j["burst"] > 2:
        fails.append("J 一次拨动求交 %d 次 ⇒ 限流没生效（每次滚轮都在打射线）" % j["burst"])
    if j["ctl"] != 30:
        fails.append("J 对照失效：连调 30 次只记了 %d 次 ⇒ 计数器涨不动，「≤2」的通过是假的" % j["ctl"])
    if j["idle"] < 1:
        fails.append("J 静置超时后**没重算** ⇒ 限流退化成「只算第一次」")
    if j["moved"] < 1:
        fails.append("J 指针挪过阈值后**没重算** ⇒ 锚点会一直钉在旧位置")
    if j["lookMoved"] <= 1e-9:
        fails.append("J 的拨动根本没动相机 ⇒ 求交次数少不是限流，是事件没用")

    # ---- 正对照：已知坏的实现必须被同一条判据拒掉 ----
    ct = controls()
    e2_sep = abs(ct["old_f80"] - ct["old_f160"]) > 1e-3        # 应为 **False**（旧式两值相同）
    f2_rev = abs(ct["old_rev"] - 1.0) <= 1e-12                 # 应为 **False**（0.9919 ≠ 1）
    print("\n== 正对照（把**改之前真正在跑的那一行**喂给同一条判据）==")
    print("   E2 旧式 f80=%.6f f160=%.6f ⇒ 能把量分开吗？%s（判据必须说「不能」）"
          % (ct["old_f80"], ct["old_f160"], e2_sep))
    print("   F2 旧式 +100−100 = %.6f ⇒ 可逆吗？%s（判据必须说「不可逆」，新式 %.6f）"
          % (ct["old_rev"], f2_rev, ct["new_rev"]))
    if e2_sep:
        fails.append("正对照 E2 失效：旧式实现对滚动量竟可分 ⇒ E 条没有分辨力")
    if f2_rev:
        fails.append("正对照 F2 失效：旧式实现竟然可逆 ⇒ F 条没有分辨力")
    print("   H2 对照（解析）：LOOK 不动时指针下那点滑走 %.2f px（判据须 > %.0f px）⇒ %s"
          % (h.get("frozenPix", float("nan")), CTRL_MIN_PX,
             "判据说「滑走了」✓" if h.get("frozenPix", 0) > CTRL_MIN_PX else "✗ 滑不动 ⇒ H 没分辨力"))
    print("   I2 对照（解析）：靶平面口径在模型外会把 LOOK 挪走 %.3f m（判据须 > 1.0 m）⇒ %s"
          % (i["planeWouldMove"], "判据说「会挪」✓" if i["planeWouldMove"] > 1.0 else "✗ ⇒ I 没分辨力"))
    print("   J2 对照（实测）：连调探针 30 次 ⇒ 计数 +%d（须 == 30）⇒ %s"
          % (j["ctl"], "计数器涨得动 ✓" if j["ctl"] == 30 else "✗ 计数器不涨 ⇒ J 的通过是假的"))
    ok_ct = (not e2_sep and not f2_rev and h.get("frozenPix", 0) > CTRL_MIN_PX
             and i["planeWouldMove"] > 1.0 and j["ctl"] == 30)
    print("   ⇒ 五条对照 %s" % ("**全部按预期** ✓ 本判据有分辨力" if ok_ct else "✗ 有对照没响 ⇒ 本判据无分辨力"))

    print("\n===== 判词 =====")
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
        rc = RC_FAIL
    elif unmeasured:
        print("  NO-GAUGE  rc=4   本判据**这条没量到**（不是判红）:", unmeasured)
        rc = RC_NOGAUGE
    else:
        print("  PASS  rc=0   中键/右键平移命中解析解（%.4f m）· 左键只转不移 · 滚轮按量且可逆 · "
              "朝指针缩放钉住表面点（对照滑走 %.1f px）· 模型外只缩不挪 · 限流 1 拨 1 算 · 双击回开场帧"
              % (m["A"]["expect"], m["H"]["frozenPix"]))
        rc = RC_OK
    print("  ★ 盲区：只量**鼠标手势的相机状态与求交次数**；画面观感、合成事件下的指针捕获、触摸双指、"
          "手感阈值、限流省下的墙钟 **全部不量**（盲区①~③⑦⑧）。量不到(rc=4) 与 判红(rc=1) 分开报（盲区④）。")
    if a.json:
        os.makedirs(os.path.dirname(a.json), exist_ok=True)
        json.dump({"pass": rc == RC_OK, "rc": rc, "measured": m, "controls": ct,
                   "fails": fails, "unmeasured": unmeasured},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())

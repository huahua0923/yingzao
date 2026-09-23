# -*- coding: utf-8 -*-
"""出图脚本的**单一事实源**：轮廓面积、数据快照戳、页面新鲜度自检。

为什么单独一个模块（三条口径原先各写各的、已经开始漂移）：
  1. **面积**：`_dxf_cad_render` / `_dxf_png_batch` / `_dxf_compare_render` 三处都
     写成 `(x1-x0)*(y1-y0)` —— 那是**包围盒**面积，不是楼层面积。c006 是 L 形四翼，
     包围盒 10805 ㎡ 而轮廓真实 5698.7 ㎡（**虚高 90%**）。caption 上写"面积"却是包围盒，
     正是铁律 17「量什么就写什么」禁的那类错。
  2. **楼层号显示**：铁律 5 = 内部 0 基、显示 1 基。`_dxf_png_batch` 的 gallery 写的是
     `F{F}`（0 基），与另两页并存两种口径。
  3. **新鲜度**：gallery 的计数是**烘焙进 HTML 的快照**，只有重跑出图脚本才更新；而
     floors 是天天在改的 —— 实测 c006 第 7 层 caption 写「门 86 / 井 2 / 房 28」，
     而 floor6.json 已是「33 / 8 / 6」（07:32 出页 / 11:43 改数据）。同一个对照页上
     图是新的、字是旧的，而这一页的用途恰恰是"对照找识别问题"。
     ⇒ `freshness_script()` 让页面**在浏览器里按当前 floor JSON 现算**并打警告；
     拿不到（file:// 直接打开）就安静回退到烘焙值 + 快照戳，不装。

所有函数都是纯函数 / 只读，不写任何文件。
"""
import os
import time


# ---- 楼名 / 文件名 ----

def cn_from_dxf(p):
    """从源 DXF 文件名抽中文楼名：`C025-第一教学楼.dxf` → `第一教学楼`。

    ★ 原先 `_dxf_cad_render.py` 与 `_dxf_compare_render.py` **各写了一份**（正则一字不差、
    只差一句 docstring），2026-09-14 收到这里 —— 两份拷贝的下场就是哪天有人只改一份。
    """
    import re
    base = os.path.splitext(os.path.basename(p.dxf))[0]
    return re.sub(r"^[A-Za-z]+\d+[-_ ]*", "", base).strip(" -_") or base


# ---- 几何：轮廓面积（shoelace，纯 Python，不引新依赖） ----

def ring_area_m2(ring):
    """单个闭合环的面积（㎡）。自交环按代数面积算 —— 与 shapely 的口径不同，
    但这里只用它做**页面上的粗数**，判据一律以门禁脚本为准（别拿它当判据）。"""
    n = len(ring or [])
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x0, y0 = float(ring[i][0]), float(ring[i][1])
        x1, y1 = float(ring[(i + 1) % n][0]), float(ring[(i + 1) % n][1])
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def outline_area_m2(fl):
    """楼层文件里**轮廓真实面积**（㎡，1 位小数）。outline 缺失时返回 None。"""
    ol = (fl or {}).get("outline")
    if not ol:
        return None
    return round(ring_area_m2(ol), 1)


def floor_counts(fl):
    """页面要印的四个数 —— 口径集中在这里，三个 gallery 不再各写一份。"""
    fl = fl or {}
    return {
        "doors": len(fl.get("doors") or []),
        "stairs": len(fl.get("stairwells") or []),
        "rooms": len(fl.get("rooms") or []),
        "area": outline_area_m2(fl),
    }


# ---- 数据快照戳 ----

def mtime_str(path):
    """`2026-09-14 11:43`；读写不到就是 `?`（不猜、不装）。"""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
    except OSError:
        return "?"


# ---- 页面：caption 片段 ----

def caption_counts_html(cnt, F, snap=""):
    """caption 的计数段。每个数带 `data-fk`，供 freshness_script 在浏览器里改写。

    `F` = 内部楼层号（0 基，只用来指出数据来源文件名）；显示一律 `F+1`（铁律 5）。
    """
    cnt = cnt or {}
    area = cnt.get("area")
    area_txt = "?" if area is None else ("%g" % area)
    snap_html = ("<span class=snap>　数据快照 floor%d.json @ %s</span>" % (F, snap)
                 ) if snap else ""
    return ('　门 <b data-fk="doors">%d</b>'
            ' · 楼梯井 <b data-fk="stairs">%d</b>'
            ' · 房间 <b data-fk="rooms">%d</b>'
            ' · 轮廓面积 <b data-fk="area">%s</b>㎡%s'
            % (cnt.get("doors", "?"), cnt.get("stairs", "?"), cnt.get("rooms", "?"),
               area_txt, snap_html))


# ---- 页面：新鲜度自检（浏览器侧现算） ----

_JS_TMPL = """
<script>
(function () {
  var REL = "__REL__", FLOORS = __FLOORS__;
  function area(r) {
    var s = 0, n = r.length;
    for (var i = 0; i < n; i++) {
      var a = r[i], b = r[(i + 1) % n];
      s += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(s) / 2;
  }
  function refit(fig, d) {
    // ★ 只认**确实存在于 JSON 里**的键：键缺失就不动那个数，
    //   否则"缺键 → 0"会和烘焙值比出一次假过期。
    var vals = {};
    if (d.doors) vals.doors = d.doors.length;
    if (d.stairwells) vals.stairs = d.stairwells.length;
    if (d.rooms) vals.rooms = d.rooms.length;
    if (d.outline && d.outline.length >= 3) vals.area = area(d.outline).toFixed(1);
    var changed = false;
    Object.keys(vals).forEach(function (k) {
      var el = fig.querySelector('[data-fk="' + k + '"]');
      if (!el) return;
      // ★ 按**数值**比，不按字符串比：Python 写 1 位小数、JS 若取整，
      //   "5701.2" != "5701" 会假报过期（本脚本第一版就是这么错的，端到端一测就现形）。
      if (parseFloat(el.textContent) !== parseFloat(vals[k])) changed = true;
      el.textContent = vals[k];
    });
    var snap = fig.querySelector('.snap');
    if (snap) snap.textContent = '　计数已按当前 floor JSON 现算';
    if (changed && !fig.querySelector('.freshwarn')) {
      var s = document.createElement('div');
      s.className = 'freshwarn';
      s.textContent = '⚠ 本页计数原是烘焙快照（图也可能一起过期）：'
        + '请重跑出图脚本刷新这一层的 PNG。';
      fig.appendChild(s);
    }
  }
  FLOORS.forEach(function (F) {
    var fig = document.querySelector('[data-floor="' + F + '"]');
    if (!fig) return;
    fetch(REL + 'floor' + F + '.json', {cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) refit(fig, d); })
      .catch(function () { /* file:// 直接打开 → 安静回退到烘焙值 */ });
  });
})();
</script>
"""


def freshness_script(rel, floors):
    """rel = 从**本页**到 `floors/` 的相对前缀（如 `../floors/`）。"""
    return (_JS_TMPL.replace("__REL__", rel)
                   .replace("__FLOORS__", "[%s]" % ",".join(str(int(f)) for f in floors)))


#: 三个 gallery 共用的样式（快照戳 + 过期警告）。
CSS_EXTRA = (
    ".snap{color:#999;font-size:11px}"
    "b[data-fk]{font-weight:600;color:#111}"
    "div.freshwarn{margin-top:6px;padding:5px 8px;border-radius:4px;"
    "background:#fff4e5;border:1px solid #f0b37e;color:#8a4b08;font-size:12px}"
)

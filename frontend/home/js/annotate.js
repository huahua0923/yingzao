// 左屏「圈问题」图层 —— 在 DWG 图 / 识别叠加图上拖一个框，说这里哪儿不对。
//
// ── 一条坐标系约定，整个文件都围着它转 ──────────────────────────
//
// **框存的是 0..1 的图幅比例，不是像素、不是米。**
//
// 于是有一条不变量，它是本文件唯一需要证明的东西：
//
//     同一个框，在任何屏幕尺寸、任何缩放下，落在图上的**同一个位置**。
//
// 做到它的办法是：覆盖层**每时每刻都精确贴住 `<img>` 的屏幕矩形**
// （`sync()` 干这件事），拖框时把指针位置除以覆盖层自己的宽高。
// 存的是比例 ⇒ 换楼层、换窗口大小、换设备，回显都不用做任何换算。
//
// ★ 为什么不能存像素（这是 N4 那条对照守的东西）：
//   同一栋楼 F1 与 F2 的图幅不同（c001 实测 F0 是 906×453、F1 是 913×590），
//   同一个屏幕点落在两张图上的**比例不同**。存像素的话，两条记录会存下
//   一模一样的数字，而它们指的根本不是同一个地方 —— 屏幕上完全看不出来，
//   直到有人把框叠回图上才发现全错位了。
//
// ★ 为什么不用「相对 .h-sheet 的比例」：.h-sheet 比图大（有内边距、
//   且图是居中放的）。用 sheet 做分母，图一换宽高比，同一个框就漂了。
//   分母**只能是图自己**。
//
// ── 画框只能靠指针 ──────────────────────────────────────────────
//
// 拖框这个动作没有键盘等价物。所以：
//   · **回看**已圈的框走 `<button>`（可 Tab、可 Enter），键盘可达；
//   · **新建**标注需要指针 —— 这一句写在页面上（annotate_hint），不假装可达。
// 把「能 Tab 到的假控件」做出来比不做更坏：它让无障碍检查变绿、让真人更迷惑。

const MIN_RATIO = 0.012;   // 小于这个尺寸的拖动当成「点了一下」，不产生标注
const CLAMP = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

/**
 * @param {HTMLElement} sheet  .h-sheet（左屏那块底板，position:relative）
 * @param {(box: {x0,y0,x1,y1}, px: {w,h}) => void} onCommit 拖完一个够大的框
 * @param {(id: string) => void} onSelect 点/回车选中一个已有的框
 */
export function createAnnotator(sheet, { onCommit, onSelect } = {}) {
  const overlay = document.createElement('div');
  overlay.className = 'ann-layer';
  overlay.setAttribute('role', 'group');
  overlay.setAttribute('aria-label', '问题标注层');

  const band = document.createElement('div');   // 拖拽中的橡皮筋
  band.className = 'ann-band';
  band.setAttribute('aria-hidden', 'true');
  overlay.append(band);

  let img = null;
  let items = [];
  let armed = false;
  let drag = null;
  let selected = null;
  let ro = null;

  // ── 贴住图 ────────────────────────────────────────────────────
  function sync() {
    if (!img || !img.isConnected) return;
    const s = sheet.getBoundingClientRect();
    const r = img.getBoundingClientRect();
    // 图还没解码出来（或这一层没有图）时它的矩形是空的 ——
    // 那时候把覆盖层藏起来，别让它铺满整块底板去接指针。
    if (r.width < 8 || r.height < 8) { overlay.style.display = 'none'; return; }
    overlay.style.display = '';
    overlay.style.left = `${r.left - s.left}px`;
    overlay.style.top = `${r.top - s.top}px`;
    overlay.style.width = `${r.width}px`;
    overlay.style.height = `${r.height}px`;
  }

  /** 把覆盖层交给这张图。传 null 表示「这一层没有图」，图层退场。 */
  function track(imgEl) {
    if (img === imgEl) { sync(); return; }
    detachImg();
    img = imgEl || null;
    items = []; selected = null; drag = null;
    band.style.display = 'none';
    if (!img) { overlay.style.display = 'none'; return; }
    if (!overlay.isConnected) sheet.append(overlay);
    // ★ load 之后再 sync 一次：`track()` 被调用时图往往还没解码，
    //   那一刻的 getBoundingClientRect 是**替换文本的高度**，不是图的高度。
    //   不补这一枪，覆盖层就永远停在那个错的矩形上（本仓记忆：ResizeObserver 必须补一帧）。
    img.addEventListener('load', sync);
    img.addEventListener('error', sync);
    if (typeof ResizeObserver === 'function') {
      ro = new ResizeObserver(sync);
      ro.observe(img);          // 只观察**图**：它是唯一的分母
    }
    sync();
    // ★ 补一帧。`track()` 被调用的那一刻，<img> 常常**还没进文档**
    //   （paintSheet 先建节点、paintStage 才 mount）—— 脱离文档的元素
    //   `getBoundingClientRect()` 全返回 0，上面那一句 sync() 等于白跑。
    //   本仓记忆「ResizeObserver 必须补一帧」说的就是这个形状。
    requestAnimationFrame(sync);
  }

  function detachImg() {
    if (img) { img.removeEventListener('load', sync); img.removeEventListener('error', sync); }
    if (ro) { ro.disconnect(); ro = null; }
    img = null;
  }

  // ── 画已有的框 ────────────────────────────────────────────────
  function render() {
    for (const n of overlay.querySelectorAll('.ann-box')) n.remove();
    for (const it of items) {
      const b = it.box;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ann-box' + (it.id === selected ? ' is-sel' : '');
      btn.dataset.id = it.id;
      btn.style.left = `${b.x0 * 100}%`;
      btn.style.top = `${b.y0 * 100}%`;
      btn.style.width = `${(b.x1 - b.x0) * 100}%`;
      btn.style.height = `${(b.y1 - b.y0) * 100}%`;
      btn.title = `${it.label}${it.note ? ` · ${it.note}` : ''}`;
      btn.setAttribute('aria-label',
        `${it.label}${it.note ? `，备注：${it.note}` : ''}（回车查看）`);
      btn.addEventListener('click', (e) => {
        // 画框模式下点框 = 开始画，不抢；
        // 但画框模式**不禁止**选框：一次点击本来就不产生标注（MIN_RATIO 兜着）。
        e.stopPropagation();
        selected = it.id;
        render();
        onSelect?.(it.id);
      });
      overlay.append(btn);
    }
  }

  // ── 拖 ────────────────────────────────────────────────────────
  const ratioOf = (e) => {
    const r = overlay.getBoundingClientRect();
    return { x: CLAMP((e.clientX - r.left) / r.width), y: CLAMP((e.clientY - r.top) / r.height) };
  };

  overlay.addEventListener('pointerdown', (e) => {
    if (!armed || e.button !== 0) return;
    e.preventDefault();
    overlay.setPointerCapture(e.pointerId);
    const p = ratioOf(e);
    drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
    drawBand();
  });

  overlay.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const p = ratioOf(e);
    drag.x1 = p.x; drag.y1 = p.y;
    drawBand();
  });

  function drawBand() {
    const nx = Math.min(drag.x0, drag.x1), ny = Math.min(drag.y0, drag.y1);
    const w = Math.abs(drag.x1 - drag.x0), h = Math.abs(drag.y1 - drag.y0);
    band.style.display = '';
    band.style.left = `${nx * 100}%`; band.style.top = `${ny * 100}%`;
    band.style.width = `${w * 100}%`; band.style.height = `${h * 100}%`;
  }

  function finish(e) {
    if (!drag) return;
    try { overlay.releasePointerCapture(e.pointerId); } catch { /* 已经放开就算了 */ }
    const d = drag; drag = null;
    band.style.display = 'none';
    const box = {
      x0: Math.min(d.x0, d.x1), y0: Math.min(d.y0, d.y1),
      x1: Math.max(d.x0, d.x1), y1: Math.max(d.y0, d.y1),
    };
    if (box.x1 - box.x0 < MIN_RATIO || box.y1 - box.y0 < MIN_RATIO) return;   // 点了一下，不算
    const r = overlay.getBoundingClientRect();
    onCommit?.(box, { w: Math.round(r.width), h: Math.round(r.height) });
  }
  overlay.addEventListener('pointerup', finish);
  overlay.addEventListener('pointercancel', () => {
    drag = null; band.style.display = 'none';
  });

  const onKey = (e) => {
    if (e.key === 'Escape' && drag) { drag = null; band.style.display = 'none'; }
    if (e.key === 'Escape' && armed) setArmed(false);
  };
  window.addEventListener('keydown', onKey);
  // 窗口尺寸变了图也会变（max-height 是 vh）—— ResizeObserver 观察的是图本身，
  // 它变了会响；但 sheet 先变、图后变的那一帧里，覆盖层会短暂错位。补一个窗口监听。
  window.addEventListener('resize', sync);

  function setArmed(on) {
    armed = !!on;
    overlay.classList.toggle('is-armed', armed);
    if (!armed) { drag = null; band.style.display = 'none'; }
    return armed;
  }

  return {
    track, sync, render, setArmed,
    isArmed: () => armed,
    selected: () => selected,
    select: (id) => { selected = id; render(); },
    setItems(list) { items = list || []; render(); },
    getImg: () => img,
    destroy() {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', sync);
      detachImg();
      overlay.remove();
    },
  };
}

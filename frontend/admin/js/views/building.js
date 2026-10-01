// 「整栋三维」视图 —— 把 `frontend/building.html`（128 KB，成熟可用）**原样托管**进后台。
//
// ★ 这是本轮唯一一个 iframe，理由在计划里就写死了：重写那个页面等于把「能看」换成
//   「我重写过」，风险拉满、收益为零。同源托管 ⇒ 不新开端口、不跨域，
//   也就不需要任何 X-Frame-Options / CSP 妥协。
//
// ★ 地址是**根级** `/building.html`（`backend/api/main.py` 里的一条 FileResponse），
//   不是挂到某个子路径。那个页面内部取数走的是**文档相对**路径
//   （`data/buildings/index.json`、`data/su/<楼>.json`），根级托管它们天然落在既有的
//   `/data/...` 窄挂载上。塞进子路径就得给它加 `<base href="/">`，
//   等于凭空多一个能悄悄坏掉的机关。
//
// ★★ `dispose()` 不是可选项，是这一屏最容易埋雷的地方。
//   每切一次视图就会新建一个 WebGL 上下文；浏览器上限约 16 个，超了会**静默丢掉最老的**，
//   症状是「点来点去三维就白了」—— 不报错、不警告，只在你以为它还好的时候白给你看。
//   所以这里必须把 iframe 明确拆掉：先 `about:blank`，再移出 DOM。
//   两步都要，且顺序是这个顺序：`about:blank` 让子文档的卸载（以及 WebGL 上下文的释放）
//   在它**还活着**的时候跑完；随后 `remove()` 才是销毁浏览上下文。
//   不能指望 `dom.js` 的 `mount()` 顺手收走 —— 那是"反正节点都没了"的赌，
//   而这一屏赌输的代价是几十分钟后才显形的白屏。
//
// ★★ 就绪判据用**页面自己的握手量**，不数 canvas。
//   数 canvas 会假绿：`renderer` 是那个页面的模块级变量，画布在「载入中」的那 13~17 秒里
//   早就挂在 DOM 上了。而 `__gym3d` 上的 `geometryBuilding` 与 `builtToken === buildToken`
//   是 `rebuild()` **末尾**才置位的，并且载入失败那一支**刻意把它们留在未就绪**
//   （见 building.html 里 `loadBuilding` 的 catch：清场景、丢楼层数据、不盖就绪章）。
//   ⇒ 「进程起来了」与「它在干活」必须由能分开这两件事的量来判。
//
// ★ 楼号这一格**刻意不做前端校验**。`sub` 只进 URL 的**查询参数**（下面 encodeURIComponent
//   一道），不做路径拼接；而「这个楼号存不存在」的判据**长在 building.html 里** ——
//   它拿自己那份 `index.json` 比，查无此楼就直说且**不回退**（那里连"回退会冒充成功"
//   这件事都写在注释里了）。在这儿再写一份正则就是同一个判断两份实现，
//   而第二份只会把该放过的拦掉（memory: one-judgement-many-implementations）。
import { el, mount } from '../dom.js';

export const label = '整栋三维';

const PAGE = '/building.html';
const POLL_MS = 400;
// 那个页面自己写着几何要 13~17 秒才到；60 秒是四倍余量。
// 超时**不是**失败判据，是"再也不等了"的判据 —— 它只说"没出几何"，不会替页面认错。
const READY_TIMEOUT_MS = 60000;
// 就绪之后**再补一次**读数，然后才停。
// ★ 为什么不是"看到就绪就停"：徽标上有一项是 `renderer.info.render.triangles`，
//   那是**上一帧**画了多少。而 `builtToken` 是在 `rebuild()` **末尾**才置位的 ——
//   即"几何建好了"，可那一刻屏幕上最后一帧画的还是**空场景**。于是第一次读到就停，
//   就会把一个属于"上一帧"的 0 冻在屏幕上，而此刻几何明明在（实测：先读到 0，
//   一秒后同一次会话里是 30732 个三角面、1961 个 draw call）。
//   它当时**不说假话**，它是**过期**的；而屏幕上两者长得一样。
//   ⇒ 帧派生的量必须等一帧之后再读。900ms 在软件光栅下也够跑好几帧了。
const SETTLE_MS = 900;
const MIN_FRAME_H = 380;

// 页面自己写的**失败告示**。这是转述它的话，不是我们的判据。
// ★ 认不出就退化成"超时" —— 超时仍然只说"没出几何"，不会变成假绿。
const FAIL_MARKS = [/载入失败/, /清单里没有这栋楼/, /不回退/];

const state = {
  iframe: null,
  probe: null,
  timer: null,
  childErr: null,
  onErr: null,
  settled: false,   // 就绪后那次补读数是否已经排上（见 SETTLE_MS 那段）
};
let disposed = false;
let cleanups = [];

function clearTimer() {
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
}

/** 一个量该怎么说：量不到 ≠ 0。两者的字面量必须不同。 */
function fmt(v) {
  return v === null || v === undefined ? '—' : String(v);
}

function setProbe(node, cls, text) {
  if (!node) return;
  node.className = `bld-probe ${cls}`;
  node.textContent = text;
  // ★ 这一行的宽度是 `max-width: 62ch`（见 building.css），超了就走省略号 ——
  //   而上面几个分支的行长差别很大：就绪态那行本来就 501px > 417px（**改之前就超**），
  //   等待态那行又把 `s.bname` 顶在行首（`#bname` 现在多了「· 生成 …」一截）⇒
  //   被吃掉的是**行尾**，而那正是「几何要 13~17 秒」这种有用的话。
  //   没有 title 时省略号是不可逆的信息丢失（屏幕上量不出"少了什么"）；补一行 title，
  //   鼠标停上去就能读全，布局一个像素都不动。
  node.title = text;
}

/**
 * 读一眼 iframe 里的实际状态。**只读事实，不做判断以外的推论。**
 * 判「就绪 / 失败 / 载入中」三态的依据全部来自子页暴露的量或它自己写的字。
 */
function snapshot(frame) {
  const win = frame.contentWindow;
  let doc = null;
  try { doc = frame.contentDocument; } catch { /* 理论上不会跨源，但不赌 */ }
  const title = (doc && doc.title) || '';
  let bname = '';
  try {
    const n = doc && doc.querySelector ? doc.querySelector('#bname') : null;
    bname = (n && n.textContent) || '';
  } catch { /* 文档还没成形 */ }

  const g = win && win.__gym3d;
  if (!g) {
    // ★ 这个分支同时也是「模块脚本在解析期就挂了」的信号：
    //   那种错发生在 iframe 的 load 之前，父页的错误钩子挂不上（见下面 arm 里的说明）。
    return { phase: 'boot', title, bname,
             note: '页面还没挂出握手口 __gym3d —— 脚本没跑起来，或还在解析' };
  }

  let built = false;
  let rooms = null;
  let purposes = null;
  let tris = null;
  let kids = null;
  let err = null;
  let su = false;
  try {
    built = g.geometryBuilding !== null && g.builtToken === g.buildToken;
    rooms = g.visibleRoomCount();
    purposes = g.legendPurposes();
    tris = g.info && g.info.render ? g.info.render.triangles : null;
    kids = g.scene ? g.scene.children.length : null;
    su = !!g.suMode;
  } catch (e) {
    err = String((e && e.message) || e);
  }
  // legendPurposes 是"代表多少种用途（长尾会折叠）"。它今天是个数组，
  // 但这里不赌形状 —— 是数组就数长度，是数就用它，都不是就写"量不到"。
  const purposeK = Array.isArray(purposes) ? purposes.length
    : (typeof purposes === 'number' ? purposes : null);

  const failed = FAIL_MARKS.some((re) => re.test(bname));
  return {
    phase: failed ? 'failed' : built ? 'ready' : 'loading',
    title, bname, building: g.geometryBuilding,
    rooms, purposeK, tris, kids, su, err,
  };
}

function paintProbe(node, s) {
  if (s.phase === 'ready') {
    const bits = [`楼 ${s.building}`];
    if (s.su) bits.push('数据源 SU 规格');
    bits.push(`可见房间 ${fmt(s.rooms)}`, `用途 ${fmt(s.purposeK)}`,
              `三角面 ${fmt(s.tris)}`, `场景对象 ${fmt(s.kids)}`);
    setProbe(node, 'ok', `三维已就绪 · ${bits.join(' · ')}`);
    return;
  }
  if (s.phase === 'failed') {
    setProbe(node, 'fail', `页面报载入失败：${s.bname || s.title || '（它没留下话）'}`);
    return;
  }
  if (s.phase === 'boot') {
    setProbe(node, 'wait', `载入中… ${s.note}${s.title ? `（标题 ${s.title}）` : ''}`);
    return;
  }
  setProbe(node, 'wait',
    `${s.bname ? s.bname + ' · ' : ''}载入中…（几何要 13~17 秒）`
    + (s.err ? `　★ 读握手量时出错：${s.err}` : ''));
}

/** 挂错误钩子 + 起轮询。每次 `load` 都重来一遍（子页自己切数据源也会触发 load）。 */
function arm(frame, probe) {
  clearTimer();
  // 每来一次 load 都是一个新周期（子页自己切数据源也会触发 load）⇒ 补读数那步重新算。
  state.settled = false;
  const win = frame.contentWindow;
  if (!win) { setProbe(probe, 'fail', '读不到 iframe 的 contentWindow'); return; }

  // ★ 子页**自己报错**时给它留个话口 —— 同源才做得到，而这一屏正好同源。
  //   没有这一步的话，three 在子页里失败 = 父页只看到一个空白框，
  //   而"空白框"与"这栋楼本来就没画"在屏幕上长得一模一样。
  // ★ 它只覆盖 load **之后**的运行时错误（GLTF 取不到、WebGL 上下文丢了）。
  //   load 之前的模块解析错误由 snapshot 的 'boot' 那支接住（握手口不存在），
  //   两条路互补，所以两处都留着。
  const onErr = (ev) => {
    const m = ev && (ev.message || (ev.error && ev.error.message));
    if (m) state.childErr = String(m).slice(0, 200);
  };
  try {
    win.addEventListener('error', onErr);
    state.onErr = [win, onErr];
  } catch { /* 挂不上就算了：下面轮询仍在 */ }

  const t0 = Date.now();
  const tick = () => {
    if (disposed) return;
    const s = snapshot(frame);
    if (state.childErr) s.err = s.err || state.childErr;
    paintProbe(probe, s);
    if (s.phase === 'ready') {
      // 见 SETTLE_MS 那段：先让用户看到"就绪"（这一刻的数是对的），
      // 再等一帧把帧派生的量重新读一遍，然后收工。
      if (!state.settled) {
        state.settled = true;
        state.timer = setTimeout(() => {
          if (disposed) return;
          const s2 = snapshot(frame);
          if (state.childErr) s2.err = s2.err || state.childErr;
          paintProbe(probe, s2);
        }, SETTLE_MS);
      }
      return;
    }
    if (s.phase === 'failed') return;
    const waited = Date.now() - t0;
    if (waited > READY_TIMEOUT_MS) {
      setProbe(probe, 'fail',
        `等了 ${Math.round(waited / 1000)} 秒还没出几何`
        + `（页面标题 ${s.title || '—'}；楼名栏 ${s.bname || '—'}`
        + `${s.err ? `；子页报错 ${s.err}` : ''}）`
        + ' —— 这不代表页面坏了，只代表「我们没等到几何到位」这个事实。');
      return;
    }
    state.timer = setTimeout(tick, POLL_MS);
  };
  tick();
}

/** 眼前这一屏**实际**在看的地址（子页可能自己写了 `?su=1`）。读不到就退回我们建的那个。 */
function currentSrc() {
  try {
    const href = state.iframe && state.iframe.contentWindow
      && state.iframe.contentWindow.location.href;
    if (href && href.startsWith(location.origin)) return href;
  } catch { /* 还没载入 */ }
  return state.iframe ? state.iframe.src : PAGE;
}

function toggleFull(frame, btn) {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
    return;
  }
  const req = frame.requestFullscreen || frame.webkitRequestFullscreen;
  if (typeof req !== 'function') {
    btn.disabled = true;
    btn.title = '这个浏览器没有全屏 API';
    return;
  }
  req.call(frame).catch((e) => {
    btn.title = `全屏被拒：${(e && e.message) || e}`;
  });
}

function reload(frame) {
  // 走子页自己的 reload 而不是重设 src：重设同一个 src 在部分浏览器里不会真的重载，
  // 于是按钮点下去"什么也没发生"——而它看着和"页面本来就不用重载"一样。
  try {
    frame.contentWindow.location.reload();
  } catch {
    try { frame.src = frame.src; } catch { /* 都没有就等下一轮 load */ }
  }
}

/** 量一次真实高度给 iframe —— 不写死 `calc(100vh - 某个魔数)`。 */
function fit(wrap) {
  const main = document.getElementById('main');
  if (!main || !wrap.isConnected) return;
  const foot = document.querySelector('.footer');
  const top = wrap.getBoundingClientRect().top;
  const fh = foot ? foot.getBoundingClientRect().height : 0;
  const pad = parseFloat(getComputedStyle(main).paddingBottom) || 0;
  const h = Math.max(MIN_FRAME_H, window.innerHeight - top - fh - pad - 4);
  wrap.style.height = `${Math.round(h)}px`;
}

/**
 * @param {HTMLElement} root 挂载点（app.js 给的是 #main）
 * @param {string} sub 形如 '' 或 'c006'
 */
export function render(root, sub) {
  disposed = false;
  cleanups = [];
  const name = (sub || '').trim();
  const src = PAGE + (name ? `?building=${encodeURIComponent(name)}` : '');

  const frame = el('iframe', {
    class: 'bld-frame',
    src,
    title: '整栋立体模型',
    // ★ 这里刻意**不加** sandbox：同源是我们读 `__gym3d` 握手口的前提，
    //   加了它这一屏就只剩"给个框、里面白不白不知道"。
  });
  state.iframe = frame;

  const probe = el('span', { class: 'bld-probe wait', text: '正在连 /building.html…' });
  state.probe = probe;

  const btnFull = el('button', {
    class: 'bld-btn', type: 'button', text: '全屏',
    onclick: () => toggleFull(frame, btnFull),
  });
  const btnTab = el('button', {
    class: 'bld-btn', type: 'button', text: '新标签打开',
    // 新标签开的是**眼前这一屏**的实际地址（子页可能已经自己切到 ?su=1 了）。
    onclick: () => window.open(currentSrc(), '_blank', 'noopener'),
  });
  const btnReload = el('button', {
    class: 'bld-btn', type: 'button', text: '重载',
    onclick: () => reload(frame),
  });

  const onFs = () => {
    btnFull.textContent = document.fullscreenElement ? '退出全屏' : '全屏';
  };
  document.addEventListener('fullscreenchange', onFs);
  cleanups.push(() => document.removeEventListener('fullscreenchange', onFs));

  const wrap = el('div', { class: 'bld-wrap' },
    el('div', { class: 'bld-bar' },
      el('span', { class: 'bld-where' },
        name ? `楼号 ${name}` : '未点名楼号 —— 用页面里自己的下拉选楼'),
      probe,
      el('span', { class: 'bld-sp' }),
      btnReload, btnTab, btnFull),
    el('div', { class: 'bld-box' }, frame),
    el('p', { class: 'bld-note' },
      '这一屏托管的是 ', el('code', { text: '/building.html' }),
      '（同一个进程、同一个端口，同源 iframe）。它是本轮唯一没有重写的界面：'
      + '那个页面成熟可用，重写它只有风险没有收益。',
      el('br'),
      '上面那个徽标读的是**页面自己**的握手量（`__gym3d.geometryBuilding` 与 '
      + '`builtToken === buildToken`），不是「它回没回 200」—— '
      + '「进程起来了」与「它在干活」不是一回事。'));

  mount(root, wrap);
  fit(wrap);

  const onResize = () => fit(wrap);
  window.addEventListener('resize', onResize);
  cleanups.push(() => window.removeEventListener('resize', onResize));

  frame.addEventListener('load', () => {
    if (disposed) return;
    arm(frame, probe);
  });

  // ★ 兜底：万一 load 事件在监听器挂上之前就烧完了（缓存命中时会这样），
  //   两秒后自己看一次 —— 宁可多探一次，也不要让这个徽标永远停在"正在连…"。
  const t = setTimeout(() => {
    if (disposed || state.timer) return;   // 已经在轮询了就别插一脚
    arm(frame, probe);
  }, 2000);
  cleanups.push(() => clearTimeout(t));
}

export function dispose() {
  disposed = true;
  clearTimer();
  const [win, fn] = state.onErr || [];
  if (win && fn) {
    try { win.removeEventListener('error', fn); } catch { /* 文档可能已经没了 */ }
  }
  state.onErr = null;
  state.childErr = null;
  for (const f of cleanups.splice(0)) {
    try { f(); } catch { /* 收尾失败不该挡住切换 */ }
  }
  const f = state.iframe;
  if (f) {
    // 顺序见文件头：先 about:blank（让子文档在活着时卸载），再移出 DOM。
    try { f.src = 'about:blank'; } catch { /* 已经拆了 */ }
    try { f.remove(); } catch { /* 同上 */ }
  }
  state.iframe = null;
  state.probe = null;
}

// 门户启动。
//
// 顺序是硬的：**先问会话，再装配**。
//
// ★ 说准一点：外壳的**标记**是在 `index.html` 里的（带 `hidden`），未登录时它
//   在 DOM 里、只是不显示 —— 那句话不该写成"一行都不建"。真正成立、也真正
//   要紧的是：未登录时 `assemble()` 一次都不跑，于是
//     · 一个数据请求都不发（导航是后端按 caps 过滤后才有的，不是前端筛出来的）；
//     · 三维不建（连地形 GLB 都不取）；
//     · 一个事件都不绑。
//   所以 F12 把那块 `hidden` 去掉也什么都看不到：导轨是空的、面板是空的、
//   画布是白的。**保护来自"没取过数"，不是来自"藏得好"。**

import { API, onUnauthenticated } from './api.js';
import { probe, mountLogin, describe, logout } from './session.js';
import { createScene } from './scene.js';
import { createPanel } from './panel.js';
import { createModules } from './modules.js';
import { el, fill, note } from './dom.js';

const $ = (id) => document.getElementById(id);

// 导航分组。★ 分组是**人的读法**，不是接口的字段 —— 所以写在这里，
//   而不是让后端多回一个 group 字段。后端那份 MODULES 只管"有什么、要什么权限"。
const GROUPS = [
  ['校区', ['overview', 'datascreen', 'campus3d', 'building']],
  ['设施与运行', ['facility', 'pipeline', 'energy', 'security']],
  ['平台管理', ['pipeline_flow', 'iam']],
];

const ICONS = {
  overview: 'M3 12h8V3H3zM13 21h8v-9h-8zM3 21h8v-6H3zM13 9h8V3h-8z',
  // 三维：一个立方体加一条地平线 —— 与「纵览」那个平面网格图标**刻意不同**，
  // 两个模块一个看平面一个看体量，图标长得像的话切换时人会以为自己没点动。
  campus3d: 'M12 2l9 5v10l-9 5-9-5V7zM12 2v20M3 7l9 5 9-5',
  building: 'M4 21V4h10v17M14 10h6v11M7 8h4M7 12h4M7 16h4M17 14h1M17 18h1',
  // 大屏：一台挂屏 + 屏里那条起伏线。★ 与「纵览」那个四方格图标**刻意不同** ——
  //   两块都是"看全景"的，图标长得像的话，切换时人会以为自己没点动。
  datascreen: 'M2 4h20v13H2zM6 13l3.2-4.6L12 12l2.6-3.4L18 13M8 21h8M12 17v4',
  facility: 'M12 3v3M12 18v3M3 12h3M18 12h3M12 8a4 4 0 100 8 4 4 0 000-8z',
  pipeline: 'M3 8h6a3 3 0 013 3v2a3 3 0 003 3h6M3 16h4M17 5h4v6',
  energy: 'M13 2L4 14h6l-1 8 9-12h-6z',
  security: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  pipeline_flow: 'M4 6h6M14 6h6M4 12h16M4 18h6M14 18h6M10 3v6M10 15v6',
  iam: 'M12 12a4 4 0 100-8 4 4 0 000 8zM5 21a7 7 0 0114 0',
};

function svgIcon(d) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', d);
  s.appendChild(p);
  return s;
}

// ───────────────────────────────────────────── 外壳

const S = {
  principal: null,
  modules: [],
  overview: null,
  anchors: new Map(),
  roster: [],
  rosterLoaded: false,
  active: 'overview',
  scene: null,
  panel: null,
  modulesUI: null,
  onlyAnchored: false,
};

function startClock() {
  const c = $('clock');
  const tick = () => {
    const d = new Date();
    c.textContent = d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).replace(/\//g, '-');
  };
  tick();
  setInterval(tick, 1000);
}

/** 顶栏"我是谁" + 需改口令的提醒。 */
function paintWho() {
  const d = describe(S.principal);
  const host = $('who');
  fill(host);
  host.appendChild(el('span', {}, el('b', { text: S.principal.username })));
  host.appendChild(document.createTextNode(' '));
  host.appendChild(el('span', { text: `· ${d.text}` }));
  if (d.mustChange) host.appendChild(el('span', { class: 'chip mock', text: '需改初始口令' }));
}

/** 左导轨。只画**后端给回来的**那些模块 —— 权限过滤在后端做，前端一个字都不判。 */
function paintRail() {
  const rail = $('rail');
  fill(rail);
  const byKey = new Map(S.modules.map((m) => [m.key, m]));
  for (const [title, keys] of GROUPS) {
    const present = keys.map((k) => byKey.get(k)).filter(Boolean);
    if (!present.length) continue;                      // 整组都不可见 ⇒ 连标题都不印
    rail.appendChild(el('h2', { text: title }));
    for (const m of present) {
      rail.appendChild(el('button', {
        type: 'button',
        'aria-current': String(m.key === S.active),
        onclick: () => go(m.key),
      }, svgIcon(ICONS[m.key] ?? ICONS.overview),
        el('span', { class: 'lbl', text: m.name }),
        el('span', { class: `tag ${m.mock ? '' : 'live'}`, text: m.mock ? '模拟' : '实测' })));
    }
  }
  rail.appendChild(el('footer', {},
    el('div', { text: '校园数字孪生平台' }),
    el('div', { text: '成都理工大学' }),
    el('div', { text: '仅校内网访问' })));
}

function paintStageBar() {
  const bar = $('stage-bar');
  fill(bar);
  const mk = (label, fn, pressed) => el('button', {
    type: 'button', 'aria-pressed': pressed === undefined ? null : String(pressed),
    onclick: fn,
  }, label);
  bar.appendChild(mk('立体视图', () => S.scene?.home()));
  bar.appendChild(mk('顶视', () => S.scene?.top()));
  bar.appendChild(mk('只看已锚定', () => {
    S.onlyAnchored = !S.onlyAnchored;
    for (const b of S.scene?.state?.blocks ?? []) {
      if (b.mesh) b.mesh.visible = !S.onlyAnchored || S.anchors.has(b.id);
    }
    S.scene?.requestRender();
    paintStageBar();
  }, S.onlyAnchored));
}

function paintLegend() {
  const lg = $('legend');
  fill(lg);
  const item = (color, text) => el('span', {},
    el('i', { style: `background:${color}` }), text);
  lg.appendChild(item('#8C857A', '模拟体块'));
  if (S.anchors.size) lg.appendChild(item('#B4571F', '已锚定'));
  if (S.scene?.state?.unplaced?.length) {
    lg.appendChild(item('#C0392B', `${S.scene.state.unplaced.length} 块没落到地面`));
  }
}

/** 场景级持续提示 —— **印在三维上，不印在面板里**。
 *
 *  ★ 它原来靠 `$('panel').prepend(...)` 挂在右侧面板顶上。那个位置是错的，两种错：
 *    ① **面板内容会被整份替换**（`panel.show()` / `renderIdle()` 都走 `fill(host, …)`）
 *       ⇒ 只要点一个体块、或从左栏切一次模块，这条提示就永远消失，而它说的正是一件
 *       **一直成立**的事。它跟面板里那些"这一刻选中的那块"的字**生命周期不同**。
 *    ② 它说的是"有一块**根本没被画出来**" —— 而那一块恰好是你在三维里**点不着**的那块。
 *       把它印在本该告诉你"你点了什么"的面板里，等于把线索放在最不可能去找的地方。
 *  ⇒ 判别标准：**这块文字说的是场景的常态还是当前选中项？** 常态归 `#scene-note`。
 */
function paintSceneNote() {
  const n = $('scene-note');
  const unp = S.scene?.state?.unplaced ?? [];
  fill(n);
  if (!unp.length) { n.hidden = true; return; }
  n.hidden = false;
  n.appendChild(el('span', {},
    `★ ${unp.length} 个模拟体块没能落到地形网格上（那块地是 NoData 洞）：`
    + `${unp.join('、')}。它们没有被画出来 —— 这里报的是「我没量到」，`
    + `不是「那里没有」。`));
}

// ───────────────────────────────────────────── 模块切换

function go(key) {
  S.active = key;
  paintRail();
  const doc = $('doc');
  const cw = $('canvas-wrap');
  const mod = S.modules.find((m) => m.key === key);

  // ★ 右栏那 344px 面板只在**三维场景**里才有内容（它答的是"你点中的是哪一块"）。
  //   文档型 / 驾驶舱型模块里它是空的 —— 不收起来就是屏幕上白占 344px，
  //   而驾驶舱那张正射图正好被挤掉同样多。⇒ 按模块切 `no-panel`。
  $('shell').classList.toggle('no-panel', S.modulesUI.isDoc(key));

  if (S.modulesUI.isDoc(key)) {
    cw.hidden = true;
    doc.hidden = false;
    S.modulesUI.render(doc, key, mod);
    $('stage-bar').hidden = true;
    $('hint').hidden = true;
    $('legend').hidden = true;
    $('scene-note').hidden = true;
  } else {
    cw.hidden = false;
    doc.hidden = true;
    fill(doc);
    $('stage-bar').hidden = false;
    $('hint').hidden = false;
    $('legend').hidden = false;
    paintSceneNote();               // 逐次重画：它属于场景，不随面板走
    S.scene?.syncSize();
    S.panel?.renderIdle();
  }
}

function paintHint() {
  fill($('hint'),
    el('b', { text: '校园一张图' }),
    '拖动旋转 · 滚轮缩放 · 点一个体块看它的档案。',
    el('br'),
    el('span', { class: 'busy', text: '体块目前是模拟的 —— 先不忙把真实建筑放上去。' }));
}

// ───────────────────────────────────────────── 锚点

async function loadAnchors() {
  // ★★ 这里是**就地改写**，不是 `S.anchors = new Map(...)`。
  //   面板建起来的时候拿到的是这个 Map **本身**（`ctx.anchors`），
  //   整份换掉的话，面板手里那个仍然指着最初那个空 Map ——
  //   于是每一次刷新锚点都"成功"，而面板永远显示"未锚定"，
  //   锚点工作流整条断在这里，屏幕上却一切正常。
  try {
    const rows = await API.anchors();
    S.anchors.clear();
    for (const r of rows) S.anchors.set(r.block_id, r);
    S.scene?.setAnchored([...S.anchors.keys()]);
    paintLegend();
    return null;
  } catch (e) {
    // ★ 锚点读不到**不阻断**三维 —— 但必须在屏幕上说出来。
    //   静默当成"还没有锚点"的话，界面会显示 0 个锚点，
    //   而"库连不上"与"确实一个都没建"是两件完全不同的事。
    S.anchors.clear();
    paintLegend();
    return e.status === 403 ? '你看不到锚点（没有范围）。' : `锚点读不到：${e.message}`;
  }
}

async function loadRoster() {
  if (S.rosterLoaded) return;
  // 同上：`ctx.roster` 是**这个数组**，不许整体换掉。
  try {
    const rows = await API.roster();
    S.roster.length = 0;
    for (const r of rows) S.roster.push(r);
    S.rosterLoaded = true;
  } catch { /* 名录读不到 ⇒ 锚点工具会显示 0 栋可选，用户看得见 */ }
}

// ───────────────────────────────────────────── 装配

async function assemble() {
  $('gate').hidden = true;
  $('shell').hidden = false;

  S.overview = await API.overview();
  S.principal = S.overview.me;
  S.modules = S.overview.modules ?? [];

  paintWho();
  startClock();

  const caps = new Set(S.principal.caps ?? []);

  S.modulesUI = createModules(S);
  S.scene = createScene($('gl'), {
    onPick: (id) => S.panel?.show(id),
  });
  S.panel = createPanel($('panel'), {
    scene: S.scene,
    principal: S.principal,
    caps,
    roster: S.roster,
    overview: S.overview,
    anchors: S.anchors,
    onAnchorChanged: async () => {
      // 锚点变了 ⇒ 把锚点表重读一遍（场景配色、图例、面板都跟着它）。
      // ★ 顺序是"先重读、再重画面板"：反过来的话，重画用的是**旧**锚点表 ——
      //   屏幕上就是"点了锚定，面板没变"，而再点一次又对了（铁律：进行中的数被当终值）。
      const err = await loadAnchors();
      await loadRoster();
      S.panel?.show(S.scene.state.picked);
      if (err) {
        const ov = $('overlay');
        ov.hidden = false;
        fill(ov, note(err, 'err'));
      }
    },
  });

  // 3D 起不来的话，**不把整页作废**：导轨、表格、账号页都还能用。
  // 把错误盖在画布上（不是弹窗），并且把原因原样印出来。
  try {
    await S.scene.boot();
  } catch (e) {
    const ov = $('overlay');
    ov.hidden = false;
    fill(ov, el('div', {},
      el('p', { class: 'kicker', text: '三维底图没有起来' }),
      note(String(e.message ?? e), 'err'),
      el('p', { class: 'busy', text: '左边其余模块不受影响，可以照常用。' })));
  }

  // 名录只有能建锚点的人要用（后端那条路由也只要 view，但没必要白取 93 行）。
  // ★ 必须 await：不歇的话锚点工具会在"名录还没到"的那一小段时间里印
  //   「0 栋可选」，而那看起来像"你的范围里一栋都没有"。
  if (caps.has('edit') || caps.has('manage')) await loadRoster();
  const aErr = await loadAnchors();

  paintRail();
  paintStageBar();
  paintLegend();
  paintHint();
  go('overview');

  // ★ 不再往面板里 prepend 那条 unplaced 提示 —— 见 paintSceneNote() 的注释。
  //   `go('overview')` 上面已经调过它了。
  if (aErr) $('panel').prepend(note(aErr, 'err'));

  $('logout').addEventListener('click', () => logout());
  return S;
}

// ───────────────────────────────────────────── 启动

onUnauthenticated(() => {
  // 会话中途失效：把人送回登录屏，并**说明原因** ——
  // 只说"请登录"的话，一个刚刚还在用的人会以为是自己点错了。
  const g = $('gate');
  if (!g.hidden) return;
  g.hidden = false;
  $('shell').hidden = true;
  $('loginmsg').textContent = '会话已失效（可能是在别处登录了，或者闲置太久）。请重新登录。';
});

(async () => {
  try {
    const p = await probe();
    if (!p) { mountLogin(assemble); return; }
    await assemble();
  } catch (e) {
    // 连"我是谁"都问不到 ⇒ 多半是后端没起。这时**不能**当成"未登录"
    // 把登录屏摆出来 —— 那会让人反复输口令，而后端根本没在跑。
    $('gate').hidden = false;
    $('loginmsg').textContent = `连不上后端：${e.message}。后端起来了吗？`;
    mountLogin(assemble);
  }
})();

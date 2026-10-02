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
// ★ 旧的 `scene.js`（three.js 那块"贴在纸面上的展板"）**不再被引用** ——
//   世界换成 2024 实景 3D Tiles，铺满视口。文件先留着，等第 3 关收尾再删
//   （删文件之前要先确认全仓没有第二个引用点）。
import { createPortalWorld } from './world/portal-world.js';
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

// ★★ 每个模块**占 HUD 的哪一块** —— 这一条取代了旧版那个"是不是文档型"的布尔值。
//
//   旧版只有一句判断：`key !== 'campus3d'` —— 除了三维，其余九个模块**全都**是
//   "把世界藏起来、往文档区画一页"。那一个布尔值就是「10 个模块 = 10 张互不
//   相干的页面」的源头 —— 它把"模块"与"世界"放成了互斥的两件事，
//   而大厂的做法正相反：**每个模块都长在同一片世界上**。
//
//   ★ 这里**不留旧标识符的字面量**：验收判据是
//     `grep -c "<旧名>" frontend/portal/js/*.js` 归零，而注释会被 grep 数进去
//     （铁律 025：grep 数出来的是「文本事实」）。把历史写在上面这段散文里就够了。
//
//   · `none`  —— 只有世界（三维场景）
//   · `sheet` —— 一整幅半透明面板浮在世界之上，世界从边缘与底下透出来
//   · `dash`  —— 左列卡片条 + 表格带；右侧详情面板留着，点一行 → 相机飞过去
//
//   ★ 落在表外的键（后端加了模块而这里没补）**默认 sheet**：宁可盖住世界，
//     也不要在还不认识它的时候把右栏打开 —— 后者会让一页没调过宽度的表挤成一条。
const HUD_FORM = {
  campus3d: 'none',
  // ★ 纵览驾驶舱从 `sheet` 改成 `map`（2026-10-02，出图之后改的）：
  //   `sheet` 是一整幅盖满的板 —— 实测它压掉 **82.4%** 的世界（`doc 1480×846`），
  //   而这一页要给人看的东西（正射影像 + 341 条轮廓）**世界背后就是同一份**
  //   （三维场景用的就是这张正射烘出来的瓦片）。两块各盖一半，等于互相挡。
  //   改成 `map` 之后：左列 = 六个真 KPI + 口径；右下角 = 一张 **520×340 的
  //   正射插图**（平面视角，看"轮廓压得准不准"这件事三维里的透视看不出来）。
  //   实测露出从 17.6% → 60% 以上（判据把边距和插图都算进去）。
  overview: 'map',
  datascreen: 'sheet',
  iam: 'sheet',
  building: 'dash',
  facility: 'dash',
  pipeline: 'dash',
  energy: 'dash',
  security: 'dash',
  pipeline_flow: 'dash',
};
const hudFormOf = (key) => HUD_FORM[key] ?? 'sheet';

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
  calOff: new Set(),          // 被图例点掉的那几档口径（三档是语义，所以图例要能过滤）
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
  // ★★ 署名容器必须在 `fill(rail)` **之前**取到引用。
  //   原因不是我漏写了一句，是 `fill` 的语义：`dom.js:32 clear(node)` 会把子节点
  //   一个个 `removeChild` 掉 ⇒ `#credit` **不在文档里了**，此后
  //   `document.getElementById('credit')` 恒返回 `null`。
  //   ★ 我原来把它取在函数**末尾**，于是它每次都取不到 ⇒ 下面那句 `throw` 每次都响
  //     ⇒ `paintRail()` 中断 ⇒ `globalThis.__portal = S`（`app.js:445`）**从没被执行过**。
  //     症状与"报错"完全不同：世界起来了（canvas 在、`.cesium-viewer-bottom` 也在）、
  //     导轨有按钮，而 `__portal` 是 `undefined`、`#credit` 查不到 ——
  //     量具在 180 s 超时之后才撞上它（`_ct_rep6.txt`：
  //     `Cannot read properties of undefined (reading 'scene')`）。
  //   ⇒ 教训与前一句注释里那条同族、方向相反：**"缺了就建"会把"我指错了"变成
  //     "这里本来就没有东西"；而"取不到就抛"如果取在错误的时刻，会把
  //     "我取晚了"变成"HTML 被改过"**。判据的位置和判据本身一样重要。
  //   ★ 这里**不是**在 `fill` 之前取一次就够了 —— 还要确认它**确实在 rail 里**，
  //     否则一个被挪到别处的 `#credit` 也会安静地通过（它照样能取到 id）。
  const credit = document.getElementById('credit');
  if (!credit || !rail.contains(credit)) {
    throw new Error('#credit 不在 #rail 里 —— 它由 index.html 的 #rail 预设，'
      + '本函数只负责把它挂回去。找不到说明 HTML 被改过。');
  }
  fill(rail);
  const byKey = new Map(S.modules.map((m) => [m.key, m]));
  for (const [title, keys] of GROUPS) {
    const present = keys.map((k) => byKey.get(k)).filter(Boolean);
    if (!present.length) continue;                      // 整组都不可见 ⇒ 连标题都不印
    rail.appendChild(el('h2', { text: title }));
    for (const m of present) {
      // ★ 导轨只有 72px，模块名与徽标都收进 `.lbl` 那个**飘出层**（CSS 里）。
      //   按钮自己只留图标 + 一个色点（`.is-live` 走绿色）—— 色点是让人在
      //   鼠标还没飘上去时就能看出「这一屏是模拟的还是实测的」。
      //   ★ 名字**没有删**，还在 `.lbl` 里 ⇒ 它仍是这个按钮的无障碍名。
      rail.appendChild(el('button', {
        type: 'button',
        class: m.mock ? '' : 'is-live',
        'aria-current': String(m.key === S.active),
        onclick: () => go(m.key),
      }, svgIcon(ICONS[m.key] ?? ICONS.overview),
        el('span', { class: 'lbl' },
          el('span', { text: m.name }),
          el('span', { class: `tag ${m.mock ? '' : 'live'}`, text: m.mock ? '模拟' : '实测' }))));
    }
  }
  rail.appendChild(el('footer', {},
    el('div', { text: '成都理工大学' }),
    el('div', { text: '仅校内网' })));
  // ★ 把署名容器**挂回去**（`fill(rail)` 在上面把它摘下来了；引用取在本函数开头）。
  //   它不能由这里 `createElement` 建：Cesium 只认建 viewer 那一刻拿到的那个元素，
  //   而 viewer 是在 `S.scene.boot()`（早于本函数）里建的 —— 新建一个等于
  //   建了个没人往里写的空盒子，而屏幕上看起来"署名没了"（铁律 125：缺了就建，
  //   会把"我指错了"变成"这里本来就没有东西"）。
  rail.appendChild(credit);
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
  bar.appendChild(mk('只看已关联', () => {
    S.onlyAnchored = !S.onlyAnchored;
    S.scene?.setOnlyAnchored(S.onlyAnchored);
    paintStageBar();
  }, S.onlyAnchored));
}

/** 图例 —— ★ 这里的三档**不是配色，是口径**（见 `outlines.js` 顶上的长注释）。
 *
 *  `h_m` 有两个来源：量到屋顶的 231 条、以及**没量到、退回地面**的 94 条。
 *  不把它们画成不同颜色的话，读的人会把"这里没量到"的高度读成"这栋楼只有一层" ——
 *  而那是个**看起来很正常的数**（0.43 m）。所以三档分色是判据的一部分，不是装饰。
 */
function paintLegend() {
  const lg = $('legend');
  fill(lg);
  const counts = S.scene?.state?.counts ?? null;
  /** ★ 一项 = 一个**可点**的口径开关（不是纯装饰）。
   *
   *  `aria-pressed` 不是给屏幕阅读器凑数的：它同时是 `.legend > span[aria-pressed="false"]`
   *  那条样式的选择器 —— 关掉的那一档要**看得出是关掉的**。"这一档 0 条"与
   *  "我把它关了"在屏幕上长得一样，而两件事处置完全不同（一个是数据问题，
   *  一个是观察者自己造成的）。 */
  const item = (cal, color, text, title) => {
    const off = S.calOff.has(cal);
    return el('span', {
      role: 'button', tabindex: '0',
      'aria-pressed': String(!off),
      title: title || text,
      onclick: () => toggleCaliber(cal),
      onkeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleCaliber(cal); }
      },
    }, el('i', { style: `background:${color}` }), text);
  };
  lg.appendChild(item('roof_p50', '#5ad2ff', `屋顶实测${counts ? ` ${counts.roof_p50 ?? 0}` : ''}`,
    '屋顶高程取点云 p50 —— 这一档的高度是量到的。点一下藏起来。'));
  lg.appendChild(item('fallback_roof', '#ffc857', `屋顶面推算${counts ? ` ${counts.fallback_roof ?? 0}` : ''}`,
    '屋顶面有、点不够，取的是面。点一下藏起来。'));
  lg.appendChild(item('fallback_ground', '#ff7b72', `退回地面${counts ? ` ${counts.fallback_ground ?? 0}` : ''}`,
    '★ 屋顶量不到、退回地面高程 —— 这一档的"净高≈0"是**没量到**，不是楼矮。点一下藏起来。'));
  if (S.anchors.size) {
    lg.appendChild(el('span', { title: '已经和名册里某一栋对上（有真楼名与真房间）' },
      el('i', { style: 'background:#ffb347' }), `已关联 ${S.anchors.size}`));
  }
}

/** 藏 / 显一档口径。★ 状态存在 `S.calOff` 里，**重画之后还在** ——
 *  否则点一次图例（`paintLegend()` 重建 DOM）就把刚点的那一档又打开了，
 *  屏幕上表现为"点了没反应"，而实际是"打开又被自己关掉"。
 *  ★ 与「只看已关联」正交：那两个开关各管各的，叠在一起时按**与**处理。 */
function toggleCaliber(cal) {
  if (S.calOff.has(cal)) S.calOff.delete(cal); else S.calOff.add(cal);
  S.scene?.setCaliberVisible(cal, !S.calOff.has(cal));
  paintLegend();
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
  const st = S.scene?.state ?? {};
  const unp = st.unplaced ?? [];
  const nFail = st.failedTotal ?? 0;
  fill(n);
  // ★★ 这一块以前**恒空**：它只读 `unplaced`，而 `portal-world.js` 把 `unplaced`
  //   写死成 `[]`（第 27 行自己注着「因此 paintSceneNote 不显示」）。
  //   与此同时世界层收了 `state.failed`（瓦片没读到），注释写着「**要在屏幕上说出来**」
  //   —— 而全仓 grep 不到它。⇒ 写好的东西没被调用（铁律 017），
  //   后果是「少了一块」与「那里本来就没有」在屏幕上一模一样（铁律 046/048）。
  //   现在它按**严重度**报三件事，全都没有就藏起来。
  if (nFail > 0) {
    n.hidden = false;
    const cap = st.failed?.length ?? 0;
    const more = cap < nFail ? `（明细只留了前 ${cap} 条）` : '';
    n.appendChild(el('span', {},
      `★ 有 ${nFail} 块实景瓦片**没读到**${more} —— 那些地方在画面上是空的，`
      + `但那不等于那里没有东西。第一块的原因：${st.failed?.[0] ?? '（未记）'}`));
    return;
  }
  if (st.base === false) {
    n.hidden = false;
    n.appendChild(el('span', {}, `★ 实景底图没装上来：${st.baseError ?? '原因未记'}`));
    return;
  }
  if (unp.length) {
    n.hidden = false;
    n.appendChild(el('span', {},
      `★ ${unp.length} 个模拟体块没能落到地形网格上（那块地是 NoData 洞）：`
      + `${unp.join('、')}。它们没有被画出来 —— 这里报的是「我没量到」，`
      + `不是「那里没有」。`));
    return;
  }
  n.hidden = true;
}

// ───────────────────────────────────────────── 模块切换

function go(key) {
  S.active = key;
  paintRail();
  const doc = $('doc');
  const mod = S.modules.find((m) => m.key === key);
  const form = hudFormOf(key);
  const is3d = form === 'none';

  // 右栏那 344px 面板答的是"**你点中的是哪一块**"。
  //   · 三维场景（`none`）—— **留着**：那一屏的主内容就是点一栋楼看它的名册。
  //   · 表格带（`dash`）—— **先收起来**。★ 这一条是出图看出来的，不是想出来的：
  //     收之前它在 `energy` / `security` 那几页上是一条 **344×894 的空黑板**
  //     （点过一行才有内容），白占 23% 宽、还把底部表带切掉一截。
  //     点行时由 `第 3 关` 的联动把它打开 —— 那时候它才有东西可答。
  //   · 一整幅面板（`sheet`）—— 本来就收着。
  //   ★ 收它只需改一个变量：`--hud-r` 是从 `--panel-w` 推出来的，
  //     所以 `#stage-bar` 与 `.doc.hud` 的右边距会**同时**跟着收。
  const wantsPanel = form === 'none';
  $('shell').classList.toggle('no-panel', !wantsPanel);

  // ★★ `dash` 形态下 `.doc` 自己**不再是那块盖住世界的板** —— 它退成一个透明、
  //   不收事件的定位容器，两块真板是它里面的 `.cards`（左列 396px）与 `.strip`
  //   （底部表带）。样式与"为什么必须拆"都写在 `portal.css` 的 `.doc.hud.is-dash`。
  //   ★ 它必须**每次切换都重设**（不是只在 dash 时加上）：从 dash 切到 sheet 时
  //     若不清掉，sheet 那页会落在一个透明容器里 —— 屏幕上表现为"这页没有底、
  //     字直接压在影像上"，而那看起来像配色坏了。
  //   `map` 与 `dash` 共用同一套"拆成透明容器 + 两块真板"的骨架，差别只在
  //   第二块板摆哪儿（`dash` 摆底部通栏、`map` 摆右下角插图）—— 所以这里
  //   两个形态都加 `is-dash`，再由 `is-map` 那一层改第二块板的位置。
  doc.classList.toggle('is-dash', form === 'dash' || form === 'map');
  doc.classList.toggle('is-map', form === 'map');

  if (is3d) {
    doc.hidden = true;
    fill(doc);
    $('stage-bar').hidden = false;
    $('hint').hidden = false;
    $('legend').hidden = false;
    paintSceneNote();               // 逐次重画：它属于场景，不随面板走
    S.panel?.renderIdle();
  } else {
    // ★★ 这里**不再** `cw.hidden = true`。旧版把世界整块藏掉，于是"切到一个模块"
    //   等于**离开三维** —— 那正是「10 个模块 = 10 张互不相干的页面」的成因。
    //   现在世界永远在，模块只是换一层罩在它上面的板。
    doc.hidden = false;
    S.modulesUI.render(doc, key, mod, form);
    // 这三样都是**三维的操作控件**，浮层盖着的时候点不到它们，留着就是骗人。
    $('stage-bar').hidden = true;
    $('hint').hidden = true;
    $('legend').hidden = true;
    $('scene-note').hidden = true;
  }

  // ★★ `syncSize()` / `requestRender()` **两条路都要走**。
  //   旧版只在三维那一支里调，因为另一支把画布 `hidden` 掉了、尺寸无从谈起。
  //   现在世界一直活着（Cesium 在后台继续取瓦片），不重新量尺寸的话，
  //   回到三维时 canvas 还是切走那一刻的大小 —— 屏幕上表现为"模型挤在左边一条"。
  S.scene?.syncSize();
  S.scene?.requestRender();
}

// ★★ 旧版这里印着一大段**给开发者看的话**（「体块目前是模拟的 —— 先不忙把真实
//   建筑放上去」）。那种话属于**口径**，不属于画面：它每一秒都压在三维上，
//   而它说的事情在对的人眼里是噪音、在错的人眼里会被当成"这平台还没做完"。
//   ⇒ 现在画面上只留**一句操作提示**；口径进图例的 `title` 与右侧面板。
function paintHint() {
  fill($('hint'),
    el('b', { text: '拖动旋转 · 滚轮缩放 · 点一栋楼' }),
  );
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
  S.scene = createPortalWorld($('world'), {
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

  // ★ 量具挂钩。**不是给用户用的**，是给 `_scratch/_p3_probe.py` 用的 ——
  //   世界层的内部状态（瓦片加载了几块、失败了几块、包围球多大）在 DOM 上
  //   **一个字都读不到**，而"画面上少了一块"与"那里本来就没有"同形（铁律 046/048）。
  //   没有这个钩子，验收就只能靠肉眼看截图 —— 那正是本仓反复禁止的量法。
  //   ★ 它不放大任何权限：`S` 里全是这一页**已经拿到**的东西（导航、名册、锚点），
  //     会话仍在 cookie 里、不经由此处。
  globalThis.__portal = S;
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

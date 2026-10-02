// 门户那一片世界 —— 把 `world.js`（Cesium 底）+ `outlines.js`（341 条真轮廓）
// 接到 `app.js` / `panel.js` 已有的那套调用面上。
//
// ★ 为什么要这一层"转接"，而不是让 `app.js` 直接 import 三份：
//   `app.js` 与 `panel.js` 现在整篇是按**旧的 `scene.js`（three.js）**写的 ——
//   它们要的是 `state.blocks / state.picked / home() / top() / setAnchored()`。
//   这一层把**同一套调用面**架到新世界上，于是"换掉世界"与"改业务面板"
//   可以分两步走、每步都能出图验。等下几步把业务也搬完了，这一层自然就薄了。
//
// ★★ 这一份**不认识后端** —— 它只调 `api.js` 里的地址表（铁律：地址表唯一）。
//
// ★★ 身份：341 条轮廓**没有楼号**（详见 `outlines.js` 顶上那段）。
//   所以这里给每条一个**轮廓自己的编号** `O<i>`，它**不是**楼号，
//   只是"这条轮廓"的键 —— 锚点表（`building_anchors.block_id`）就是按它存的。
//   一旦锚定，`panel.js` 那条既有通路就会把**真的**楼栋档案与房间读出来。

import { API } from '../api.js';
import { createWorld } from './world.js';
import { normalise, buildOutlines, CALIBERS } from './outlines.js';

export function createPortalWorld(host, opts = {}) {
  const world = createWorld(host, { tilesetUrl: opts.tilesetUrl });
  const state = {
    ready: false,
    blocks: [],            // ← 给 `app.js` / `panel.js` 读的那个数组（就是轮廓条目）
    picked: null,          // 当前选中的**条目对象**
    error: null,
    counts: null,          // 三档口径各多少条（图例要印）
  };

  // ★★ 世界层的"体检数"**转发**过来，不在这里另立一份常量。
  //   原来这里写的是 `unplaced: [], base: true` —— 两个**写死的快照**：
  //   `unplaced` 恒空（于是 `paintSceneNote` 永远不显示），`base` 恒真
  //   （于是"底图没装上来"这条路永远不会走到）。而真正会变的那两个值
  //   在 `world.state` 里，**降一层就够不着**。
  //   ⇒ 屏幕上的读数是"那一刻的样子"，转接层只该转发、不该复述（铁律 141/171 同族：
  //     一个变量名在两处指两个量，读的人分不出读到的是哪一个）。
  const HEALTH = {
    failed: 'failed', failedTotal: 'failedTotal', sse: 'sse', renderer: 'renderer',
    sseLog: 'sseLog', base: 'base', tiles: 'tiles', rendered: 'rendered',
    // ★ 世界层那个 `error` **换个名字**进来。这一层自己的 `state.error` 有别的含义
    //   （"轮廓读不到"），同名会盖掉一个、而两个都叫 error 谁也分不出读到的是哪个
    //   （铁律 174②：两个同名的量必须死掉一个）。
    baseError: 'error',
  };
  for (const [k, src] of Object.entries(HEALTH)) {
    Object.defineProperty(state, k, { get: () => world.state[src], enumerable: true });
  }

  let outlines = null;
  const linked = new Set();          // 已锚定的条目

  function setPicked(it) {
    state.picked = it;
    if (outlines) { if (it) outlines.select(it); else outlines.clearSelection(); }
    opts.onPick?.(it ? it.id : null);
  }

  return {
    state,
    world,
    get viewer() { return world.viewer; },
    get tileset() { return world.tileset; },
    get outlines() { return outlines; },

    async boot() {
      await world.boot();
      world.syncSize();

      // 轮廓是**数据**，读不到就明说 —— 不许悄悄只画一片底，
      // 那样屏幕上看着"世界起来了"，而 341 条实测轮廓一条都不在（铁律 017 的同族）。
      let raw;
      try {
        raw = await API.outlines();
      } catch (e) {
        state.error = `建筑轮廓读不到：${e.message}`;
        throw e;
      }
      const items = normalise(raw);
      items.forEach((it) => { it.id = `O${it.i}`; });    // ← 锚点表的键（**不是楼号**）
      state.blocks = items;
      const hist = {};
      items.forEach((it) => { const k = it.cal || '未知'; hist[k] = (hist[k] || 0) + 1; });
      state.counts = hist;

      outlines = buildOutlines(world.viewer, world.tileset, items, setPicked);
      state.ready = true;
      return this;
    },

    home: () => world.home(),
    top: () => world.top(),
    syncSize: () => world.syncSize(),
    requestRender: () => world.scene?.requestRender(),

    /** 锚点变了 ⇒ 换色 + 记下来（"只看已关联"要用）。 */
    setAnchored(keys) {
      linked.clear();
      for (const k of keys) {
        const it = state.blocks.find((b) => b.id === k);
        if (it) linked.add(it);
      }
      outlines?.setLinked?.(linked);
    },

    /** "只看已关联" —— 走**过滤函数**，不是逐条 `show=false`。
     *  ★ 理由见 `outlines.js` 里那段：逐条关会被图例那个开关再打开一部分。 */
    setOnlyAnchored(on) {
      outlines?.setFilter(on ? (it) => linked.has(it) : null);
      world.scene?.requestRender();
    },

    /** 图例点一下藏掉一档 —— 三档是**语义**，所以图例本身要能过滤。 */
    setCaliberVisible(cal, on) { outlines?.setCaliberVisible(cal, on); },

    /** 相机飞到某一条上（表里点一行 → 世界里那一条亮起来）。 */
    focus(it) { if (it) outlines?.focus(it); },

    boot_error_text: () => state.error,
  };
}

export { CALIBERS };

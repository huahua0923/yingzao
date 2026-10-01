// 右侧详情栏 —— 「点开一栋，看它每层的功能和需求」。
//
// ★ 这一栏的全部意义在于**把两种数据分得开**：
//     · 模拟（本轮的体块参数：面积/高度/层数/用途）—— 灰章 `模拟`
//     · 实测（锚定之后从 `data/buildings/` 读回来的）—— 绿章 `实测`
//   混着印、只靠文案暗示，读的人迟早把模拟数当实测数报上去。
//   所以这里**每一条**都挂在明确标了章的那一块下面，没有"裸"的数字。
//
// ★ 锚点是**解锁键**，不是给块起个名：锚定之前这一栏只有几何；
//   锚定之后才出现楼层、房间、用途、使用单位 —— 那些是**真的**。

import { API, ApiError } from './api.js';
import { el, fill, kv, block, chip, note, num, int } from './dom.js';

// 用途配色的固定表 —— 同一个用途在全校拿同一个颜色。
// ★ 用**固定表 + 稳定哈希**，不用"按出现顺序分配"：后者会让同一栋楼
//   在两次加载之间换颜色（用途表顺序一变就全变），而颜色是给人记的。
const USE_COLORS = [
  '#B4571F', '#3F6B3A', '#41618A', '#8A6A1F', '#6E4A72',
  '#2F6E6B', '#8C3B3B', '#5A6B2F', '#8A5A38', '#4A4A66',
];

function colorOf(key) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < key.length; i++) { h ^= key.charCodeAt(i); h = Math.imul(h, 16777619); }
  return USE_COLORS[(h >>> 0) % USE_COLORS.length];
}

/** 把 rows 按某字段计数、按数值降序。空值归到"未填"——**不并进任何一档**。 */
function tally(rows, key, valOf = () => 1) {
  const m = new Map();
  for (const r of rows) {
    const k = (r[key] === null || r[key] === undefined || r[key] === '') ? '未填' : String(r[key]);
    m.set(k, (m.get(k) ?? 0) + valOf(r));
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

/** 横向堆叠条 + 图例。数据可视化是设计系统的一部分，不是后补的一张图。 */
function stacked(entries, total, unit = '') {
  const bar = el('div', { class: 'stack', role: 'img',
    'aria-label': entries.slice(0, 6).map(([k, v]) => `${k} ${v}${unit}`).join('，') });
  for (const [k, v] of entries) {
    const i = el('i', { style: `flex:${Math.max(v, 1e-9)} 0 0;background:${colorOf(k)}` });
    i.title = `${k}：${num(v, 1)}${unit}（${(v / total * 100).toFixed(1)}%）`;
    bar.appendChild(i);
  }
  const key = el('div', { class: 'stack-key' });
  for (const [k, v] of entries.slice(0, 8)) {
    key.appendChild(el('span', {},
      el('i', { style: `display:inline-block;width:9px;height:9px;margin-right:4px;`
        + `vertical-align:-1px;background:${colorOf(k)}` }),
      k, ' ', el('b', { text: v.toFixed(1) + unit })));
  }
  if (entries.length > 8) {
    key.appendChild(el('span', { class: 'busy', text: `另有 ${entries.length - 8} 类，见下表` }));
  }
  return el('div', {}, bar, key);
}

/**
 * 面板主体。
 * @param {HTMLElement} host `#panel`
 * @param {object} ctx `{scene, principal, caps:Set, roster, anchors:Map, onAnchorChanged}`
 */
export function createPanel(host, ctx) {
  /** 当前选中块的详情（一次只挂一个请求，切块时把上一个作废）。 */
  let token = 0;

  function renderIdle() {
    const ov = ctx.overview;
    fill(host,
      // ★ 题头这句原来写的是「总览驾驶舱」—— 那个模块 2026-10-01 已经改名
      //   「三维场景」（portal.py 的 MODULES），导轨上再没有「总览驾驶舱」这个名字。
      //   这块面板就是三维那一屏的右栏，题头必须印**它自己那个模块的名字**：
      //   印一个不存在的旧名，读的人会以为这是另一个页面。
      el('p', { class: 'kicker', text: '三维场景' }),
      el('h3', { text: '成都理工大学 · 校园空间' }),
      el('p', { class: 'lede', text: '在左边三维里点一个体块。' }),
      // ★ 这一行叫「名录登记层数」而不是「楼层合计」，是**故意**的：
      //   同一个「楼层合计」在「建筑与空间」那一页还有一个数，两个数**不相等**
      //   （这里是 `index.json` 里人写的那一列，那里是盘上 `floors/floor*.json`
      //   的份数），差 4 层。两个不同的量挂同一个名字，读的人只能自己挑一个信 ——
      //   而且多半会挑错。⇒ 名字里带上出处，让两屏看起来就是两件事。
      ov ? block('名册（实测）', 'index.json', kv([
        ['名录登记栋数', `${int(ov.roster?.n_buildings)} 栋`],
        ['名录登记层数', `${int(ov.roster?.n_floors)} 层`],
        ['锚点', ov.anchors?.state === 'ok'
          ? `${int(ov.anchors.stats?.n_blocks)} 块 / 覆盖 ${int(ov.anchors.stats?.n_buildings)} 栋`
          : null],
      ])) : null,
      ov && ov.anchors?.state === 'down'
        ? note(`锚点库连不上：${ov.anchors.reason ?? '未说明'}`
          + '（三维与名册还能看，"哪块是哪栋"做不了）。', 'err')
        : null,
    );
  }

  /** 两种"没有"必须分开说：读不到（错）与 是空的（0）。 */
  function renderNoRooms(reason, kind) {
    if (kind === 'empty') {
      return note('房间表是空数组 —— 盘上有这一栋，但没有房间记录'
        + '（这是"确实没有"，不是"读不到"）。', '');
    }
    return note(`房间数据读不到：${reason}`, 'err');
  }

  async function renderAnchored(b, anchor) {
    const code = anchor.building_code;
    // 表头先画出来（此刻数据还没回来），最后整体重画时**它也在 body 里** ——
    // 早先我写成"先 fill 表头、再 fill 数据"，第二趟就把表头整个抹掉了。
    const body = [
      el('p', { class: 'kicker', text: `模拟体块 ${b.id} · 已锚定` }),
      el('h3', { text: b.realTitle ?? code }),
      el('p', { class: 'lede' }, chip('实测', 'live'), ' ',
        chip(`锚定方式：${anchor.method === 'manual' ? '人工指认' : anchor.method}`, 'off')),
      el('p', { class: 'busy', text: '正在读楼栋档案…' }),
    ];
    fill(host, ...body);

    const my = token;
    let info = null, rooms = null, eInfo = null, eRooms = null;
    // ★ 只读 `rooms`，**不读** `/floors`：逐层的数从每间房的 `floor` 自己分出来，
    //   与上面的整栋构成同源。两个接口各算一遍的话，两边一旦口径不同
    //   （比如一栋楼在 floors 里有 11 层、在 rooms 里只落得下 6 层），
    //   屏幕上就是两套对不上的数，而没有任何东西会说谁对。
    // ★ 两个请求**并行**：串起来等，切块时会明显卡一下。
    await Promise.all([
      API.buildings().then((rows) => { info = rows.find((r) => r.name === code) ?? null; },
        (e) => { eInfo = e; }),
      API.rooms(code).then((rows) => { rooms = rows; }, (e) => { eRooms = e; }),
    ]);
    if (my !== token) return;                       // 期间换了块 ⇒ 这次作废

    body.length = 3;                                // 去掉"正在读…"那一行

    body.push(block('楼栋档案', '实测', info ? kv([
      ['代号', code],
      ['名称', info.title || null],
      ['层数', info.floor_count === undefined ? null : `${info.floor_count} 层`],
      ['房间数', info.rooms === undefined ? null : `${int(info.rooms)} 间`],
      ['轮廓面积', info.outline_area_m2 === undefined ? null : num(info.outline_area_m2, 1, ' m²')],
      ['层高', info.layer_height ? num(info.layer_height, 1, ' m') : null],
      ['有模型', info.has_model ? '有' : '无'],
    ]) : note(`楼栋档案读不到：${eInfo?.message ?? '未知原因'}`, 'err')));

    // ── 整栋的功能构成（面积口径）
    if (rooms && rooms.length) {
      const byArea = tally(rooms, 'purpose', (r) => Number(r.area_m2) || 0)
        .filter(([k, v]) => v > 0);
      const totArea = byArea.reduce((s, [, v]) => s + v, 0);
      body.push(block('整栋功能构成', `${rooms.length} 间 · 按面积`,
        byArea.length ? stacked(byArea, totArea, ' m²')
          : note('这些房间都没填用途，构成图画不出来。', ''),
      ));
    }

    // ── 逐层
    if (rooms) {
      const byFloor = new Map();
      for (const r of rooms) {
        const f = r.floor;
        if (!byFloor.has(f)) byFloor.set(f, []);
        byFloor.get(f).push(r);
      }
      const lis = [];
      for (const [f, rs] of [...byFloor.entries()].sort((a, b) => (a[0] ?? -99) - (b[0] ?? -99))) {
        const t = tally(rs, 'purpose', (r) => Number(r.area_m2) || 0).slice(0, 4);
        const area = rs.reduce((s, r) => s + (Number(r.area_m2) || 0), 0);
        lis.push(el('li', {},
          el('span', { class: 'no', text: f === null || f === undefined ? '—' : `${f}F` }),
          el('span', { class: 'use' },
            `${rs.length} 间 · ${num(area, 0, ' m²')}`,
            ...t.map(([k, v]) => el('span', {},
              el('br'), el('span', { style: `color:${colorOf(k)}`, text: '■ ' }), k,
              ` ${num(v, 0, ' m²')}`)),
          )));
      }
      body.push(block('逐层功能', rooms.length ? `${byFloor.size} 层` : '',
        rooms.length ? el('ul', { class: 'floor-list' }, ...lis)
          : renderNoRooms(null, 'empty')));
    } else {
      body.push(block('逐层功能', '', renderNoRooms(eRooms?.message ?? '未知原因', 'err')));
    }

    // ── 使用单位
    if (rooms && rooms.length) {
      const byDept = tally(rooms, 'dept', (r) => Number(r.area_m2) || 0);
      const nFill = rooms.filter((r) => r.dept).length;
      body.push(block('使用单位', nFill === rooms.length ? '已填齐' : `${rooms.length - nFill} 间未填`,
        stacked(byDept, byDept.reduce((s, [, v]) => s + v, 0) || 1, ' m²')));
    }

    // ── 锚点本身
    const acts = [];
    if (ctx.caps.has('manage')) {
      acts.push(el('button', {
        class: 'ghost', type: 'button', style: 'margin-top:12px',
        onclick: async () => {
          if (!confirm(`撤掉 ${b.id} → ${code} 这条锚点？（只删这条对应关系，不删楼栋）`)) return;
          try { await API.dropAnchor(b.id); ctx.onAnchorChanged?.(); }
          catch (e) { alert(`撤不掉：${e.message}`); }
        },
      }, '撤掉这条锚点'));
    }
    body.push(block('锚点', anchor.method === 'manual' ? '人工' : anchor.method, kv([
      ['体块', b.id],
      ['楼栋', code],
      ['置信度', anchor.confidence === null || anchor.confidence === undefined
        ? null : num(anchor.confidence, 2)],
      ['设于', (anchor.set_at ?? '').slice(0, 19).replace('T', ' ') || null],
      ['备注', anchor.note || null],
    ]), ...acts));

    fill(host, ...body);
  }

  function renderMock(b) {
    fill(host,
      el('p', { class: 'kicker', text: `模拟体块 ${b.id}` }),
      el('h3', { text: b.use }),
      el('p', { class: 'lede' }, chip('模拟', 'mock'), ' ',
        chip('未锚定', 'off')),
      note('模拟体块 · 未和名录里任何一栋对上 —— 只有几何，没有真实的楼层与用途。'),
      block('体块参数', '模拟', kv([
        ['底面积', num(b.area_m2, 0, ' m²')],
        ['高度', num(b.h, 0, ' m')],
        ['层数', `${b.floors} 层`],
        ['落地面高', Number.isFinite(b.landY) ? num(b.landY, 1, ' m（椭球高）') : null],
        ['朝向', `${b.rot}°`],
        ['备注', b.note || null],
      ])),
    );

    if (!ctx.caps.has('manage')) {
      host.appendChild(note('锚定需要「搭建方」权限 —— 你现在的账号只能看。'));
      return;
    }
    host.appendChild(renderAnchorTool(b));
  }

  /** 锚定工具：从名录里挑一栋，把这块对准它。 */
  function renderAnchorTool(b) {
    // ★ 名录的字段是 **`code`**，不是 `name`。后端 `/api/portal/roster`
    //   把 index.json 里的 `name` **改名成** `code` 再发出来（portal.py:246）。
    //   我这儿原先按 `name` 读 —— 那样每个 `option` 的 value 都会是字符串
    //   "undefined"，而且本地那道校验**永远为假**，屏幕上会印
    //   「名录里没有 c006」，把人往"我打错了"上引。
    const roster = ctx.roster ?? [];
    const input = el('input', {
      type: 'text', placeholder: '搜代号或名称，如 c006 / 砚湖图书馆',
      style: 'width:100%;padding:8px 10px;border:1px solid var(--rule);'
        + 'background:var(--paper);font:13px/1 var(--sans)',
      list: 'roster-list',
    });
    const dl = el('datalist', { id: 'roster-list' });
    for (const r of roster.slice(0, 400)) {
      dl.appendChild(el('option', { value: r.code, label: `${r.code} ${r.title ?? ''}` }));
    }
    const msg = el('p', { class: 'busy', style: 'min-height:1.4em;margin:8px 0 0' });
    const btn = el('button', {
      class: 'ghost', type: 'button', style: 'width:100%;margin-top:10px',
      onclick: async () => {
        const code = input.value.trim().split(/\s+/)[0];
        if (!code) { msg.textContent = '先选一栋。'; return; }
        // ★ 本地**不再**先判"名录里有没有这一栋"。这张名录是页面打开那一刻
        //   取的快照，而名录会变 —— 拿过期快照去拒，会把"这栋刚加进名录"
        //   报成"你打错了"，而那句话指向的行动（重打一遍）恰恰是错的。
        //   判"这栋在不在、你够不够得着"是服务端的事（它每次都现读名录），
        //   这里只负责把它的原话原样显示出来。
        btn.disabled = true;
        try {
          await API.setAnchor({ block_id: b.id, building_code: code, method: 'manual' });
          ctx.onAnchorChanged?.();
        } catch (e) {
          // ★ 后端那句原样显示。「名录里没有」与「你没权限」与「库挂了」
          //   三句话补救办法完全不同，我在这儿替它归纳就把它刚说清的东西抹了。
          msg.textContent = e instanceof ApiError ? e.message : String(e);
        } finally { btn.disabled = false; }
      },
    }, '把这一块锚定到这一栋');

    return block('这是哪一栋？', `${roster.length} 栋可选`,
      note('名录已按你的可见范围过滤。'),
      input, dl, btn, msg);
  }

  /** 主入口：块变了就重画。 */
  async function show(blockId) {
    token += 1;
    const my = token;
    if (!ctx.scene?.state?.ready) return;
    const b = ctx.scene.state.blocks.find((x) => x.id === blockId);
    if (!b) { renderIdle(); return; }

    if (b.unplaced) {
      fill(host,
        el('p', { class: 'kicker', text: `体块 ${b.id}` }),
        el('h3', { text: '没能落到地面上' }),
        note('高程在地形网格上是空的（那块地是 NoData 洞）⇒ 没有被画出来。'
          + '这是"我没量到"，不是"那里没有"。', 'err'));
      return;
    }

    const anchor = ctx.anchors.get(b.id) ?? null;
    if (!anchor) { renderMock(b); return; }

    // 锚定了 —— 先把名录里的名字拿到（overview 里没有），再画真数据。
    if (b.realTitle === undefined) {
      try {
        const rows = await API.buildings();
        if (my !== token) return;
        b.realTitle = rows.find((r) => r.name === anchor.building_code)?.title
          ?? anchor.building_code;
      } catch {
        if (my !== token) return;
        b.realTitle = anchor.building_code;
      }
    }
    await renderAnchored(b, anchor);
  }

  return { show, renderIdle };
}

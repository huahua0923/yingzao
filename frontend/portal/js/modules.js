// 各模块的页面内容。
//
// ★ 这一份里**每一块都自己声明它是实测还是模拟**，而且声明**印在屏幕上**：
//     · 「建筑与空间」「账号与权限」—— 走真实接口，来源是盘上的
//       `data/buildings/`（92 栋、房间表）与库里的 `users/roles/grants`。
//     · 设施 / 能耗 / 安防 / 数据与流程 —— **模拟**。
//       数不是随便编的：由**固定种子**从楼栋代码推出来（见 `rng.js` 的 `rng`），
//       刷新不变、换机器也不变。这么做不是为了好看 —— 一个每次刷新都变的数
//       看起来比一个固定的数更"真"，而它同样是编的。
//
// ★★ 2026-10-02 **删掉「管网与回线」整屏**（用户原话「回线你理解错了，相关的删掉」）。
//   同趟删的：`ledgerPipeline()` + `pipeline()` 那一屏 + `PIPE_KINDS` / `PIPE_OWNER`
//   两张表；后端 `api/routers/portal.py` 的 `MODULES` 里那条也撤了。
//
//   ★ 为什么删**整屏**而不是只抹掉「回线」两个字：四个类型（井 / 通道 / 线 / 回线）
//     出自**同一句**用户原话，我既然理解错了一个，另外三个的合法性也从未被验过 ——
//     而它们看起来比「回线」正常得多，所以更危险。那一屏的四列
//     （长度 / 埋深 / 权属 / 巡检）与 `J-/TD-/X-/HX-` 编号前缀，**全部**是我的编造，
//     盘上没有任何真管网资料。
//   ★ 也**不许**把它改名成「管线」留着：那等于把用户的定义换成我的猜测，
//     而那一步不会报错。这条纪律 2026-10-01 就定下了（见
//     `校园数字孪生平台·功能梳理.md` §215）。
//   ⇒ 恢复条件：先拿到**真的**管网资料（走向 / 埋深 / 权属 / 巡检至少一个真源），
//     再把这一屏与后端那条一起写回来。空手加回来 = 又把编的数摆上屏幕。

import { API, ApiError } from './api.js';
import { el, fill, kv, block, chip, note, num, int, statBox } from './dom.js';
import { rng } from './rng.js';
import { renderOverview } from './cockpit.js';
import { renderDatascreen } from './datascreen.js';

// ────────────────────────────────────────────── 模拟台账

const DEVICES = ['电梯', '多联机空调', '新风机组', '配电柜', '生活水泵', '消防泵',
                 '锅炉', '空压机', 'UPS', '弱电柜'];

function iso(dayOffsetFromToday) {
  const d = new Date();
  d.setDate(d.getDate() - dayOffsetFromToday);
  return d.toISOString().slice(0, 10);
}

// ★★ 这四张模拟台账的**主键**从「341 条轮廓」改成了「93 栋真名册」。
//   （原为五张，「管网与回线」2026-10-02 整屏删除 —— 见本文件开头的长注。）
//
//   旧版的主键是 `ctx.scene.state.blocks` —— 那是**建筑轮廓**，一条只有
//   `{ i, poly, area, h, base, cal, code }`。换掉假体块那一步把 `use / area_m2 /
//   floors` 三个字段一起带走了，于是：
//     · 设施设备 / 能耗 / 安防 / 数据与流程 —— **四页直接抛**
//       `TypeError: Cannot read properties of undefined (reading 'split')`，
//       屏幕上只有一条红字，整页是空的；
//     · （已删的「管网与回线」当时**不抛**，但那一列印的是 `O12` 这种
//       **轮廓编号**，而它看起来就是一个正常的楼号。）
//   ⇒ 两种坏法里，**不抛的那一种更坏**（铁律 016/046：命令自己报错时的空输出
//     不是"没有数据"；反过来，静默印出一个像楼号的编号也不是数据）。
//
//   改用 `API.buildings()`（实测、93 栋、带真 `title`）当主键，一举三得：
//     ① 楼名是真名册的（用户 2026-10-01 选的就是"接真名册，数值仍标模拟"）；
//     ② 三个字段都有真值（`floor_count` / `outline_area_m2`）；
//     ③ 种子键从 `O123` 换成真楼号 ⇒ **刷新、换机器、换范围都是同一组数**。

/** 台账里怎么称呼一栋楼。★ `name` 是代号、`title` 是中文名，两个都印 ——
 *  只印代号的话，读的人得自己去别处查"c006 是哪栋"。 */
const labelOf = (b) => [b.name, b.title].filter(Boolean).join(' ');

/** 每类设备**一台大约管多少平方米**（`[下界, 上界]`，m²/台）。
 *
 *  ★ 这是**模拟档、取值域**，不是实测值（模块仍标「模拟」）—— 与 `ledgerEnergy`
 *    那两个强度档同一个身份，别把它读成"量过"。
 *  ★ 但它必须**物理上讲得通**，因为它是屏幕上那个「台数」的唯一来源：
 *    配电柜比锅炉密（配电柜几百 m² 一台、锅炉几千 m² 一台），
 *    所以同样一栋楼里配电柜会比锅炉多 —— 这一条读数的人一眼就能验。
 *  ★★ 加这张表的**真正理由**是修一个假数：原来写的是 `2 + floor(r() * 40)`，
 *    **不含面积**。于是 30 m² 的单体楼与 3 万 m² 的教学楼，台数分布完全一样
 *    —— 屏幕上表现为「c118（30 m²）装着 27 台空压机」这种一眼假的数，
 *    而它**不会报错**（与 `ledgerEnergy` 修之前那个 "c118 是全校最耗电的楼"
 *    是同一个病：分子不看分母）。
 */
const DEVICE_SPAN = {
  电梯: [2500, 6000], 多联机空调: [800, 2500], 新风机组: [1200, 3500],
  配电柜: [500, 1500], 生活水泵: [3000, 12000], 消防泵: [5000, 20000],
  锅炉: [6000, 25000], 空压机: [4000, 15000], UPS: [1500, 6000],
  弱电柜: [400, 1200],
};

/** 设施设备：每栋挑 2~4 类设备。 */
function ledgerFacility(rows) {
  const out = [];
  for (const b of rows) {
    const r = rng(`facility:${b.name}`);
    const k = 2 + Math.floor(r() * 3);
    // ★ 选设备**不许**写 `sort(() => r() - 0.5)`：那个比较器不满足传递性，
    //   `Array.prototype.sort` 对不一致的比较器**结果由实现决定** ——
    //   于是"换机器同一组数"这个承诺当场失效，而屏幕上没有任何变化。
    //   改成给每台设备一个**一次算定的键**，再按键排。
    const picked = DEVICES
      .map((d) => [d, rng(`facility:${b.name}:${d}`)()])
      .sort((x, y) => x[1] - y[1])
      .slice(0, k)
      .map(([d]) => d);

    // ★ 面积缺了就**不编台数** —— 与 `ledgerEnergy` 同一条纪律：一栋楼多大都不知道，
    //   却印出"装着 12 台配电柜"，那是把"不知道"伪装成"量到了"（铁律 123 同族）。
    const A = Number(b.outline_area_m2);
    const hasA = Number.isFinite(A) && A > 0;

    for (const dev of picked) {
      const [lo, hi] = DEVICE_SPAN[dev];
      const rd = rng(`facility:${b.name}:${dev}:span`);
      const span = lo + rd() * (hi - lo);      // 这一台管多少 m²
      // ★ `max(1, …)` 是**域界**不是修饰：楼里"装了 0 台配电柜"不成立，
      //   而 `round(30/1500) = 0` 会把它印出来。代价是**小楼那一档密度必然越界**
      //   （30 m² 只有 1 台 ⇒ 每台管 30 m²）—— 这是夹取的必然结果，
      //   量具要把这一档**单独数出来**，不许把它混进"密度合规"里（铁律 062）。
      const n = hasA ? Math.max(1, Math.round(A / span)) : null;
      const bad = n === null ? null : Math.floor(r() * Math.max(1, n / 12));
      out.push({
        设备: dev, 所在: labelOf(b),
        '面积': hasA ? A.toFixed(0) : null,
        台数: n,
        在用: n === null ? null : n - bad,
        待修: bad,
        最近维保: iso(10 + Math.floor(r() * 300)),
      });
    }
  }
  return out;
}


/** 能耗：每栋一行。
 *
 *  ★ 电耗与水耗**必须随楼的大小走**。原来写的是 `4000 + r() * 46000` ——
 *    那个式子**不含面积**，于是「单位面积电耗」那一列量出来是这样（实测，见
 *    `_scratch/_p3_energy_domain.py`）：
 *      `corr(面积, 月用电) = −0.145`（真有楼的话该是**强正**，实际略负）；
 *      分母（总建筑面积）摆幅 **1462 倍**、分子只有 **9.4 倍**
 *      ⇒ 单位面积电耗从 3.72 排到 **1610.73**（433 倍），
 *        而最高的两行**正是最小的两栋楼**（c118 一层 30 m² 月耗 48966 kWh）。
 *    一个**看起来像结论的假数**：读的人会得出「c118 是全校最耗电的楼」。
 *
 *    改法：**先按面积定强度、再乘回面积** —— 这样派生的比值列才有意义，
 *    而且它的分布直接等于强度档本身，落在物理上说得通的区间里。
 *    强度档：高校教学/办公 **2~12 kWh/m²·月**（中位约 3.7，与实测一致）；
 *    水 **0.02~0.08 t/m²·月**（≈ 1~2.5 L/m²·天，按建筑面积人均 10 m² 折算）。
 *
 *    ★ 这两个档是**取值域**不是实测值 —— 模块本身仍标「模拟」。
 */
function ledgerEnergy(rows) {
  return rows.map((b) => {
    const r = rng(`energy:${b.name}`);
    // ★ 面积缺了**不许写 0** —— `kWh / 0` 是 `Infinity`，印出来比缺更坏
    //   （铁律 123：`Infinity`/`NaN` 落进 JSON 就是裸的 `Infinity`，
    //    浏览器 `JSON.parse` 直接抛）。缺了就交 `null`，`table()` 印 `—`。
    const A = Number(b.outline_area_m2);
    const hasA = Number.isFinite(A) && A > 0;
    const eInt = 2.5 + r() * 9.5;      // kWh/m²·月
    const wInt = 0.02 + r() * 0.06;    // t/m²·月
    // ★ 面积缺 ⇒ 三个数**一起**缺。只缺面积却照印电耗，等于把「不知道这栋多大」
    //   伪装成「这栋用了这么多电」，而那正是上一版那个假数的来源。
    return {
      楼: labelOf(b),
      '面积': hasA ? A.toFixed(0) : null,
      '月用电 kWh': hasA ? (A * eInt).toFixed(0) : null,
      '月用水 t': hasA ? (A * wInt).toFixed(0) : null,
      // 这一列现在**就是强度本身**。`面积` 印的是 `toFixed(0)`，读者拿屏幕上两个数
      // 一除仍会有末位差 —— 那是显示精度（实测 92 行里 2 行），不是数据问题，
      // 不许当缺陷报（铁律 105：期望值要钉在被测对象真正读到的那个数上）。
      '单位面积电耗': hasA ? eInt.toFixed(2) : null,
      '同比': `${(r() * 30 - 14).toFixed(1)}%`,
    };
  });
}

/** 安防：每栋一行。 */
function ledgerSecurity(rows) {
  return rows.map((b) => {
    const r = rng(`security:${b.name}`);
    const fl = Number(b.floor_count) || 0;
    return {
      楼: labelOf(b),
      门禁点位: Math.round(2 + r() * 26),
      摄像机: Math.round(3 + r() * 40),
      消防栓: Math.round(4 + fl * (1 + r() * 3)),
      本月告警: Math.round(r() * 7),
    };
  });
}

/** 数据与流程：CD 图纸导入的派生任务。 */
function ledgerFlow(rows) {
  const STAGE = ['DWG 收图', 'DWG→DXF 重绘', '图层识别', '房间生成', '交付比对'];
  const out = [];
  rows.forEach((b, i) => {
    const r = rng(`flow:${b.name}`);
    const st = Math.floor(r() * STAGE.length);
    out.push({
      任务号: `T-${String(1001 + i).slice(1)}`,
      楼栋: labelOf(b),
      阶段: STAGE[st],
      状态: st === STAGE.length - 1 ? '完成' : (r() > 0.75 ? '等待审批' : '进行中'),
      提交: iso(Math.floor(r() * 90)),
      提交人: ['张工', '李工', '王工'][Math.floor(r() * 3)],
    });
  });
  return out;
}

// ────────────────────────────────────────────── 渲染小件

function table(cols, rows, numCols = []) {
  const t = el('table', { class: 'data' });
  const thead = el('thead', {}, el('tr', {}, ...cols.map((c) => el('th', { text: c }))));
  const tb = el('tbody');
  for (const r of rows) {
    tb.appendChild(el('tr', {}, ...cols.map((c) => {
      const v = r[c];
      const isNum = numCols.includes(c);
      return el('td', { class: isNum ? 'num' : '', text: v === null || v === undefined ? '—' : String(v) });
    })));
  }
  t.appendChild(thead); t.appendChild(tb);
  return t;
}

/** 一页的内容。★ 它按**形态**分成两摞，而不是按模块分成两摞。
 *
 *  · `sheet` —— `.cards` 与 `.strip` 在同一块板上**顺次往下排**（视觉与旧版一样：
 *      header → KPI → 小标题 → 表 → 注）。这一形态下"两摞"只是两个 div，没有样式。
 *  · `dash`  —— 两块**各自绝对定位**：`.cards` 是一列 396px 的卡、贴左上；
 *      `.strip` 是底部一条表带。中间那片**让给世界**（样式见 `portal.css` 的
 *      `.doc.hud.is-dash`，那里写着为什么必须拆）。
 *
 *  ★ 表格的去处由**形态**决定，不由模块决定：左列只有 396px，而
 *    `.doc table.data` 有 `min-width: 680px` —— 一张 7 列的表塞进卡片里
 *    只会横向溢出一条滚动条，而屏幕上看起来是"表被裁掉了"。
 */
function page(mod, form, tag, ...body) {
  const cards = el('div', { class: 'cards' });
  cards.appendChild(el('header', {},
    el('p', { class: 'kicker', text: tag }),
    el('h2', { text: mod.name }),
    el('p', { class: 'lede2', text: mod.desc }),
  ));
  const strip = el('div', { class: 'strip' });
  for (const b of body.flat()) {
    if (!b) continue;
    if (form === 'dash' && b.tagName === 'TABLE') strip.appendChild(b);
    else cards.appendChild(b);
  }
  const wrap = el('div', { class: 'paged' }, cards);
  // 没有表就不放这条空带 —— 空的 `34vh` 会白白吃掉一大片世界，
  // 而它看起来只是"底下留白多了点"。
  if (strip.firstChild) wrap.appendChild(strip);
  return wrap;
}

// ★ 模拟标注**必须留**（本仓的老规矩：模拟数不许被读成实测数，导轨上每个模块
//   也都带「实测/模拟」小字）。但只留那一件事 —— 原来那三句里，后两句是在向
//   **做这页的人**解释它为什么这么设计（用户 2026-10-01：只要功能）。
const MOCK_NOTE = () => note('模拟数据 · 固定种子推导，刷新不变 —— 不是实测值。', '');

// ────────────────────────────────────────────── 各模块

export function createModules(ctx) {
  // ★ 五张模拟台账的**主键来源**（实测）。
  //   为什么不复用 `ctx.roster`：那是 `API.roster()`，app.js 只在 `edit/manage`
  //   时取它 —— 一个 `viewer` 打开这五页会看到**空表**，而空表看起来像"没有设备"。
  //   `API.buildings()` 只要 `view` 权限，任何人都有。
  //   ★ **不缓存**：`createModules()` 整个会话只跑一次，在它外面存一份
  //     等于把"第一次打开这一页"的数冻住 —— 那之后刷新也刷不出新的
  //     （本仓铁律：进行中的数被当终值）。
  const rosterOf = () => API.buildings();

  const RENDER = {
    // 总览驾驶舱 = 正射影像那一屏（用户 2026-10-01：「纵览驾驶舱用正射影像图」）。
    // ★ 它原来是 `return null`（"总览 = 三维本身"）。三维没有消失 ——
    //   它挪到了自己的模块 `campus3d` 上。两个模块看的是同一份数据、不同的问题：
    //   三维看体量关系，这一屏看平面事实（轮廓压得准不准、坐标是多少）。
    overview: (mod) => renderOverview(mod),

    // 数据大屏：全校区一张图上挂满仪器（用户 2026-10-01：「点击大屏，
    // **所有的房屋都在上面显示**」）。与驾驶舱的分工写在 datascreen.js 的文件头上。
    datascreen: (mod) => renderDatascreen(mod),

    // 三维场景：没有文档页 —— 它**就是**世界本身（HUD 形态 `none`，
    // 见 `app.js` 的 `HUD_FORM`）。这里返回 `null` 是"这一块不占 HUD"，不是"没做"。
    campus3d() { return null; },

    /** 建筑与空间：**实测**。 */
    async building(mod, form) {
      const rows = await API.buildings();
      const nRooms = rows.reduce((s, r) => s + (Number(r.rooms) || 0), 0);
      const nFloor = rows.reduce((s, r) => s + (Number(r.floor_count) || 0), 0);
      const live = rows.filter((r) => r.has_model).length;
      // ★ 名录里那一列（`index.json` 的 `floors`）的合计 —— 与上面的 `nFloor` **不是同一个量**：
      //   那个是**建模实际落下的层**（盘上 `floors/floor*.json` 的份数），
      //   这个是人**登记**的层数。实测两者差 4 层，而屏幕上如果都叫"楼层合计"，
      //   读的人只能自己挑一个信，多半还会挑错。
      //   所以：① 这一格改名叫「盘上交付层数」；② 差额在这里**算出来**并印出来。
      //   ★ 差值是 `nReg - nFloor`，两个数都来自**这次**的响应 —— 不许手打（铁律 105/174）。
      const nReg = ctx.overview?.roster?.n_floors;
      const nRegB = ctx.overview?.roster?.n_buildings;
      const gap = Number.isFinite(nReg) ? nReg - nFloor : null;
      const gapB = Number.isFinite(nRegB) ? nRegB - rows.length : null;
      return page(mod, form, '实测 · 盘上 data/buildings/',
        statBox([
          [`${rows.length}`, '盘上交付栋数'],
          [`${nFloor}`, '盘上交付层数'],
          [`${int(nRooms)}`, '房间合计'],
          [`${live}`, '有三维模型'],
        ]),
        el('div', { class: 'doc-actions' },
          el('span', { class: 'busy', text: '定位一栋：在左边点它的体块（前提是已锚定）。' })),
        table(['name', 'title', 'floor_count', 'rooms', 'outline_area_m2', 'has_model'], rows
          .slice().sort((a, b) => (b.outline_area_m2 ?? 0) - (a.outline_area_m2 ?? 0)),
          ['floor_count', 'rooms', 'outline_area_m2']),
        note('按轮廓面积降序；行已按你的权限范围过滤。'),
        // ★ 这一段里**不许出现 `**` 或反引号**：`note()` 走的是 `textContent`，
        //   它**不解析 markdown** —— 写进去的星号会原样上屏（见 dom.js 的规矩：
        //   "要强调就加 <b>/<em> 节点"）。这里改用本仓惯用的 ★ 与「」分层。
        //
        // ★ 「两个来源、名字里带出处」这一段**不许删**：它挡的是"两处同名不同数"。
        //   删掉之后屏幕上只会剩两个都叫「层数」的数，而两个都像真的。
        //   但解释**为什么会有差**的那三句删了（用户 2026-10-01：只要功能）——
        //   只留一句"差是实的、不是算错"，够读了。
        (gap === null && gapB === null) ? null : ((gap === 0 && gapB === 0)
          ? note(`名录登记与盘上交付，这次两个数都相等。`, 'ok')
          : note(`★ 两个来源，四个数（都是这一趟现读的，差是实的、不是算错）：`
            + `栋数：盘上交付 ${rows.length}（就是这一页的行）／名录登记 ${nRegB}；`
            + `层数：盘上交付 ${nFloor}（上面那一格）／名录登记 ${nReg}。`, '')),
      );
    },

    async facility(mod, form) {
      const rows = ledgerFacility(await rosterOf());
      // ★★ 缺面积的楼，那三列是 `null` —— 而 `0 + null` 在 JS 里是 `0`，
      //   于是 `reduce` **静默**把"不知道"当成"0 台"加进去，屏幕上只有一个小了的合计
      //   （铁律 144：「读不到」不是「一致」/不是 0；铁律 062：分档要让「不适用」出声）。
      //   ⇒ 先把缺的行数出来，缺了就**在合计旁边点名**，不许安静地算小。
      const missing = rows.filter((r) => r.台数 === null).length;
      const n = rows.reduce((s, r) => s + (r.台数 ?? 0), 0);
      const bad = rows.reduce((s, r) => s + (r.待修 ?? 0), 0);
      const tail = missing ? `（另有 ${missing} 条因**楼栋面积缺失**未计入）` : '';
      return page(mod, form, '模拟 · 设施设备台账',
        statBox([[`${rows.length}`, '台账条目'], [`${int(n)}${missing ? '＋' : ''}`, '设备总台数'],
                 [`${bad}`, '待修'], [`${new Set(rows.map((r) => r.所在)).size}`, '涉及楼栋']]),
        // ★ 把「面积」印出来的**理由**：这一列是「台数」的来源，两列并排，
        //   读的人自己就能核「这栋多大、装了几台」—— 一眼看得出这数假不假。
        //   藏起来的话，同一个假数只能靠读代码才发现（铁律 167：把工具自己的
        //   记录原样摆上去，是唯一能自动抓住这类错的探针）。
        table(['设备', '所在', '面积', '台数', '在用', '待修', '最近维保'], rows,
          ['台数', '在用', '待修']),
        missing ? note(`★ ${missing} 条台账条目**没有计入合计** —— 那几栋在名册里没有面积，`
          + `无从推算台数。这里报的是「我没量到」，不是「那里没有设备」。`, '') : null,
        MOCK_NOTE(),
      );
    },

    async energy(mod, form) {
      const rows = ledgerEnergy(await rosterOf());
      const kwh = rows.reduce((s, r) => s + Number(r['月用电 kWh']), 0);
      return page(mod, form, '模拟 · 分楼分项',
        statBox([[`${int(kwh)}`, '月用电 kWh'],
                 [`${int(rows.reduce((s, r) => s + Number(r['月用水 t']), 0))}`, '月用水 t'],
                 [`${rows.length}`, '计量点'],
                 [`${(kwh / 10000).toFixed(1)}`, '万 kWh']]),
        table(['楼', '面积', '月用电 kWh', '月用水 t', '单位面积电耗', '同比'], rows,
          ['面积', '月用电 kWh', '月用水 t', '单位面积电耗']),
        MOCK_NOTE(),
      );
    },

    async security(mod, form) {
      const rows = ledgerSecurity(await rosterOf());
      return page(mod, form, '模拟 · 点位与告警',
        statBox([
          [`${rows.reduce((s, r) => s + r.门禁点位, 0)}`, '门禁点位'],
          [`${rows.reduce((s, r) => s + r.摄像机, 0)}`, '摄像机'],
          [`${rows.reduce((s, r) => s + r.消防栓, 0)}`, '消防栓'],
          [`${rows.reduce((s, r) => s + r.本月告警, 0)}`, '本月告警'],
        ]),
        table(['楼', '门禁点位', '摄像机', '消防栓', '本月告警'], rows,
          ['门禁点位', '摄像机', '消防栓', '本月告警']),
        MOCK_NOTE(),
      );
    },

    async pipeline_flow(mod, form) {
      const rows = ledgerFlow(await rosterOf());
      return page(mod, form, '模拟 · 图纸导入与派生任务',
        statBox([
          [`${rows.length}`, '任务'],
          [`${rows.filter((r) => r.状态 === '完成').length}`, '已完成'],
          [`${rows.filter((r) => r.状态 === '进行中').length}`, '进行中'],
          [`${rows.filter((r) => r.状态 === '等待审批').length}`, '等待审批'],
        ]),
        table(['任务号', '楼栋', '阶段', '状态', '提交', '提交人'], rows),
        MOCK_NOTE(),
      );
    },

    /** 账号与权限：**实测**，且只有 manage 能看。 */
    async iam(mod, form) {
      // 一个请求拿两样（后端 `/api/auth/users` 就是回 `{users, roles}`）。
      // 分两次取会得到两份各自带时刻的快照，而这一屏讲的正是"谁有什么"。
      const u = await API.users();
      const users = u?.users ?? [];
      const roles = u?.roles ?? [];
      const t = el('table', { class: 'data' });
      t.appendChild(el('thead', {}, el('tr', {},
        el('th', { text: '账号' }), el('th', { text: '姓名' }),
        el('th', { text: '状态' }), el('th', { text: '授权（角色@范围）' }),
        el('th', { text: '最近登录' }))));
      const tb = el('tbody');
      for (const x of users) {
        tb.appendChild(el('tr', {},
          el('td', { text: x.username }),
          el('td', { text: x.display_name ?? '' }),
          el('td', {}, x.is_active === false ? chip('停用', 'off') : chip('在用', 'live'),
            x.must_change ? chip('需改密', 'mock') : ''),
          el('td', { text: (x.grants ?? []).map((g) => `${g.role_code}@${g.scope_node}`).join('、') || '—' }),
          el('td', { text: (x.last_login_at ?? '') || '从未' }),
        ));
      }
      t.appendChild(tb);

      const rt = el('table', { class: 'data' });
      rt.appendChild(el('thead', {}, el('tr', {},
        el('th', { text: '角色码' }), el('th', { text: '名称' }),
        el('th', { text: '能力' }), el('th', { text: '说明' }))));
      const rtb = el('tbody');
      for (const x of roles) {
        rtb.appendChild(el('tr', {},
          el('td', { text: x.code }), el('td', { text: x.name }),
          el('td', { text: (x.caps ?? []).join(' / ') }), el('td', { text: x.description ?? '' })));
      }
      rt.appendChild(rtb);

      return page(mod, form, '实测 · 库里的 users / roles / grants',
        statBox([[`${users.length}`, '账号'], [`${roles.length}`, '角色'],
                 [`${users.filter((x) => x.is_active === false).length}`, '已停用'],
                 [`${users.filter((x) => x.must_change).length}`, '待改初始口令']]),
        el('h3', { class: 'sub', text: '账号' }), t,
        el('h3', { class: 'sub', text: '角色与能力' }), rt,
        // ★ 这一句留着的理由：不说，人会在这一屏上找"新建账号"那个按钮。
        note('本屏只读 —— 开号 / 停用 / 重置口令 / 加撤授权的接口都有，界面还没接。'),
      );
    },
  };

  return {
    has(key) { return Object.prototype.hasOwnProperty.call(RENDER, key); },
    async render(host, key, mod, form) {
      const f = RENDER[key];
      if (!f) {
        fill(host, note(`模块 ${key} 还没有页面。`, 'err'));
        return;
      }
      fill(host, el('p', { class: 'busy', text: '读取中…' }));
      try {
        const node = await f(mod, form);
        if (node) fill(host, node);
        else fill(host);
      } catch (e) {
        // ★ 三种失败必须分开说：没权限 / 后端坏了 / 网络断了。
        //   合成一句"加载失败"会把人引去做无用功（去查后端，其实是没权限）。
        const msg = e instanceof ApiError
          ? (e.status === 403 ? `这个模块需要更高的权限：${e.message}`
            : e.status === 401 ? '会话已失效，请重新登录。'
              : `读不到：${e.message}`)
          : String(e);
        fill(host, note(msg, 'err'));
      }
    },
  };
}

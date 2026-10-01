// 各模块的页面内容。
//
// ★ 这一份里**每一块都自己声明它是实测还是模拟**，而且声明**印在屏幕上**：
//     · 「建筑与空间」「账号与权限」—— 走真实接口，来源是盘上的
//       `data/buildings/`（92 栋、房间表）与库里的 `users/roles/grants`。
//     · 设施 / 管网与回线 / 能耗 / 安防 / 数据与流程 —— **模拟**。
//       数不是随便编的：由**固定种子**从体块参数推出来（见 `blocks.js` 的 `rng`），
//       刷新不变、换机器也不变。这么做不是为了好看 —— 一个每次刷新都变的数
//       看起来比一个固定的数更"真"，而它同样是编的。
//
// ★ 「回线」这个词**照抄用户原话**（用户写的是"井、通道、线以及回线"），
//   没有改成"管线"。它到底指什么还没确认 —— 在确认之前，
//   改动这个词就等于把用户的定义换成了我的猜测，而那不会报错。

import { API, ApiError } from './api.js';
import { el, fill, kv, block, chip, note, num, int } from './dom.js';
import { rng } from './blocks.js';
import { renderOverview } from './cockpit.js';
import { renderDatascreen } from './datascreen.js';

// ────────────────────────────────────────────── 模拟台账

const DEVICES = ['电梯', '多联机空调', '新风机组', '配电柜', '生活水泵', '消防泵',
                 '锅炉', '空压机', 'UPS', '弱电柜'];
const PIPE_KINDS = ['井', '通道', '线', '回线'];
const PIPE_OWNER = ['后勤保障处', '基建处', '网络与信息中心', '国有资产管理处'];

function iso(dayOffsetFromToday) {
  const d = new Date();
  d.setDate(d.getDate() - dayOffsetFromToday);
  return d.toISOString().slice(0, 10);
}

/** 设施设备：每块挑 2~4 类设备。 */
function ledgerFacility(blocks) {
  const rows = [];
  for (const b of blocks) {
    const r = rng(`facility:${b.id}`);
    const k = 2 + Math.floor(r() * 3);
    // ★ 选设备**不许**写 `sort(() => r() - 0.5)`：那个比较器不满足传递性，
    //   `Array.prototype.sort` 对不一致的比较器**结果由实现决定** ——
    //   于是"换机器同一组数"这个承诺当场失效，而屏幕上没有任何变化。
    //   改成给每台设备一个**一次算定的键**，再按键排。
    const picked = DEVICES
      .map((d) => [d, rng(`facility:${b.id}:${d}`)()])
      .sort((x, y) => x[1] - y[1])
      .slice(0, k)
      .map(([d]) => d);
    for (const dev of picked) {
      const n = 2 + Math.floor(r() * 40);
      const bad = Math.floor(r() * Math.max(1, n / 12));
      rows.push({
        设备: dev, 所在: `${b.id} ${b.use.split(' ')[0]}`,
        台数: n, 在用: n - bad, 待修: bad,
        最近维保: iso(10 + Math.floor(r() * 300)),
      });
    }
  }
  return rows;
}

/** 管网与回线：每块 1~3 段。 */
function ledgerPipeline(blocks) {
  const rows = [];
  let i = 0;
  for (const b of blocks) {
    const r = rng(`pipeline:${b.id}`);
    const k = 1 + Math.floor(r() * 3);
    for (let j = 0; j < k; j++) {
      i += 1;
      const kind = PIPE_KINDS[Math.floor(r() * PIPE_KINDS.length)];
      rows.push({
        编号: `${kind === '井' ? 'J' : kind === '通道' ? 'TD' : kind === '线' ? 'X' : 'HX'}-${String(i).padStart(3, '0')}`,
        类型: kind,
        所在: b.id,
        长度: kind === '井' ? null : (20 + r() * 380).toFixed(1),
        埋深: (0.6 + r() * 3.4).toFixed(2),
        权属: PIPE_OWNER[Math.floor(r() * PIPE_OWNER.length)],
        巡检: r() > 0.82 ? '待巡检' : '正常',
      });
    }
  }
  return rows;
}

/** 能耗：每块一行。 */
function ledgerEnergy(blocks) {
  return blocks.map((b) => {
    const r = rng(`energy:${b.id}`);
    const kWh = 4000 + r() * 46000;
    const t = 120 + r() * 2600;
    return {
      楼: `${b.id} ${b.use.split(' ')[0]}`,
      '面积': b.area_m2.toFixed(0),
      '月用电 kWh': kWh.toFixed(0),
      '月用水 t': t.toFixed(0),
      '单位面积电耗': (kWh / b.area_m2).toFixed(2),
      '同比': `${(r() * 30 - 14).toFixed(1)}%`,
    };
  });
}

/** 安防：每块一行。 */
function ledgerSecurity(blocks) {
  return blocks.map((b) => {
    const r = rng(`security:${b.id}`);
    return {
      楼: `${b.id} ${b.use.split(' ')[0]}`,
      门禁点位: Math.round(2 + r() * 26),
      摄像机: Math.round(3 + r() * 40),
      消防栓: Math.round(4 + b.floors * (1 + r() * 3)),
      本月告警: Math.round(r() * 7),
    };
  });
}

/** 数据与流程：CD 图纸导入的派生任务。 */
function ledgerFlow(blocks) {
  const STAGE = ['DWG 收图', 'DWG→DXF 重绘', '图层识别', '房间生成', '交付比对'];
  const rows = [];
  blocks.forEach((b, i) => {
    const r = rng(`flow:${b.id}`);
    const st = Math.floor(r() * STAGE.length);
    rows.push({
      任务号: `T-${String(1001 + i).slice(1)}`,
      楼栋: `${b.id} ${b.use.split(' ')[0]}`,
      阶段: STAGE[st],
      状态: st === STAGE.length - 1 ? '完成' : (r() > 0.75 ? '等待审批' : '进行中'),
      提交: iso(Math.floor(r() * 90)),
      提交人: ['张工', '李工', '王工'][Math.floor(r() * 3)],
    });
  });
  return rows;
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

function page(mod, tag, ...body) {
  const wrap = el('div');
  wrap.appendChild(el('header', {},
    el('p', { class: 'kicker', text: tag }),
    el('h2', { text: mod.name }),
    el('p', { class: 'lede2', text: mod.desc }),
  ));
  for (const b of body.flat()) if (b) wrap.appendChild(b);
  return wrap;
}

function statBox(pairs) {
  const s = el('div', { class: 'stats' });
  for (const [v, k] of pairs) {
    const c = el('div', {}, el('b', { text: v }), el('small', { text: k }));
    s.appendChild(c);
  }
  return s;
}

// ★ 模拟标注**必须留**（本仓的老规矩：模拟数不许被读成实测数，导轨上每个模块
//   也都带「实测/模拟」小字）。但只留那一件事 —— 原来那三句里，后两句是在向
//   **做这页的人**解释它为什么这么设计（用户 2026-10-01：只要功能）。
const MOCK_NOTE = () => note('模拟数据 · 固定种子推导，刷新不变 —— 不是实测值。', '');

// ────────────────────────────────────────────── 各模块

export function createModules(ctx) {
  const blocksOf = () => (ctx.scene?.state?.blocks ?? []).filter((b) => !b.unplaced);

  const RENDER = {
    // 总览驾驶舱 = 正射影像那一屏（用户 2026-10-01：「纵览驾驶舱用正射影像图」）。
    // ★ 它原来是 `return null`（"总览 = 三维本身"）。三维没有消失 ——
    //   它挪到了自己的模块 `campus3d` 上。两个模块看的是同一份数据、不同的问题：
    //   三维看体量关系，这一屏看平面事实（轮廓压得准不准、坐标是多少）。
    overview: (mod) => renderOverview(mod),

    // 数据大屏：全校区一张图上挂满仪器（用户 2026-10-01：「点击大屏，
    // **所有的房屋都在上面显示**」）。与驾驶舱的分工写在 datascreen.js 的文件头上。
    datascreen: (mod) => renderDatascreen(mod),

    // 三维场景：没有文档页 —— 它**就是**画布本身（rail 上点它，右侧文档区让位给 #canvas-wrap）。
    campus3d() { return null; },

    /** 建筑与空间：**实测**。 */
    async building(mod) {
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
      return page(mod, '实测 · 盘上 data/buildings/',
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

    facility(mod) {
      const rows = ledgerFacility(blocksOf());
      const n = rows.reduce((s, r) => s + r.台数, 0);
      const bad = rows.reduce((s, r) => s + r.待修, 0);
      return page(mod, '模拟 · 设施设备台账',
        statBox([[`${rows.length}`, '台账条目'], [`${int(n)}`, '设备总台数'],
                 [`${bad}`, '待修'], [`${new Set(rows.map((r) => r.所在)).size}`, '涉及体块']]),
        table(['设备', '所在', '台数', '在用', '待修', '最近维保'], rows,
          ['台数', '在用', '待修']),
        MOCK_NOTE(),
      );
    },

    pipeline(mod) {
      const rows = ledgerPipeline(blocksOf());
      const byKind = {};
      for (const r of rows) byKind[r.类型] = (byKind[r.类型] ?? 0) + 1;
      return page(mod, '模拟 · 井、通道、线与回线',
        statBox([
          [`${rows.length}`, '管网条目'],
          [`${byKind['井'] ?? 0}`, '井'],
          [`${byKind['通道'] ?? 0}`, '通道'],
          [`${(byKind['线'] ?? 0) + (byKind['回线'] ?? 0)}`, '线 / 回线'],
        ]),
        // ★ 这一句**不许删**：它是"这个词还没定"的唯一凭据（用户原话里就有
        //   「井、通道、线以及回线」）。删掉它，「回线」这个标签在屏幕上
        //   与别的标签就再没有区别了。
        note('「回线」照抄需求原话，含义待确认。'),
        table(['编号', '类型', '所在', '长度', '埋深', '权属', '巡检'], rows,
          ['长度', '埋深']),
        MOCK_NOTE(),
      );
    },

    energy(mod) {
      const rows = ledgerEnergy(blocksOf());
      const kwh = rows.reduce((s, r) => s + Number(r['月用电 kWh']), 0);
      return page(mod, '模拟 · 分楼分项',
        statBox([[`${int(kwh)}`, '月用电 kWh'],
                 [`${int(rows.reduce((s, r) => s + Number(r['月用水 t']), 0))}`, '月用水 t'],
                 [`${rows.length}`, '计量点'],
                 [`${(kwh / 10000).toFixed(1)}`, '万 kWh']]),
        table(['楼', '面积', '月用电 kWh', '月用水 t', '单位面积电耗', '同比'], rows,
          ['面积', '月用电 kWh', '月用水 t', '单位面积电耗']),
        MOCK_NOTE(),
      );
    },

    security(mod) {
      const rows = ledgerSecurity(blocksOf());
      return page(mod, '模拟 · 点位与告警',
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

    pipeline_flow(mod) {
      const rows = ledgerFlow(blocksOf());
      return page(mod, '模拟 · 图纸导入与派生任务',
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
    async iam(mod) {
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

      return page(mod, '实测 · 库里的 users / roles / grants',
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
    /** 有些模块要盖住三维（文档型），有些不要 —— 现在**只有**三维场景那一块不要。 */
    isDoc(key) { return key !== 'campus3d'; },
    async render(host, key, mod) {
      const f = RENDER[key];
      if (!f) {
        fill(host, note(`模块 ${key} 还没有页面。`, 'err'));
        return;
      }
      fill(host, el('p', { class: 'busy', text: '读取中…' }));
      try {
        const node = await f(mod);
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

// 纵览驾驶舱 —— 用户 2026-10-01：「纵览驾驶舱用正射影像图」。
//
// 这一屏和「三维场景」分工不同，而不是新旧两版：
//   · 三维场景 —— 看**体量关系**：谁高谁矮、操场在哪儿、坡往哪边落。
//   · 纵览驾驶舱（本页）—— 看**平面事实**：轮廓压在哪、占地多大、坐标是多少。
//     影像 0.8 m/px 铺满屏时，一栋楼是几十个像素的实物照；压在它上面的轮廓
//     错没错一眼就能看出来。三维里同样的错会被透视和光照吃掉。
//
// ★★ 轮廓换过一茬（2026-10-01）。原来画的是 `campus_lod1_blocks.json` ——
//   213 个 DSM − DTM 挤出来的**派生物块**，当时只因为它有一条现成的 API 路由。
//   实测：中位底面积 131 m²、中位高 4.2 m，最小的一批压在马路 / 绿化带 / 转盘 /
//   工地围挡上，**根本不是楼的轮廓**；只有约 13 个 663~2450 m² 的大块真在楼上。
//   而这一页当时印着"轮廓压在楼上"。**判词与数据不符** —— 这不是画得好不好看的问题，
//   是它会让人拿一张错的地图下判断。
//   现用的是 `campus_outlines.json`：341 条渠东 1:500 图上描的**实测轮廓**，
//   与三维场景里的 `campus_buildings.glb` 同一份输入（四条判据全过，包围盒差 0.4 mm）。
//   ★ 代价要说清楚：**它只覆盖渠东那一片**（1392 × 1644 m）。图外的大房子
//     （六教 / 理工宾馆 / 八教 / 综合实验楼实测都在这份之外）**没有轮廓** ——
//     那句话必须印在屏幕上，不然"图上没轮廓"会被读成"那里没有房子"。

import { API } from './api.js';
import { el, fill, note, rich, int, num, statBox, caliber } from './dom.js';
import { loadOrthoBase } from './ortho-base.js';
import { createOrthoMap } from './ortho-map.js';

// ★ 同一个理由：数据大屏也要印 dt/dd 两栏事实，而"值可以是个节点（走 rich()）"
//   这条规矩必须只有一处实现 —— 两处实现必然有一处忘了认节点，
//   那一处的表现是**屏幕上多出两个裸星号**，而代码和判据都不出声。
export function kvList(pairs) {
  const dl = el('dl', { class: 'kv' });
  for (const [k, v] of pairs) {
    if (v === undefined) continue;
    // ★ 值允许是**节点** —— 走 `rich()` 的**作者文字**（里面 `**` 要变加粗）。
    //   不是节点就按数据走 `String(v)`：数据里的 `**` 是星号，不是标记。
    //   不给这一条的话，凡是"作者写了一句带强调的口径说明"放进 kv 的地方，
    //   屏幕上都只剩两个裸星号，而没有任何一步会出声。
    const empty = v === null || v === '';
    dl.appendChild(el('dt', { text: k }));
    dl.appendChild(v instanceof Node ? el('dd', {}, v)
      : el('dd', { class: empty ? 'na' : '', text: empty ? '未填' : String(v) }));
  }
  return dl;
}

/** 「这一条轮廓」的事实。★ 只印**量得出来的**：形状、面积、高度、地面高程。
 *  绝不印"这是几号楼" —— 环号与楼栋名之间目前没有任何在盘上成立的对应关系
 *  （那正是人工锚点表要做的事）。 */
function blockFacts(b) {
  if (!b) return note('点底图上的一条轮廓。');
  // ★ 那 94 条的 `h_m` **不是楼高**（源数据层的原话："这个 h 不是楼高，是地高，
  //   读它等于读空地"）。同一个标签印不同的量 = 铁律 124 —— 一个名字两个量，
  //   而屏幕上印出来的数照样像结论。所以这里**换标签**，不是加个星号了事。
  const isGround = b.height_caliber === 'fallback_ground';
  return el('div', { class: 'facts' },
    el('h4', {}, el('span', { text: b.id ?? b.ring }),
      el('em', { text: isGround ? '实测轮廓 · 疑非楼' : '实测轮廓' })),
    kvList([
      // ★ 短号与全号都印：短号是**图上那条标签**，全号是**它在这份数据里的身份**
      //   （源 npz 里的键）。只印一个的话，读的人对不上图上那条线是哪一行 ——
      //   而"同一个东西两种写法"正是本仓有过教训的那类歧义。
      ['环号（源里的键）', b.ring ?? b.id],
      ['底面积', Number.isFinite(b.area_m2) ? `${num(b.area_m2, 1)} m²` : null],
      [isGround ? '地面高（不是楼高）' : '屋顶高',
        Number.isFinite(b.h_m) ? `${num(b.h_m, 1)} m` : null],
      // ★ 走 `rich()`：这三个口径的说明是**作者文字**，里面的 `**` 是判词关键词。
      //   直接塞字符串的话，屏幕上会印出 `这个数**不是楼高，是地高**` —— 两个裸星号。
      //   未知口径（源里冒出第四档）就印原码，别印空 —— 空看起来像"未填"，
      //   而"台面上出现了一个我从没见过的口径码"是另一件事，值得被看见。
      ['高度口径', CALIBER[b.height_caliber]
        ? rich(CALIBER[b.height_caliber]) : (b.height_caliber ?? null)],
      ['所在地面', Number.isFinite(b.ground_med_m) ? `${num(b.ground_med_m, 1)} m（椭球高）` : null],
      ['落在 NoData 洞上', b.on_hole ? '是 —— 这一带没有实测地面' : '否'],
      ['轮廓顶点数', b.n_vertices],
    ]),
  );
}

// 高度口径的说明 —— ★ 这三个定义是**从 `campus_buildings_viewdata.json` 的 note 里
// 抄回来的原话**，不是我按名字猜的。第一版我在这里写的是「地面点缺测，用邻域地面
// 回填」—— 听着合理，而**源文件说的完全是另一件事**：
//     roof_p50        屋顶格够多，量的是屋顶                                    231 条
//     fallback_roof   屋顶格不足 5，但屋顶格占比 > 10% ⇒ 有效楼高，只是分位位置随占比漂  16 条
//     fallback_ground 屋顶格占比 ≤ 10% ⇒ p90 落进**地**那一坨 ⇒ **这个 h 不是楼高，
//                     是地高，读它等于读空地**                                   94 条
// ⇒ 341 条里只有 247 条（231+16）真的带楼高；那 94 条的 h 实测中位正好是 0.0 m。
//   铁律 141：字段的名字不是它的定义；判据的合法性要靠"谁写它"证明。
// ★ 条数**不写在这里**。原先这三行末尾各带一个手打的数（231 / 16 / 94）——
//   那是**一次测量的快照**，数据一变它就过期，而屏幕上照印不误（铁律 174：
//   手打的计数只在清单长到 N+1 那一刻才第一次出声，而那一刻它长得像"被测对象坏了"）。
//   屏幕上要数，去 KPI 那一行与「高度口径」那一格读 —— 那两个是现算的。
const CALIBER = {
  roof_p50:        '屋顶格 p50（量的就是屋顶）',
  fallback_roof:   '有效楼高（屋顶格不足 5 个，分位随占比漂）',
  fallback_ground: '★ 地高 —— **不是楼高**',
};

// ★ 留一份引用**不是为了用它**：`ResizeObserver` 只被这个对象持有，
//   丢掉返回值它就可能被回收 —— 而画布会**停止跟随窗口大小**，
//   拖窗口时图不动，也不报任何错。重画之前先把上一份拆掉（否则监听器会越积越多）。
let liveMap = null;

export async function renderOverview(mod) {
  let sel = null;
  liveMap?.destroy();
  liveMap = null;
  {
      // ★★ 版面：`page()` 那一套两块板（左列卡 + 一块插图），**不是**一整幅盖满的
      //   页面。为什么改、改成什么，见 `app.js` 的 `HUD_FORM.overview` 那条注释；
      //   样式在 `portal.css` 的 `.doc.hud.is-map`。
      //   ★ 这里**自己拼**而不是调 `page()`：这一页的左列不是"标题 + 数字 + 表"，
      //     它的正文是一张会自己重绘的画布 —— 塞进 `page()` 的 body 反而要把它再抠出来。
      const cards = el('div', { class: 'cards' });
      cards.appendChild(el('header', {},
        el('p', { class: 'kicker', text: '实测 · 校区正射影像 0.8 m/px（与三维场景同一张）' }),
        el('h2', { text: mod.name }),
        el('p', { class: 'lede2', text: mod.desc })));

      const mapHost = el('div', { class: 'cockpit-map' });
      const side = el('aside', { class: 'cockpit-side' });
      const strip = el('div', { class: 'strip' }, mapHost);
      const wrap = el('div', { class: 'paged' }, cards, strip);
      fill(mapHost, el('p', { class: 'busy', text: '读取底图与帧…' }));
      fill(side, blockFacts(null));

      let base;
      try {
        base = await loadOrthoBase();
      } catch (e) {
        fill(mapHost, el('div', {},
          el('p', { class: 'kicker', text: '底图没起来' }),
          note(String(e?.message ?? e), 'err')));
        return wrap;
      }

      // ── KPI ─────────────────────────────────────────────────────────
      // ★ 楼栋与房间那两格走 `/api/buildings`（**逐行按范围过滤**）——
      //   与「建筑与空间」同一把尺子。这一屏上不许出现第二个口径的栋数。
      let nBuild = null, nRoom = null, bErr = null;
      try {
        const rows = await API.buildings();
        nBuild = rows.length;
        nRoom = rows.reduce((s, r) => s + (Number(r.rooms) || 0), 0);
      } catch (e) { bErr = e; }

      const f = base.facts;
      // ★ 顺序是**读的顺序**：标题 → 六个数 → 会改变判断的边界 → 选中的那一条。
      //   改版前这六格是 `wrap.insertBefore(..., grid)`，插在**网格前面**；
      //   现在正文只有一列，直接 `append` 就是那个顺序，少一层绕。
      cards.appendChild(statBox([
        [f.imageM ? `${(f.imageM[0] / 1000).toFixed(2)}×${(f.imageM[1] / 1000).toFixed(2)}` : '—', '底图覆盖 km'],
        [Number.isFinite(f.nRoof) ? `${f.nRoof}／${f.nBlocks}` : `${f.nBlocks}`,
          Number.isFinite(f.nRoof) ? '带楼高 ／ 轮廓总条数' : '实测轮廓 · 条'],
        [`${int(f.areaSumRoof)}`, '带楼高那部分建面合计 m²'],
        [Number.isFinite(f.hMin) ? `${num(f.hMin, 1)}~${num(f.hMax, 1)}` : '—', '屋顶高 m'],
        [nBuild === null ? '—' : `${nBuild}`, '盘上交付栋数'],
        [nRoom === null ? '—' : int(nRoom), '房间合计'],
      ]));

      // ★ 选中那一条的落点**紧跟 KPI**（2026-10-02 挪的）。它空着的时候，里面装的是
      //   `blockFacts(null)` 那句「点底图上的一条轮廓。」—— 那是这一屏**唯一**在教
      //   用户怎么操作的句子，而它原来排在可滚动列表的**最后一个**位置，被
      //   `div.cards` 的 `overflow:auto` 整个裁在框外（量出来的：它的中心点在外，
      //   `_p3_contrast.py` 的 `cut` 那一档点名印的，见铁律 190）。
      //   ⇒ 教学句不能要人先滚动才看得见。
      cards.appendChild(side);

      // ── 两个来源的核对结论（有问题就**印在图上**，不藏）──────────────
      if (base.problems.length) {
        cards.appendChild(note('★ 这一趟量到 ' + base.problems.length + ' 处不自洽：'
          + base.problems.join('／'), 'err'));
      }
      if (bErr) {
        cards.appendChild(note(`楼栋与房间那两格没取到（${bErr.message}）——`
          + '其余各格是这一趟现读的，不受影响。', 'err'));
      }

      // ── 覆盖边界 → 口径抽屉 ─────────────────────────────────────────
      // ★ 用户 2026-10-01：「现在每个页面有很多解释，这些没有啥用吧，只要功能」。
      //   这里原先挂着两张**出处卡**（「底图出处」9 行 + 「轮廓出处」13 行：
      //   判据版本 / 各段 sha256 / GLB 字节 / 判据容差 / 换源历史），
      //   那是**给做这页的人看的**，不是给用这张图的人看的 —— 删掉。
      //   留下的只有读数（KPI 那一行）与那条**会改变判断**的覆盖边界。
      // ★ 2026-10-02：那条边界本身也从**屏上**挪进了抽屉。它不是装饰 —— 不知道它，
      //   「图上没有轮廓」会被读成「那里没有房子」；但它是**成段说明文字**，
      //   而第②条验收明令屏上不许有（`_p2_shots.py` 的 B 腿就是量这个的）。
      //   ⇒ 默认收起，屏幕上只剩一行写明「里面是什么」的标题。
      const bb = base.facts.olBbox;
      cards.appendChild(caliber('口径 · 轮廓的覆盖范围与读法', note(
        bb
          ? '**覆盖只有图中间那一片**：'
            + `E ${bb.e0.toFixed(0)}~${bb.e1.toFixed(0)}、N ${bb.n0.toFixed(0)}~${bb.n1.toFixed(0)}`
            + '（渠东 1:500 图）。**图上没有线 ≠ 那里没有房子**。'
          : '读不到轮廓的覆盖范围 —— 先别拿它当下判断。',
        bb ? '' : 'err')));

      /** 侧栏的唯一重绘入口。（两段出处已按口径删掉，这里只剩选中的那一条。） */
      const paintSide = () => { fill(side, blockFacts(sel)); };
      paintSide();

      // ── 画布 ────────────────────────────────────────────────────────
      // ★ 单独包一层 try：`createOrthoMap` 拿不到图像尺寸时会**主动抛**。
      //   必须包，因为那条路的失败形态是"安静地画一张 1:1 的图"（见 ortho-map.js 里
      //   那段注释），所以它宁可死；而死掉这件事必须变成屏幕上的一句话，
      //   不能是一个没人接的异常 + 一块空白画布。
      try {
        liveMap = createOrthoMap(mapHost, base, {
          onPick: (b) => { sel = b; paintSide(); },
        });
      } catch (e) {
        fill(mapHost, el('div', {},
          el('p', { class: 'kicker', text: '画布没起来' }),
          note(String(e?.message ?? e), 'err')));
        return wrap;
      }
      return wrap;
  }
}

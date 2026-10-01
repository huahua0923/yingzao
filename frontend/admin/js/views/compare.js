// 影像比对 —— 本机照片 ↔ 高德卫星，**配对是算出来的**。
//
// ★ 这一屏回答的是「我们建出来的东西，跟真实场地对得上吗」：
//   照片是**在地面上拍的**（有 EXIF 坐标），卫星图是**从天上看的**。
//   两边各自独立，谁也不是从谁派生的 —— 这才是能互证的两份证据。
//
// ★ 配对怎么来的（这是本屏可信度的全部）：照片的 EXIF GPS 是 **WGS-84**，
//   而高德瓦片是 **GCJ-02** 网格，两者在本仓实测差约 **360 m**。直接把 WGS 坐标
//   当 GCJ 用，图上会偏出小半个街区 —— 而**屏幕上完全看不出来**（两边都是
//   干净的卫星图/照片，没有一处会喊"我偏了"）。所以服务端那侧一律先
//   `wgs84_to_gcj02` 再算瓦片号；本视图只负责摆放，不重算坐标。
//
// ★ 三条不许糊的地方：
//   · **占位块**：z≥19 高德会回 HTTP 200 + 正确 JPEG 魔数 + 256×256 的
//     「此区域无卫星图」占位块 —— 朴素检查全过。这里把「瓦片 N 块里占位 M 块」
//     印在顶上（清单里就有）—— 静默贴上就等于把「超出影像覆盖」说成「这儿没东西」。
//   · **不在大图范围内**的配对单独数出来：它和大图里没画点是两件事
//     （一个是"范围外"，一个是"我漏画了"）。所以数两遍、分两句写。
//   · 出图失败时**把服务端那句话原样显示**，不许只给一个裂图：
//     404（清单里没这个键）与 409（键对、但文件跟你建清单时不是同一份了）
//     补救办法相反，而 `<img>` 的 onerror 两者看不出区别。
//
// ★ 样式：配对那两栏复用 app.css 里的 `.compare`（全目录原本没人用它，
//   形制正好是「两栏 figure 并排」）。本视图自己的东西都在 compare.css。
import { el, add, mount } from '../dom.js';
import { API } from '../api.js';

/** 主图：加载失败时去把那句话捞回来（`<img>` 的 onerror 给不出 404/409 的区别）。
 *
 * ★★ 图必须**先进 DOM、再给 `src`** —— 这是本视图唯一一处"顺序就是正确性"的地方。
 *   曾经这里是「造一个游离的 `<img loading="lazy">`，在它的 `load` 事件里才 `mount()` 进 DOM」。
 *   而 Chromium 对**游离的**懒加载图**永不发起请求**（懒加载的触发条件本身就是"进入视口"，
 *   而游离元素没有视口位置）⇒ `load` 永不触发 ⇒ `mount` 永不执行 ⇒ **死锁**。
 *   2026-09-25 真浏览器实测的症状：首次打开 `#/compare`，23 个槽全是「正在取图…」、
 *   **到 `/api/compare/photo|img` 的请求数 = 0**、`.cmp-fail` = 0、
 *   **console 0 条 / pageerror 0 条** —— 屏幕上只像"还在加载"，实际一声不吭地谁也取不来。
 *   （只有走一次深链或 reload 才会出现，所以手点一遍**碰不到**这个形状。）
 *   ⇒ 判据不是"图能出来"，是"**图在文档里**"。下面顺带留了个 5 秒兜底：万一将来
 *     有人又把 img 造在文档之外，它会明说"元素不在文档里"，而不是永远停在「正在取图…」。
 */
function imgOrWhy(url, alt, cls = null) {
  const tip = el('span', { class: 'dim', text: '正在取图…' });
  const box = el('div', { class: 'cmp-imgslot' }, tip);
  const img = el('img', { alt, class: cls, loading: 'lazy' });
  let settled = false;
  img.addEventListener('load', () => { settled = true; tip.remove(); });
  img.addEventListener('error', () => {
    settled = true;
    // 图挂了。**不能只写"图片加载失败"** —— 服务端已经说清了是哪一种失败，
    // 而这两种的下一步动作正相反（改键 vs 重建清单）。
    fetch(url, { headers: { accept: 'application/json' } })
      .then(async (r) => {
        let msg = `HTTP ${r.status}`;
        let code = '';
        try {
          const env = await r.json();
          msg = env?.error?.message || msg;
          code = env?.error?.code || '';
        } catch { /* 不是信封（比如静态 404），就用状态码那句话 */ }
        mount(box, el('div', { class: 'cmp-fail' },
          el('b', { text: `${r.status} ` }),
          code ? el('code', { text: `${code} · ` }) : null,
          el('span', { text: msg })));
      })
      .catch((e) => mount(box, el('div', { class: 'cmp-fail' },
        el('span', { text: `取不到这张图：${e.message}` }))));
    // 网络层也可能失败（后端停了）—— 上面那个 catch 兜住。
    box.setAttribute('data-err', '1');
  });
  add(box, img);          // ★ 先入文档（懒加载才有视口位置可判）
  img.src = url;          // ★ 再给 src（顺序反过来也能用，但这样最稳）
  // 兜底：只在这个视图自己的缺陷形状上说话（图不在文档里），不会因"慢"或
  // "还在屏幕外"误报 —— 那两种情况图都在文档里，浏览器只是还没轮到它。
  setTimeout(() => {
    if (!settled && !img.isConnected) {
      box.setAttribute('data-err', '1');
      mount(box, el('div', { class: 'cmp-fail' },
        el('span', { text: '这张图没有被浏览器取 —— 元素不在文档里（本视图的缺陷，不是服务端的问题）' })));
    }
  }, 5000);
  return box;
}

function kpi(k, v, n, cls = '') {
  return el('div', { class: `kpi ${cls}`.trim() },
    el('div', { class: 'k', text: k }),
    el('div', { class: 'v', text: v }),
    n ? el('div', { class: 'n', text: n }) : null);
}

const fmtKm = (v) => (typeof v === 'number' ? `${v.toFixed(3)} km` : '—');
const fmtLL = (o) => (o && typeof o.lon === 'number'
  ? `${o.lat.toFixed(6)}, ${o.lon.toFixed(6)}` : '—');

/** 那一对的两栏（照片 | 卫星裁切）。 */
function pair(it) {
  const a = it.aerial || {};
  const p = it.photo || {};
  const bad = [];
  if (a.placeholder_tiles) {
    bad.push(`${a.placeholder_tiles}/${a.tiles} 块瓦片是「此区域无卫星图」占位块`);
  }
  if (a.fetch_failed) bad.push(`${a.fetch_failed} 块瓦片取数失败（图上有空洞）`);

  return el('section', {
    class: 'cmp-pair', id: `pair-${it.key}`, dataset: { key: it.key },
  },
    el('header', { class: 'cmp-pair-h' },
      el('a', {
        class: 'cmp-key', href: `#/compare/${it.key}`,
        text: it.key, title: '这一对的可分享地址',
      }),
      el('span', { class: 'cmp-title', text: it.title || '' }),
      el('span', { class: 'dim', text: it.dt || '' }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'tag info', text: `距校中心 ${fmtKm(it.km)}` }),
      it.in_campus_image ? null : el('span', { class: 'tag warn', text: '不在校区大图范围内' })),
    el('div', { class: 'compare' },
      el('figure', {},
        el('figcaption', {},
          el('span', { text: '本机照片（EXIF 坐标）' }),
          el('span', { class: 'why', text: p.dir_head || '' })),
        imgOrWhy(API.url.comparePhoto(it.key), `照片 ${it.key}`),
        el('div', { class: 'cmp-coord' },
          el('b', { text: 'WGS-84 ' }), fmtLL(it.wgs84))),
      el('figure', {},
        el('figcaption', {},
          el('span', { text: `高德卫星 z${a.z ?? '?'}` }),
          el('span', {
            class: 'why',
            text: a.m_per_px ? `${a.px || '?'} px · ${a.m_per_px} m/px` : '',
          })),
        el('div', { class: 'cmp-overlaywrap' },
          imgOrWhy(API.url.compareImg(it.key), `卫星 ${it.key}`),
          // 准星压在正中：服务端那侧就是**以该点为中心**裁的这块（不是整瓦片对齐），
          // 所以中心像素**就是**那个坐标。这一点是配对的全部意义所在。
          el('div', { class: 'cmp-cross', 'aria-hidden': 'true' })),
        el('div', { class: 'cmp-coord' },
          el('b', { text: 'GCJ-02 ' }), fmtLL(it.gcj02),
          el('span', { class: 'dim', text: '（准星＝照片所在点）' }))),
    ),
    bad.length ? el('ul', { class: 'cmp-warn' }, bad.map((t) => el('li', { text: t }))) : null);
}

/** 校区大图 + 点位。点的位置**由清单里的 bbox 现算**，不是画上去的。 */
function campusBlock(c) {
  if (!c) return el('p', { class: 'dim', text: '清单里没有校区大图这一项。' });
  const bb = c.bbox || {};
  const wrap = el('div', { class: 'cmp-map' },
    imgOrWhy(API.url.compareImg('campus'), '校区卫星图'));
  return el('section', { class: 'cmp-campus' },
    el('h2', { text: c.title || '整片校区' }),
    wrap,
    el('p', { class: 'lede cmp-hint',
      text: '下面这些点是从清单里算出来的（照片坐标 → GCJ-02 → 图内比例）。'
        + '点它跳到那一对。' }));
}

export async function render(root, sub = '') {
  const man = await API.compareList();
  const items = man.items || [];
  const campus = man.campus || null;
  const tiles = man.tiles || {};
  const nIn = items.filter((i) => i.in_campus_image).length;

  const head = el('header', { class: 'cmp-head' },
    el('h1', { text: '影像比对' }),
    el('p', { class: 'lede' },
      '照片是在地面上拍的，卫星图是从天上看的 —— 两边各自独立，谁也不是从谁派生的。',
      el('em', { text: '配对是算出来的' }),
      '：照片 EXIF 是 WGS-84，高德瓦片是 GCJ-02，两者在本机实测差约 360 m，'
      + '所以先把坐标换算过去再算瓦片号。准星压在卫星图正中，那个中心像素就是照片所在点。'),
    man.how ? el('p', { class: 'cmp-how', text: man.how }) : null);

  if (man.absent) {
    // 「还没建清单」不是「建了但一对都没有」—— 空数组和这一句在屏幕上必须不同。
    mount(root, head, el('div', { class: 'chk-panic' },
      el('h2', { class: 'chk-panic-h', text: '还没有比对清单' }),
      el('p', { class: 'chk-panic-msg', text: man.absent }),
      el('p', { class: 'dim', text: '跑 _scratch/_compare/build_compare.py 建一份（要联网取瓦片）。' })));
    return;
  }

  const kpis = el('div', { class: 'kpis' },
    kpi('配对数', String(items.length), `${nIn} 对落在大图范围内`),
    kpi('瓦片', String(tiles.total ?? '—'),
      tiles.placeholder
        ? `${tiles.placeholder} 块是「无影像」占位块` : '无占位块（都是真影像）',
      tiles.placeholder ? 'warn' : 'good'),
    kpi('判据版本', String(man.criterion_version ?? '—'), '改了缩放/居中/占位判据就 +1'),
    kpi('建清单', man.built || '—', '清单改完刷新本页即可，不用重启'));

  // 点位：由 bbox 现算比例。**只画在范围内的**，范围外的单独报数（见文件头）。
  const bb = campus?.bbox || {};
  const spanLon = (bb.east ?? 0) - (bb.west ?? 0);
  const spanLat = (bb.north ?? 0) - (bb.south ?? 0);
  const canPlace = spanLon > 0 && spanLat > 0;
  const out = items.filter((i) => !i.in_campus_image);

  const sec = campusBlock(campus);
  if (canPlace) {
    const layer = sec.querySelector('.cmp-map');
    if (layer) {
      // 图上那层：百分比定位 ⇒ 换图不必改代码，但**图换了比例就对不上**，
      // 所以 bbox 是从清单读的（跟着图一起生成），不是写死在页面里的。
      add(layer, el('div', { class: 'cmp-pins' }, items.map((i) => {
        const g = i.gcj02 || {};
        if (typeof g.lon !== 'number' || !i.in_campus_image) return null;
        const x = ((g.lon - bb.west) / spanLon) * 100;
        const y = ((bb.north - g.lat) / spanLat) * 100;
        return el('a', {
          class: 'cmp-pin', href: `#/compare/${i.key}`,
          style: { left: `${x}%`, top: `${y}%` },
          text: i.key.replace(/^p/, ''),
          title: `${i.key} · ${i.dt || ''} · ${fmtKm(i.km)}`,
        });
      })));
    }
  } else {
    add(sec, el('p', { class: 'miss', text: '清单里没有校区大图的经纬度框 ⇒ 点摆不上去（不会瞎猜位置）。' }));
  }
  if (out.length) {
    add(sec, el('p', { class: 'miss',
      text: `${out.length} 对不在大图范围内，没有画点（是"图外"，不是"漏画"）：`
        + out.map((i) => i.key).join('、') }));
  }

  mount(root, head, kpis, sec,
    el('h2', { class: 'cmp-h2', text: `逐对（${items.length}）` }),
    el('div', { class: 'cmp-list' }, items.map(pair)));

  // `#/compare/p03` ⇒ 滚到那一对。可分享是选 hash 路由的原始理由，这里兑现它。
  if (sub) {
    const t = document.getElementById(`pair-${sub}`);
    if (t) {
      t.classList.add('cmp-focus');
      t.scrollIntoView({ block: 'start' });
    } else {
      // 「你给的那个键不在清单里」要**出声** —— 静默停在顶上会被读成"这页就这样"。
      // ★ 用 insertBefore 而不是 mount(root, …, root)：后者是把 root 塞进它自己里面。
      root.insertBefore(el('p', { class: 'miss cmp-hint',
        text: `清单里没有这一对：${sub}（现有：${items.map((i) => i.key).join('、')}）` }),
        root.firstChild);
    }
  }
}

// 「作业台」视图 —— 原 `_scratch/_portal.py`(8144) 上的活，收编进管理台。
//
// 这一屏回答的是「**手上这个库现在该怎么办**」，所以它把四件事摆在一起：
//   1. 现在有没有作业在跑（以及上一次的结局 —— 退出码不是成败的唯一读数，但它必须露出来）；
//   2. 往里放东西（CAD 图纸 / 外观照片）；
//   3. 一键把活派出去（`_system.py` / `_ref_import.py`）；
//   4. 逐栋的产物状态（有没有 GLB、门禁跑没跑、有没有速览图）。
//
// ★★ 四条规矩，都是本仓踩出来的，写在最前面：
//
//  1. **「量不到」与「零」屏幕上必须不同。** 没有 GLB 的楼写「无产物」，不写「0 MB」；
//     没跑过门禁的写「未跑」，不写「0 个 ERROR」—— 后者读起来像「跑了且干净」。
//     服务端配合这条：量不到的一律回 `null`，不回 0。
//  2. **写按钮先问后画。** 能不能写由 `GET /api/capabilities` 的 `write_enabled` 说
//     （它用的是**同一条**判定：`deps.exec_denied_reason`，回环/`GYM3D_COMPUTE`/
//     `X-Admin-Token` 三件事一起看）。不能写时按钮**一开始就是灰的并写明理由**，
//     不是「点下去才回 403」 —— 这两件事在屏幕上差别很大。
//  3. **轮询失败必须重排，或者把状态清干净并明说。** 原 8144/控制台上那个形状
//     （`if (!j.success) return;` 之后不再排下一次）会让按钮**永久卡死**在「运行中」，
//     而且它不报错。这里的做法是：失败就画一条「接口不可用」横幅、**保留上一次的读数
//     并写明那是几点几分的**、然后继续用慢一档的间隔重试（后端回来了自己就恢复）。
//  4. **不整屏重画。** 壳子（筛选框、文件选择框）只建一次，轮询只重画会变的那几块。
//     整屏重画会把正在输入的字和刚选好的文件一起抹掉 —— 屏幕上看着像「页面自己动了」。
import { el, add, mount, table } from '../dom.js';
import { API, ApiError } from '../api.js';

export const label = '作业台';

//: 静置时的轮询间隔。★ 用链式 `setTimeout` 而不是 `setInterval`：慢请求会让
//: 回调叠起来（同一时刻好几份在飞），屏幕上就是「越刷越卡」，且没有任何报错。
const POLL_MS = 8000;
//: 有作业在跑时快一档 —— 一个 900 秒级的活，用户要能看见它什么时候落地。
const POLL_BUSY_MS = 3000;
//: 接口不可用时的重试间隔。慢一档，但**不能停** —— 停了就再也不会自己恢复，
//: 用户只会以为这一屏坏了（而后端其实两秒前就起来了）。
const POLL_DOWN_MS = 15000;
//: 「最近的作业」列几个。作业的完整历史在 `data/_jobs/*.json`，这里只摆眼前要用的。
const RECENT_JOBS = 6;

//: 作业状态 → 徽标。`exit_code` 单独一栏 —— 「跑完且成功」与「跑完但失败」必须长得不一样。
const JOB_STATE = {
  running: ['now', '在跑'],
  ok: ['ok', '跑完 · 退出码 0'],
  failed: ['bad', '跑完但失败'],
  timeout: ['warn', '超时已杀'],
  lost: ['warn', '记录读不动'],
};

//: 跨挂载保留的**读数缓存**（不是状态机）：切走再回来先拿它画一屏，再刷新。
//: `at` 与读数一起留着 —— 屏幕上的每个数都要能说出「这是几点几分的」。
const state = {
  caps: null, status: null, refs: null, jobs: null, at: null, err: null,
  filter: '', onlyProblem: false, uploads: [], busy: false,
};

let timer = null;
let disposed = false;
//: 本次挂载的可变区（每次 render 重建）。dispose 后置空，免得定时器往死节点里写。
let box = null;
//: 壳子的重建入口。`panic()` 会把整个壳子换掉，所以 paint 之前要先能把它建回来。
let buildShell = null;

//: 「刚才上传的」最多留几条。它是本页内存里的东西，长活进程里不许无界长。
const MAX_UPLOG = 12;

export function dispose() {
  disposed = true;
  if (timer) clearTimeout(timer);
  timer = null;
  box = null;
}

// ── 小工具 ──────────────────────────────────────────────────────

function fmtDur(s) {
  if (s === null || s === undefined) return '—';
  if (s < 60) return `${s.toFixed(1)} 秒`;
  const m = Math.floor(s / 60);
  return `${m} 分 ${Math.round(s - m * 60)} 秒`;
}

function stamp(d) {
  return d ? d.toLocaleTimeString('zh-CN', { hour12: false }) : '—';
}

/** 缩略图。★ 图裂了必须**说出来** —— 一个裂图框和「这张图本来就没有」长得一样。 */
function thumb(src, title) {
  const box = el('figure', { class: 'ws-thumb' },
    el('img', { src, alt: title, loading: 'lazy' }),
    el('figcaption', { text: title }));
  box.querySelector('img').addEventListener('error', () => {
    box.classList.add('broken');
    box.querySelector('figcaption').textContent = `${title}（图读不出来）`;
  });
  return box;
}

/** 一个量该怎么说。`null` = 量不到，**与 0 不同字**。 */
function miss(text) { return el('span', { class: 'ws-miss', text }); }

// ── 顶栏：标题 / 写权限 / 读数时间 / 接口不可用横幅 ──────────────

function paintHead() {
  const { caps, at, err } = state;
  const writeOn = !!caps?.write_enabled;
  const parts = [
    el('div', { class: 'ws-title' },
      el('h1', { text: '作业台' },
        el('span', { class: 'sub', text: ' 放东西进来 → 把活派出去 → 看它落到哪一步' })),
      el('div', { class: 'ws-badges' },
        el('span', { class: `ws-badge ${writeOn ? 'on' : 'off'}`,
          text: writeOn ? '写权限 开' : '写权限 关',
          title: caps?.write_disabled_reason || '' }),
        el('span', { class: 'ws-badge', text: `读数 ${stamp(at)}` }))),
  ];
  if (!writeOn) {
    // ★ 理由用后端给的那**一句原话**（capabilities.write_disabled_reason）：
    //   它是与 403 响应同一处判定产出的，所以界面上写的和真打接口得到的是同一句。
    add(parts[0], el('p', { class: 'ws-note warn' },
      el('b', { text: '这一屏现在只能看。' }),
      caps?.write_disabled_reason || '后端能力接口没给理由（或还没问到）—— 按钮保守地禁掉。'));
  }
  if (err) {
    const e = err instanceof ApiError ? err : new ApiError('unknown', String(err));
    add(parts[0], el('p', { class: 'ws-note bad' },
      el('b', { text: `接口不可用：${e.code}` }), ' ', e.message || '',
      state.status
        // ★ 加粗要用元素，**不许在字符串里写 `**`** —— `el()` 只认 text，
        //   星号会原样画到屏幕上（实测回执里就印着字面量 `**认不出楼号**`）。
        ? el('span', {}, `　下面这几块是 ${stamp(at)} 的读数，`,
            el('b', { text: '可能已经过期' }),
            `（页面每 ${POLL_DOWN_MS / 1000} 秒重试一次，通了会自动刷新）。`)
        : '　还没读到过任何数据。'));
  }
  mount(box.head, parts);
}

// ── 动作：上传 + 跑 ─────────────────────────────────────────────

/** 建一次就不再重建（重建会把用户刚选好的文件清掉）。只改 `disabled` 与文案。 */
function buildActions() {
  const fileIn = box.file;
  const upBtn = el('button', {
    class: 'ws-btn primary', type: 'button', text: '上传',
    onclick: () => doUpload(fileIn, upBtn),
  });
  box.upBtn = upBtn;

  const runBtns = [];
  const runRow = el('div', { class: 'ws-runrow' });
  for (const m of state.status?.modes || []) {
    const b = el('button', {
      class: 'ws-btn', type: 'button', text: m.label,
      onclick: () => doRun(m.mode, b),
    });
    b.dataset.mode = m.mode;
    b.dataset.scriptPresent = m.script_present ? '1' : '0';
    if (!m.script_present) b.title = '要的脚本不在本机（_scratch/ 未进 git）';
    runBtns.push(b);
    add(runRow, b);
  }
  box.runRow = runRow;

  mount(box.actBody,
    el('div', { class: 'ws-act' },
      el('h2', { text: '① 放进来' }),
      el('p', { class: 'dim' },
        '图纸（DWG/DXF…）进 ', el('code', { text: '_inbox/' }),
        '；照片（png/jpg/webp…）自动分流进 ', el('code', { text: '_inbox/refs/' }),
        '，并按', el('b', { text: '文件名里的楼号' }), '认它属于哪一栋。'),
      el('div', { class: 'ws-row' }, box.file, upBtn,
        el('span', { class: 'dim', id: 'ws-up-hint' }))),
    el('div', { class: 'ws-act' },
      el('h2', { text: '② 派出去' }),
      el('p', { class: 'dim' },
        '一个长活起一个子进程，输出落 ', el('code', { text: 'data/_jobs/<id>.log' }),
        '；同时只允许一个在跑（第二个会', el('b', { text: '点名' }),
        '是谁占着），超时会', el('b', { text: '连它的子进程一起杀' }), '。'),
      runRow.children.length ? runRow
        : el('p', { class: 'dim' }, '后端一个模式都没给（',
            el('code', { text: 'RUNNERS' }), ' 那张表是空的？）。')),
    box.upList);
}

/** 把按钮的可用性对齐到当前读数。**只改 disabled，不动 DOM**（见 buildActions）。 */
function syncActions() {
  const writeOn = !!state.caps?.write_enabled;
  const reason = state.caps?.write_disabled_reason || '';
  const busy = !!state.status?.running;

  if (box.upBtn) {
    box.upBtn.disabled = !writeOn;
    box.upBtn.title = writeOn ? '' : reason;
  }
  const hint = document.getElementById('ws-up-hint');
  if (hint) {
    hint.textContent = writeOn ? '（可以多选）'
      : `（现在不能写：${reason || '后端没给理由'}）`;
  }
  for (const b of box.runRow ? box.runRow.children : []) {
    const missing = b.dataset.scriptPresent !== '1';
    b.disabled = !writeOn || missing || busy;
    if (busy && !missing && writeOn) b.title = '已经有一个作业在跑 —— 同一时刻只允许一个';
    else if (missing) b.title = '要的脚本不在本机（_scratch/ 未进 git）';
    else if (!writeOn) b.title = reason;
    else b.title = '';
  }
}

function paintUploads() {
  if (!state.uploads.length) return;
  // 一次拖进来几十个文件时，日志本身要把页面顶穿 —— 只留最近 MAX_UPLOG 条。
  // ★ 但**不许**静默截断：砍掉多少条要写出来（「少显示 3 条」和「总共就这 12 条」
  //   在屏幕上必须不是同一行字，本仓栽过 memory: gauge-coverage-invisible-in-summary）。
  const cut = Math.max(0, state.uploads.length - MAX_UPLOG);
  const shown = cut ? state.uploads.slice(cut) : state.uploads;
  mount(box.upList, el('div', { class: 'ws-act' },
    el('h2', { text: '刚才上传的' }),
    el('ul', { class: 'ws-uplist' }, shown.map((u) => el('li', { class: u.ok ? '' : 'bad' },
      el('b', { text: u.ok ? '✔ ' : '✘ ' }), u.text,
      u.next ? el('div', { class: 'dim' }, u.next) : null))),
    cut ? el('p', { class: 'dim', text: `（前面还有 ${cut} 条没列出来）` }) : null));
}

// ── 作业 ────────────────────────────────────────────────────────

function jobLine(j) {
  const [cls, text] = JOB_STATE[j.state] || ['warn', j.state || '未知状态'];
  const bits = [];
  if (j.exit_code !== null && j.exit_code !== undefined) bits.push(`退出码 ${j.exit_code}`);
  bits.push(`耗时 ${fmtDur(j.elapsed_s)}`, `起于 ${j.started || '—'}`);
  if (j.pid) bits.push(`pid ${j.pid}`);
  return el('li', { class: `ws-job ${cls}` },
    el('span', { class: 'ws-job-state', text }),
    el('span', { class: 'ws-job-label', text: j.label || j.mode || j.id }),
    el('span', { class: 'ws-job-meta', text: bits.join(' · ') }),
    j.log ? el('code', { class: 'ws-job-log', text: j.log }) : null,
    j.note ? el('span', { class: 'ws-job-note', text: j.note }) : null);
}

function paintJobs() {
  const st = state.status, jobs = state.jobs || [];
  const running = st?.job;
  const head = running
    ? el('div', { class: 'ws-now' },
      el('span', { class: 'ws-spin' }),
      el('b', { text: '正在跑：' }), running.label || running.mode,
      el('span', { class: 'dim' },
        `　pid ${running.pid} · 已跑 ${fmtDur(running.elapsed_s)} · 起于 ${running.started}`),
      el('code', { class: 'ws-job-log', text: running.log || '' }))
    : el('div', { class: 'ws-now idle' },
      el('b', { text: '现在没有作业在跑。' }),
      el('span', { class: 'dim', text: '（同一时刻只允许一个；起第二个会被拒绝并点名）' }));

  mount(box.job,
    el('div', { class: 'ws-card' },
      el('h2', { text: '作业' }),
      head,
      jobs.length
        ? el('ul', { class: 'ws-joblist' }, jobs.map(jobLine))
        : el('p', { class: 'dim' }, '还没有跑过 —— ',
            el('code', { text: 'data/_jobs/' }), ' 里也没有落过终态。')));
}

// ── 两个队列 + 待办 ─────────────────────────────────────────────

function pendingRefs() {
  const r = state.refs;
  if (!r) return el('p', { class: 'dim', text: '还没读到。' });
  if (!r.inbox_dir_present) {
    return el('p', { class: 'dim' },
      el('code', { text: '_inbox/refs/' }), ' 这个目录不存在 —— 还没往里放过照片（不是「队列是空的」）。');
  }
  if (!r.inbox.length) return el('p', { class: 'dim', text: '队列是空的 —— 没有待入库的图。' });
  return el('div', {},
    el('div', { class: 'ws-thumbs' }, r.inbox.map((x) => {
      const how = x.guess ? `认成 ${x.guess}`
        : (x.raw_guess ? `猜成 ${x.raw_guess}，但库里没这栋` : '文件名里看不出楼号');
      return thumb(API.url.workshopRefimg(x.file), `${x.file}（${x.kb} KB · ${how}）`);
    })),
    el('p', { class: 'dim' },
      '点「外观图入库」会把上面这些按文件名挂到对应楼；',
      el('b', { text: '认不出/认错的一个都不挂' }),
      '（猜错比猜不出更坏 —— 会把照片挂到别人家），它们会留在原地等人工指定。'));
}

function refsQueue() {
  const r = state.refs;
  if (!r) return el('p', { class: 'dim', text: '还没读到。' });
  const line = (title, names, empty) => el('div', { class: 'ws-q' },
    el('h3', { text: `${title}（${names.length}）` }),
    names.length
      ? el('p', { class: 'ws-names' }, names.map((n, i) => el('span', {},
        i ? '、' : '', n.startsWith('c') ? el('a', { href: `#/building/${n}`, text: n }) : n)))
      : el('p', { class: 'dim', text: empty }));
  return el('div', {},
    line('待判读（有图、还没结论）', r.pending, '没有 —— 有图没结论的一栋都没有。'),
    line('已判读', r.judged, '还没有任何一栋写出了 facts.json。'),
    el('p', { class: 'dim' },
      '这两个数来自 ', el('code', { text: 'data/refs/<楼>/' }), ' 里有没有 ',
      el('code', { text: 'refs.json' }), ' / ', el('code', { text: 'facts.json' }),
      '。判读结论要写进 ', el('code', { text: 'facts.json' }),
      '（这一步没有界面，是留给智能体和人做的）。'));
}

function pendingTasks() {
  const st = state.status;
  if (!st) return el('p', { class: 'dim', text: '还没读到。' });
  if (st.tasks === null) {
    return el('p', { class: 'dim' }, el('code', { text: '_qa/tasks/' }),
      ' 这个目录不存在（不是「没有待办」）。');
  }
  return el('div', { class: 'ws-q' },
    el('h3', { text: `待办任务单（${st.tasks.length}）` }),
    st.tasks.length
      ? el('p', { class: 'ws-names' }, st.tasks.map((f, i) => el('span', {},
        i ? '、' : '',
        el('a', { href: API.url.workshopTask(f), target: '_blank', rel: 'noopener',
          text: f.replace(/\.md$/, '') }))))
      : el('p', { class: 'dim', text: '没有待办 —— 门禁这一轮没留下要人工处理的单子。' }),
    st.qa_missing.length
      ? el('p', { class: 'dim' }, `另有 ${st.qa_missing.length} 栋`,
        el('b', { text: '门禁没跑过' }),
        '，它们的结论是「未跑」而不是「干净」：', st.qa_missing.slice(0, 8).join('、'),
        st.qa_missing.length > 8 ? ` 等 ${st.qa_missing.length} 栋` : '')
      : null);
}

function suQueue() {
  const st = state.status;
  if (!st) return el('p', { class: 'dim', text: '还没读到。' });
  if (!st.su_dir_present) {
    return el('p', { class: 'dim' }, el('code', { text: '_scratch/su_jobs/' }),
      ' 这个目录不存在（不是「没有复核页」）。');
  }
  return el('div', { class: 'ws-q' },
    el('h3', { text: `SU 复核页（${st.su.length}）` }),
    st.su.length
      ? el('p', { class: 'ws-names' }, st.su.map((f, i) => el('span', {},
        i ? '、' : '',
        el('a', { href: API.url.workshopSu(f), target: '_blank', rel: 'noopener', text: f }))))
      : el('p', { class: 'dim', text: '没有复核页。' }));
}

function paintQueues() {
  mount(box.queue,
    el('div', { class: 'ws-card' },
      el('h2', { text: '待入库的照片' }), pendingRefs()),
    el('div', { class: 'ws-card' },
      el('h2', { text: '判读' }), refsQueue()),
    el('div', { class: 'ws-card' },
      el('h2', { text: '待办' }), pendingTasks(), suQueue()));
}

// ── 楼栋状态表 ──────────────────────────────────────────────────

function qaCell(r) {
  if (r.qa_errors === null) return miss('未跑');
  if (r.qa_errors === 0) return el('span', { class: 'ws-ok', text: '0 · 干净' });
  return el('a', { class: 'ws-bad', href: `#/checks/${r.name}`, text: `${r.qa_errors} 条 ERROR` });
}

function glbCell(r) {
  if (r.glb_mb === null) return miss('无产物');
  return el('span', {}, `${r.glb_mb} MB`,
    el('span', { class: 'dim', text: r.glb_at ? `（${r.glb_at}）` : '' }));
}

function previewCell(r) {
  if (r.preview_png === null) return miss('无目录');
  if (!r.preview_png) return miss('目录在，0 张');
  return el('a', { href: API.url.workshopPreview(r.name, r.preview_first),
    target: '_blank', rel: 'noopener', text: `${r.preview_png} 张` });
}

/** 「只看有问题的」= 门禁未跑/有 ERROR，或没有 GLB。**谓词与标签必须逐字对应。** */
function isProblem(r) {
  return r.glb_mb === null || r.qa_errors === null || r.qa_errors > 0;
}

function paintTable() {
  const st = state.status;
  if (!st) { mount(box.table, el('p', { class: 'dim', text: '还没读到楼栋状态。' })); return; }
  const q = state.filter.trim().toLowerCase();
  let rows = st.rows;
  if (q) rows = rows.filter((r) => (r.name + ' ' + (r.title || '')).toLowerCase().includes(q));
  if (state.onlyProblem) rows = rows.filter(isProblem);
  const cols = ['楼', '名称', '层', '房间', 'GLB', '门禁 ERROR', '速览图'];
  const body = rows.map((r) => [
    el('a', { href: `#/building/${r.name}`, title: '看这栋的三维', text: r.name }),
    r.title || '',
    r.floors === null || r.floors === undefined ? miss('—') : String(r.floors),
    r.rooms === null || r.rooms === undefined ? miss('—') : String(r.rooms),
    glbCell(r), qaCell(r), previewCell(r),
  ]);
  mount(box.table,
    el('p', { class: 'ws-count' },
      `共 ${st.rows.length} 栋，这一屏显示 ${rows.length} 栋`
      + `${q || state.onlyProblem ? '（筛过的）' : ''} · 门禁未跑 ${st.qa_missing.length} 栋`
      + `　★ 没有产物的写「无产物」，没跑过的写「未跑」—— 都不是 0。`),
    body.length
      ? table(cols.map((c) => ({ label: c })), body, { cls: 'ws-tbl' })
      : el('div', { class: 'ws-card' },
        el('b', { text: '这个筛选下没有楼。' }),
        '（不等于「全库都没问题」 —— 把筛选条件读出来看看它筛掉了什么。）'));
}

// ── 动作实现 ────────────────────────────────────────────────────

/** 上传：**一个文件一个请求**，逐个报结果。 */
async function doUpload(fileIn, btn) {
  const files = Array.from(fileIn.files || []);
  if (!files.length) {
    state.uploads = [{ ok: false, text: '没选文件。先点「选择文件」挑好，再点「上传」。' }];
    paintUploads();
    return;
  }
  btn.disabled = true;
  const old = btn.textContent;
  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    btn.textContent = `正在传 ${i + 1}/${files.length}…`;
    try {
      // ★ 发的是 File 本体（走 postRaw）—— 见 api.js 里那段：塞进 JSON body
      //   会 stringify 成 `{}`，后端照样回 200，屏幕上写着「上传成功」。
      // ★ `post` / `postRaw` 回的是**整个信封**（先例 `views/area.js:480` 也是按 `env` 收的），
      //   所以这里必须取 `.data`。少了这一步**不会报错**：`r.kind` 恒 undefined，
      //   页面照样画出来，只是每一张图都被说成「图纸，落 `_inbox/`」、也没有「下一步」——
      //   实测在浏览器里就是这么表现的（curl 那条路测不出来，它压根不看前端读什么）。
      const r = (await API.workshopUpload(f.name, f)).data;
      const kind = r.kind === 'reference-image' ? '照片' : '图纸';
      const where = r.kind === 'reference-image' ? '_inbox/refs/' : '_inbox/';
      const guess = r.building_guess
        ? `认成 ${r.building_guess}`
        : (r.kind === 'reference-image' ? '认不出楼号（入库时会跳过它）' : '');
      state.uploads.push({ ok: true,
        text: `${f.name} → ${kind}，落 ${where}`,
        next: `${(f.size / 1024).toFixed(1)} KB${guess ? ` · ${guess}` : ''}`
          + (r.next ? `　下一步：${nextHint(r)}` : '') });
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError('unknown', String(e));
      state.uploads.push({ ok: false, text: `${f.name} → 失败：${err.code}`,
        next: err.message || String(e) });
    }
    paintUploads();
  }
  btn.disabled = false;
  btn.textContent = old;
  // 传完立刻刷一次：队列里马上就该多出这几张（这是「真落盘了」的第一次可见证据）。
  await refresh();
}

/** `next` 要么是一条命令行，要么是**下一个模式的名字** —— 后者的中文名从 modes 里取，
 *  不在前端另写一份对照（一个判断一份实现）。 */
function nextHint(r) {
  if (!r.next) return '';
  if (r.next.startsWith('python')) return `命令行：${r.next}`;
  const m = (state.status?.modes || []).find((x) => x.mode === r.next);
  return m ? `点上面的「${m.label}」` : `模式 ${r.next}`;
}

async function doRun(mode, btn) {
  btn.disabled = true;
  try {
    const j = (await API.workshopRun(mode)).data;   // 同样：post 回信封，见上面那段
    state.uploads = [];      // 上一轮的「刚才上传的」到这一步就该让位了
    paintUploads();
    add(box.job, el('p', { class: 'ws-note' },
      `已起作业 ${j.id}（pid ${j.pid}）—— 日志：`, el('code', { text: j.log })));
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError('unknown', String(e));
    // ★ 409 job_busy 与 503 script_missing 是两条**不同**的实话，分开说。
    const known = {
      job_busy: '已经有一个作业在跑 —— 后端不排队、不丢弃，直接拒绝并点名是谁占着。',
      // ★ 这几句会走 `text:` 原样画出来 ⇒ 里面**不许写反引号/星号**（会当成字面量显示）
      script_missing: '要的脚本不在这台机器上（_scratch/ 里的本机脚本未进 git），没有起任何作业。',
      compute_disabled: '本机已关闭写/执行（GYM3D_COMPUTE=0）。',
      local_only: '执行面仅限本机 —— 从别的机器打开这一屏时一律 403（只读的几块照常可用）。',
    }[err.code];
    mount(box.job, el('div', { class: 'ws-card' },
      el('p', { class: 'ws-note bad' },
        el('b', { text: `起不了：${err.code || 'unknown'}` }), ' ', err.message || String(e)),
      known ? el('p', { class: 'dim', text: known }) : null));
  } finally {
    await refresh();
  }
}

// ── 取数 + 重画 ─────────────────────────────────────────────────

async function refresh() {
  if (timer) clearTimeout(timer);
  timer = null;
  if (disposed) return;
  try {
    // 三条一起取。它们全在同一个进程同一条只读路径上 —— 一起失败就是「接口不可用」，
    // 不需要给它们各自编一套降级（那只会把「连不上」说成「这一块恰好没数据」）。
    const [status, refs, jobs] = await Promise.all([
      API.workshopStatus(), API.workshopRefs(), API.workshopJobs(RECENT_JOBS),
    ]);
    if (!state.caps) {
      // 能力问不到**不挡看结论**，只让写按钮保守地灰着（与 checks.js 同一条取舍）。
      try { state.caps = await API.capabilities(); } catch { state.caps = null; }
    }
    state.status = status;
    state.refs = refs;
    state.jobs = jobs;
    state.at = new Date();
    state.err = null;
  } catch (e) {
    if (disposed) return;
    state.err = e instanceof ApiError ? e : new ApiError('unknown', String(e));
  }
  if (disposed) return;
  paint();
  schedule();
}

function schedule() {
  if (disposed) return;
  const ms = state.err ? POLL_DOWN_MS
    : (state.status?.running ? POLL_BUSY_MS : POLL_MS);
  timer = setTimeout(() => { refresh(); }, ms);
}

function paint() {
  if (!box) return;
  // 第一次就没读到时，整屏换成一块说得清的告示 —— **不画空表**
  // （空表会被读成「全库都没问题」，而实际是「一条都没量」）。
  if (!state.status && state.err) { panic(); return; }
  // ★ 壳子被 panic 换掉过（`box.shell` 已经不在文档里）⇒ 先重建再画。
  //   少了这一步，后端恢复之后定时器会往一堆**已经摘下来的**节点里写：
  //   状态在内存里全对，屏幕上却永远停在那张「接口不可用」的告示上，
  //   而且它**不再刷新** —— 看上去就是「后端还没起来」，其实早就起来了。
  if (!box.shell.isConnected) buildShell();
  paintHead();
  if (!box.upBtn) buildActions();
  syncActions();
  paintUploads();
  paintJobs();
  paintQueues();
  paintTable();
}

/** ★ 这里刻意**自己写一套 `ws-` 样式**，不去借「检查」视图的 `chk-panic`：
 *  借来的是「看着一样」，代价是一个看不见的耦合 —— 哪天 checks.css 改了名，
 *  坏掉的正好是**最不容易被走到的这一支**（后端没起来的时候），
 *  而那一支平时没人看。视图各管各的样式表，是本目录的既有约定。 */
function panic() {
  const e = state.err;
  const down = e.code === 'network' || e.status === 0;
  if (disposed) return;
  mount(box.root, el('div', { class: 'ws-panic' + (down ? ' down' : '') },
    el('h2', { class: 'ws-panic-h', text: down ? '接口不可用' : `取数失败：${e.code}` }),
    el('p', { class: 'ws-panic-msg', text: e.message || String(e) }),
    el('p', { class: 'dim' },
      '这一屏现在什么都没有 —— 所以这里不画表。空表会被读成「全库都没问题」，'
      + '而实际是「一条都没量」。'),
    el('p', { class: 'dim' },
      '后端地址：', el('code', { text: window.GYM3D_API_BASE || '同源（当前页所在主机）' }),
      '；启动命令：', el('code', { text: 'python -u backend/api/run_api.py' })),
    e.detail ? el('details', {},
      el('summary', { text: '后端给的细节（原样）' }),
      el('pre', { class: 'ws-pre', text: JSON.stringify(e.detail, null, 2) })) : null,
    el('div', { class: 'ws-toolbar' },
      el('button', { class: 'ws-btn primary', type: 'button', text: '重试',
        onclick: () => render(box.root, '') }))));
}

// ── 入口 ────────────────────────────────────────────────────────

export async function render(root) {
  disposed = false;
  if (timer) clearTimeout(timer);
  timer = null;

  buildShell = () => {
    // 壳子只建一次（panic 之后才重建）。★ 文件选择框与筛选框必须在这一层：
    //   它们**不能**被轮询重画，否则用户刚挑好的一批照片会在 8 秒后被清空 ——
    //   而屏幕上看着像「我没选中」。
    const file = el('input', { type: 'file', multiple: true, class: 'ws-file',
      'aria-label': '选择要上传的文件' });
    const upList = el('div', { class: 'ws-uplist-holder' });
    const actBody = el('div', { class: 'ws-acts' },
      el('div', { class: 'ws-act' },
        el('h2', { text: '① 放进来' }),
        el('p', { class: 'dim', text: '正在读可用的模式…' })),
      el('div', { class: 'ws-act' }, el('h2', { text: '② 派出去' })));
    const filterIn = el('input', { type: 'search', class: 'ws-filter', value: state.filter,
      placeholder: '筛楼号 / 名称', 'aria-label': '筛选楼栋' });
    filterIn.addEventListener('input', () => { state.filter = filterIn.value; paintTable(); });
    const only = el('input', { type: 'checkbox', checked: state.onlyProblem, id: 'ws-only' });
    only.addEventListener('change', () => { state.onlyProblem = only.checked; paintTable(); });

    // ★ 四个可变区**先建成具名变量**再组装，绝不回头按 `children[i]` 去取。
    //   按下标取节点在这一屏是**静默失效**的：布局哪天多包一层，取到的就是另一个
    //   节点（或者 undefined），而屏幕上只表现为「这一块永远不刷新」。
    const head = el('div', {});
    const jobBox = el('div', {});
    const queueBox = el('div', {});
    const tblBox = el('div', {});
    const shell = el('div', { class: 'ws-wrap' },
      head,
      el('div', { class: 'ws-grid' },
        el('div', { class: 'ws-colleft' },
          el('div', { class: 'ws-card' }, actBody),
          jobBox),
        queueBox),
      el('div', { class: 'ws-card' },
        el('div', { class: 'ws-tablehead' },
          el('h2', { text: '楼栋状态' }),
          el('label', { class: 'ws-filterwrap' }, filterIn),
          el('label', { class: 'ws-only', for: 'ws-only' }, only,
            '只看：门禁未跑/有 ERROR，或没有 GLB')),
        tblBox),
      el('p', { class: 'ws-foot' },
        '这一屏是原 8144 页面的收编版：同一份能力，界面重写。'
        + ' 相对它的几处改动写在 ', el('code', { text: 'backend/api/services/workshop.py' }),
        ' 文件头 —— 其中一条是「拉起 8123/8130」那个按钮',
        el('b', { text: '刻意没有搬' }), '：那两个服务现在就在本进程里。'));

    box = { root, shell, head, actBody, file, upList, upBtn: null, runRow: null,
            job: jobBox, queue: queueBox, table: tblBox };
    mount(root, shell);
  };

  buildShell();
  await refresh();
}

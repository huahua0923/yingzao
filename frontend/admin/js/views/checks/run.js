// 「跑一次」 —— POST /api/checks/{楼}/run 的界面。
//
// 三件必须写在按钮旁边的事（都是这个端点自己的脾气）：
//   · 这是**同步**请求，不是作业队列：A 层秒级，B 层要几分钟（后端 300s / 1800s 超时）；
//   · 单飞：已经有一个作业在跑时，后端**立刻回 409**，不排队、不静默等待；
//   · 超时会**真的终止子进程**并回 504，并且明说产物没写出来 —— 那时别以为跑过了。
//
// ★★ 退出码不是成败：引擎用退出码表达**结论** —— 0 = 没发现 GAP，1 = **检查到 GAP**。
//   「命令返回 0」和「产物写成」也是两件事：成败以后端**回读产物**的结论为准
//   （响应里的 verified），不看退出码。把 1 当失败来报，正好把「查出缺陷」
//   说成「检查没跑成」，是反的。
import { el, add, clear } from '../../dom.js';
import { fmtBytes, fmtTime } from '../../fmt.js';
import { API, ApiError } from '../../api.js';

/** 错误怎么显示：错误码是机器可读的，**按码分支**，不去 parse message。 */
function renderError(box, e, building) {
  clear(box);
  const known = {
    network: '接口不可用：连不上后端。这个请求没有任何结论 —— 不是"没查出问题"。',
    check_running: '已经有一个检查作业在跑（后端单飞，不排队）。稍后重试，或直接看它的产物。',
    check_timeout: '检查超时，后端**真的终止了子进程**：产物没有写成。要跑完请用命令行。',
    artifact_not_confirmed: '命令跑完了，但产物没能被后端确认写成 —— 不当成功。先别拿退出码当结论。',
    compute_disabled: '本进程是只读的（GYM3D_COMPUTE=0），写接口一律 403。',
    check_artifact_missing: '这栋楼还没有检查产物。',
  }[e.code];
  add(box, el('div', { class: 'chk-note bad' },
    el('b', { text: `失败：${e.code || 'unknown'}` }),
    el('div', { text: e.message || String(e) }),
    known ? el('div', { class: 'dim', text: known }) : null,
    e.detail ? el('details', { class: 'chk-details' },
      el('summary', { text: '后端给的细节（原样，不改写）' }),
      el('pre', { class: 'chk-ev', text: JSON.stringify(e.detail, null, 2) })) : null,
    el('div', { class: 'dim' },
      '命令行等价物：', el('code', { text: `python -u backend/checks/runner.py ${building}${e.code === 'check_timeout' ? ' --heavy' : ''}` }))));
}

/** 成功怎么显示：以后端回读产物的核对结果为准。 */
function renderResult(box, res) {
  clear(box);
  const zero = res.exit_code === 0;
  add(box, el('div', { class: `chk-note ${zero ? '' : 'warn'}` },
    el('b', { text: `跑完了（${res.layer} 层，耗时 ${res.duration_s}s）` }),
    el('div', {},
      '退出码 ', el('code', { text: String(res.exit_code) }),
      ' —— ', res.exit_code_meaning || ''),
    el('div', { class: 'dim' },
      `产物 ${res.artifact?.file}：${fmtBytes(res.artifact?.bytes)}，`
      + `${res.artifact?.rewritten_by_this_run ? '被本次运行重写过' : 'mtime 与运行前相同（可能没重写）'}，`
      + `生成于 ${fmtTime(res.artifact?.generated_iso)}`),
    el('div', { class: 'dim' },
      '回读核对：', res.verified?.ok ? '通过' : '未通过', ' —— ', res.verified?.method || '')),
  res.warnings?.length
    ? el('div', { class: 'chk-note warn' }, el('b', { text: '要留意的' }),
      el('ul', { class: 'chk-ul' }, res.warnings.map((w) =>
        el('li', {}, el('b', { text: w.kind }), ' ', w.why))))
    : null);
}

/**
 * @param {{building:string, caps:object, registry:object, onDone:Function}} opts
 */
export function renderRunPanel(opts) {
  const { building, caps, registry, onDone } = opts;
  const heavyB = (registry?.checks || []).find((c) => c.id === 'B1');
  const writeOn = !!caps?.write_enabled;
  const heavyOk = writeOn && !!heavyB?.runnable_today;

  const box = el('div', { class: 'chk-run' });
  const state = el('label', { class: 'chk-check' },
    el('input', {
      type: 'checkbox', id: 'chk-heavy', disabled: !heavyOk,
      title: heavyB?.runnable_today ? '' : (heavyB?.blocked_by || 'B 层本机跑不动'),
    }),
    '连 B 层一起跑（heavy）',
    heavyB?.runnable_today ? null : el('span', { class: 'dim', text: `　跑不动：${heavyB?.blocked_by || '未知原因'}` }));

  const out = el('div', { class: 'chk-run-out' });
  const btn = el('button', {
    class: 'chk-btn primary', type: 'button', disabled: !writeOn,
    text: writeOn ? '跑一次' : '写接口不可用',
    onclick: async () => {
      const heavy = /** @type {HTMLInputElement} */ (state.querySelector('input')).checked;
      btn.disabled = true;
      const old = btn.textContent;
      btn.textContent = heavy ? '正在跑 A+B 层（可能几分钟）…' : '正在跑 A 层…';
      add(clear(out), el('div', { class: 'dim', text: '同步请求，不要关页面。B 层超时后端会真的终止子进程并回 504。' }));
      try {
        const env = await API.checksRun(building, heavy);
        renderResult(out, env.data || {});
        onDone?.(env);
      } catch (e) {
        renderError(out, e instanceof ApiError ? e : new ApiError('unknown', String(e)), building);
      } finally {
        btn.disabled = !writeOn;
        btn.textContent = old;
      }
    },
  });

  add(box,
    el('p', { class: 'dim' },
      '跑完会**回读产物**核对（generated_unix 不早于本次开始时刻、scope 就是这栋），'
      + '成败以回读为准 —— 不看退出码。'),
    el('div', { class: 'chk-toolbar' }, state, btn,
      heavyOk ? null : el('span', { class: 'dim', text: '（B 层的依赖或源图不满足，只能跑 A 层）' })),
    out);

  if (!writeOn) {
    add(box, el('div', { class: 'chk-note warn' },
      el('b', { text: '本进程不允许写' }),
      caps?.write_disabled_reason || '（后端 capabilities 说 write_enabled=false）',
      '。按钮是**先问再画**的结果，不是点下去才回 403。'));
  }
  if (registry?.run) {
    add(box, el('details', { class: 'chk-details' },
      el('summary', { text: '这个端点的口径（引擎写的）' }),
      el('dl', { class: 'chk-meta' },
        el('dt', { text: '模式' }), el('dd', { text: registry.run.mode }),
        el('dt', { text: '并发' }), el('dd', { text: registry.run.concurrency }),
        el('dt', { text: '超时' }), el('dd', { text: `A 层 ${registry.run.layer_a_timeout_s}s / B 层 ${registry.run.layer_b_timeout_s}s` }),
        el('dt', { text: '超时之后' }), el('dd', { text: registry.run.on_timeout }))));
  }
  return box;
}

// 会话与登录 —— 应用外壳在画任何视图**之前**先过这里。
//
// ★★ 这一层是**导航糖，不是权限**。真正的闸在服务端（`backend/api/authz.py`
//    的 `require_cap`，每条路由自己声明）。这里做的判断只决定「顶栏上给不给他
//    看这个入口」，**改一行 JS 就能全绕过去**。任何把它当门的地方都是错的。
//    为什么还要有它：一个只能看的人面前摆着「控制台／作业台／账号」三个入口，
//    点进去全是 403 —— 那是把"你没这个权限"说成了"这个功能坏了"。
//
// ★ 这里**只读服务端给的 caps/scopes**，不在前端重算一遍能力矩阵。
//   前端自己那份 `ROLE_CAPS` 是第 N 份实现，而一个判断多份实现必然漂移
//   （本仓记过：一个判断四份实现，只有一份跟着规则走）。
import { API, ApiError } from './api.js';
import { el, mount } from './dom.js';

/** 当前身份。未登录时是 null。 */
let principal = null;

/**
 * 角色码 → 中文名。
 *
 * ★ 为什么不在前端抄一份 `{builder:'搭建方', ...}`：抄一份就是**第 N 份实现**，
 *   而改名只会改到 `ROLE_SEED` 那一边 —— 顶栏继续印旧名字，账号页印新名字，
 *   两张表在同一个屏幕上对不上，而两边都"有出处"（铁律 018）。
 *   所以翻译表**从 `/api/auth/roles` 现读**，读不到就**原样回码**（不回 undefined）。
 */
let _roleNames = null;

export async function loadRoleNames() {
  try {
    const rs = await API.auth.roles();
    _roleNames = Object.fromEntries((rs || []).map((r) => [r.code, r.name]));
  } catch {
    _roleNames = null;      // 读不到不是错：下面 roleLabel 会回原始码，页面照常
  }
  return _roleNames;
}

export function roleLabel(code) {
  return (_roleNames && _roleNames[code]) || code;
}

export function getPrincipal() { return principal; }

/** 这个人有没有 `cap` 能力（**不分范围**）。导航用，别拿它当门。 */
export function can(cap) {
  return !!principal && Array.isArray(principal.caps) && principal.caps.includes(cap);
}

/** 取会话。★ 这条接口**刻意不回 401** —— 没登录是它的正常输出。 */
export async function loadSession() {
  const d = await API.auth.session();
  principal = d && d.logged_in ? d : null;
  return principal;
}

export async function logout() {
  try { await API.auth.logout(); } finally {
    principal = null;
    // ★ 用 reload 而不是重新走一遍 boot()：所有视图模块都还在内存里，
    //   它们各自缓存着上一个身份的读数（台账、构件清单…）。换个人进来
    //   看到的是**上一个人的缓存**，而屏幕上一切正常 —— 这一类最难发现。
    location.reload();
  }
}

/**
 * 登录页。走对之后调 `onSuccess()`（由 app.js 决定是重跑还是刷新）。
 *
 * ★ 这张表**不能**把上一次的失败原因留在页面上：用户改了用户名再提交，
 *   上一次那句"用户名或口令不对"仍然挂着，看起来像"这次也失败了"。
 *   所以每次提交前先把它清掉。
 * @param {HTMLElement} root
 * @param {{onSuccess?:Function, reason?:string}} opts
 */
export function renderLogin(root, opts = {}) {
  const msg = el('p', { class: 'lg-msg', role: 'status' });
  const say = (text, kind) => {
    msg.textContent = text || '';
    msg.className = 'lg-msg' + (kind ? ' is-' + kind : '');
  };
  if (opts.reason) say(opts.reason, 'warn');

  const user = el('input', {
    class: 'lg-input', type: 'text', name: 'username',
    autocomplete: 'username', required: true, autofocus: true,
    placeholder: '账号（拼音，例如 zhangsan）',
  });
  const pass = el('input', {
    class: 'lg-input', type: 'password', name: 'password',
    autocomplete: 'current-password', required: true,
    placeholder: '口令',
  });
  const btn = el('button', { class: 'lg-btn', type: 'submit', text: '登录' });

  const form = el('form', { class: 'lg-form', autocomplete: 'on' },
    el('label', { class: 'lg-field' }, el('span', { class: 'lg-label', text: '账号' }), user),
    el('label', { class: 'lg-field' }, el('span', { class: 'lg-label', text: '口令' }), pass),
    btn);

  let busy = false;
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (busy) return;
    busy = true;
    btn.disabled = true;
    say('正在登录…', null);
    try {
      const d = await API.auth.login(user.value.trim(), pass.value);
      principal = { ...d, logged_in: true };
      pass.value = '';                       // ★ 别把口令留在 DOM 里
      say('好了，正在进入…', 'ok');
      if (opts.onSuccess) opts.onSuccess(principal);
    } catch (e) {
      // ★ 三条错要**分开说**，因为下一步完全不同：
      //   429 = 等一会儿再来（限流，不是你记错了口令）；
      //   401 = 账号或口令不对；
      //   其他（网络/503）= 后端的问题，重试没用、要找运维。
      //   合成一句"登录失败"，用户会把限流当成记错口令，反复试到把自己锁死。
      if (e instanceof ApiError && e.status === 429) {
        const wait = e.detail && e.detail.retry_after;
        say(`尝试太频繁，请等 ${wait ?? '一会儿'} 秒后再试。`, 'err');
      } else if (e instanceof ApiError && e.status === 401) {
        say('账号或口令不对。', 'err');
      } else if (e instanceof ApiError && e.status === 503) {
        say('后端认不出身份：账号库连不上。这不是你输错了 —— 请联系管理员。', 'err');
      } else {
        say(`登录没成功：${e && e.message ? e.message : String(e)}`, 'err');
      }
      pass.value = '';
      pass.focus();
      btn.disabled = false;
      busy = false;
    }
  });

  mount(root, el('div', { class: 'lg-wrap' },
    el('div', { class: 'lg-card' },
      el('h1', { class: 'lg-title', text: '校园数字孪生平台' }),
      el('p', { class: 'lg-sub', text: '成都理工大学 · 请用管理员分配的账号登录' }),
      form,
      msg,
      el('p', { class: 'lg-foot',
                text: '忘记口令请联系搭建方重置。本系统只在校内网提供服务。' }))));
  user.focus();
  return form;
}

/**
 * 强制改密（`must_change`）。★ 改完**必须**重新登一次：后端会把该账号现有的
 * 全部会话吊销（`revoked_sessions` > 0），手里这张 cookie 已经作废了。
 * 不重登的话，用户接着点任何一处都是 401 —— 而页面上会显示成"接口坏了"。
 */
export function renderMustChange(root, onDone) {
  const msg = el('p', { class: 'lg-msg', role: 'status' });
  const oldPw = el('input', { class: 'lg-input', type: 'password',
    autocomplete: 'current-password', required: true, placeholder: '现在的口令' });
  const newPw = el('input', { class: 'lg-input', type: 'password',
    autocomplete: 'new-password', required: true, minlength: 12,
    placeholder: '新口令（至少 12 位）' });
  const again = el('input', { class: 'lg-input', type: 'password',
    autocomplete: 'new-password', required: true, placeholder: '再输一次' });
  const btn = el('button', { class: 'lg-btn', type: 'submit', text: '改并重新登录' });
  const form = el('form', { class: 'lg-form' },
    el('label', { class: 'lg-field' },
      el('span', { class: 'lg-label', text: '当前口令' }), oldPw),
    el('label', { class: 'lg-field' },
      el('span', { class: 'lg-label', text: '新口令' }), newPw),
    el('label', { class: 'lg-field' },
      el('span', { class: 'lg-label', text: '确认' }), again),
    btn);
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (newPw.value !== again.value) { msg.textContent = '两次输的新口令不一样。'; return; }
    btn.disabled = true;
    msg.textContent = '正在改…';
    try {
      await API.auth.changePw(oldPw.value, newPw.value);
      msg.textContent = '改好了，正在重新登录…';
      await API.auth.login(principal?.username || '', newPw.value);
      onDone();
    } catch (e) {
      msg.textContent = `没改成：${e && e.message ? e.message : String(e)}`;
      btn.disabled = false;
    }
  });
  mount(root, el('div', { class: 'lg-wrap' },
    el('div', { class: 'lg-card' },
      el('h1', { class: 'lg-title', text: '请先改口令' }),
      el('p', { class: 'lg-sub', text: '这是初始口令，必须换成你自己的才能继续。' }),
      form, msg)));
  oldPw.focus();
}

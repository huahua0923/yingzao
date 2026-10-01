// 会话：登录屏与"我现在是谁"。
//
// ★ 这一屏是**闸**，不是装饰。未登录时整个外壳（导航、三维、详情）一行都不装配 ——
//   不是"装配好了再藏起来"。后者会留下一个能被 F12 打开的真实界面，
//   而"藏起来"与"没有"在屏幕上看起来一模一样（本仓铁律里那一族）。
//
// ★ `/api/auth/session` 未登录时回 **200 + logged_in:false**，不是 401 ——
//   所以这里不能靠 catch 401 来判断，必须读字段。

import { API, ApiError } from './api.js';

/**
 * 问一次"我现在是谁"。
 * @returns {Promise<object|null>} 已登录 ⇒ principal；未登录 ⇒ null。
 */
export async function probe() {
  const s = await API.session();
  // ★ `logged_in` 只认**严格真**：后端回 `false`/缺字段/整段读不到，
  //   三种都必须是"没登录"。写 `if (s)` 的话，一个 `{}` 会被读成已登录，
  //   然后外壳装配起来、每个接口 401 —— 屏幕上是一堆"读不到"，
  //   而真原因（你没登录）一个字都不显示。
  if (s?.logged_in !== true) return null;
  return s;
}

/** 把登录屏接上。`onOk(principal)` 在登录成功后调用一次。 */
export function mountLogin(onOk) {
  const gate = document.getElementById('gate');
  const form = document.getElementById('loginform');
  const btn = document.getElementById('loginbtn');
  const msg = document.getElementById('loginmsg');
  const u = document.getElementById('u');
  const p = document.getElementById('p');

  gate.hidden = false;
  // 焦点给用户名 —— 每次开页面都要重新输，省一次点击。`preventScroll` 免得
  // 在窄屏上把整屏滚一下。
  setTimeout(() => u.focus({ preventScroll: true }), 0);

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (btn.disabled) return;
    btn.disabled = true;
    msg.textContent = '';
    try {
      await API.login(u.value.trim(), p.value);
      // ★ 登录成功后**不自己拆这张屏** —— 交给 onOk 走同一条装配路径
      //   （和"刷新页面时带 cookie 直接进来"完全一致）。两条路径装配的话，
      //   就会出现"第一次登录进去少了某块、刷新一下又好了"这种幽灵。
      await onOk();
    } catch (e) {
      // 口令错、被限流、后端没起 —— 三句话各自不同，原样显示后端那句。
      // ★ 不要在 401 上写"用户名或密码错误"：后端口径是不区分
      //   "没这个账号"与"口令不对"，我在这儿替它区分就把它刚关上的那个
      //   账号探测器又打开了。
      msg.textContent = e instanceof ApiError
        ? (e.status === 429 ? e.message : e.message)
        : '登录失败。';
      // ★ 口令**不清空**（打错一个字符时重输整串很烦），但选中它，
      //   这样接着敲就覆盖掉。用户名错误的情况下一改用户名也知道要重输口令。
      p.select();
    } finally {
      btn.disabled = false;
    }
  });

  return {
    hide() { gate.hidden = true; },
    /** 会话过期时被 api.js 喊回来 —— 口令框清空，因为**那一个**已经不能用了。 */
    show(reason) {
      gate.hidden = false;
      p.value = '';
      msg.textContent = reason ?? '';
      setTimeout(() => (u.value ? p : u).focus({ preventScroll: true }), 0);
    },
  };
}

/** 顶栏那行"我是谁"。 */
export function describe(principal) {
  if (!principal) return '';
  const caps = principal.caps ?? [];
  // ★ 角色名是**机器码**（builder / admin / line_admin / viewer），
  //   屏幕上要给人话。这里只做一层翻译，**不是**权限判断 ——
  //   谁能看见什么由后端按 caps/scopes 定，前端一个字都不许自己判。
  const ROLE = { builder: '搭建方', admin: '普通管理员',
                 line_admin: '回线管理员', viewer: '普通人' };
  const roles = (principal.roles ?? []).map((r) => ROLE[r] ?? r);
  // ★ 这三档**不能合成 `n === 0 ? 全校 : N 个范围`** —— 我原来就是这么写的，两档都错：
  //     · `scopes = ['*']` 是**全校**（后端的"覆盖一切"是那个星号，不是"0 个范围"），
  //       而它被印成「1 个范围」⇒ 一个看得见整个校区的账号，屏幕上像被限住了；
  //     · `scopes = []` 是**一个授权都没有**（authz.py:274：有账号没授权 ⇒ 空身份，
  //       能看见的 = 空集），而它被印成「全校」—— 这句比上一句危险得多，
  //       它把"你什么都没有"说成了"你什么都看得到"。
  //   两件完全不同的事印成同一行字，读的人无从分辨。
  const scopes = principal.scopes ?? [];
  const scope = scopes.includes('*') ? '全校'
    : (scopes.length === 0 ? '无范围' : `${scopes.length} 个范围`);
  return {
    roles, caps,
    text: `${roles.join('、') || '（无角色）'} · 可见 ${scope}`,
    mustChange: principal.must_change === true,
  };
}

/** 退出：先让后端把会话作废，再回登录屏。 */
export async function logout() {
  try { await API.logout(); }
  catch { /* 后端不通也要能把人放回登录屏 —— 本地那块 cookie 已经没用了 */ }
  location.reload();
}

// 账号与授权 —— 搭建方专属（后端挂 `require_cap("manage")`）。
//
// 权限模型三个概念必须分开，这一屏也就是三段：
//   · **身份** users           —— 谁（这一屏的左半边）
//   · **角色** roles           —— 一组能力（能干什么；从 `/api/auth/roles` 读，不在这里抄一份）
//   · **授权** grants          —— `(账号, 角色, 范围节点)` 三元组（在哪、以什么身份）
//   角色与范围是**正交**的两维：`admin@c006` 与 `viewer@*` 是两个不同的东西。
//
// ★ 口令只显示一次。库里只有 scrypt 哈希，**找不回来** —— 开号/重置之后那个口令
//   只在这条响应里出现，页面必须把它摆在最显眼的地方，并且说清"关了就没"。
//   放在一个会随下一次操作消失的地方（比如 toast）等于没给。
import { API } from '../api.js';
import { getPrincipal } from '../session.js';
import { el, mount, table, rich } from '../dom.js';

export const label = '账号';

let _roles = [];          // 角色字典（本次加载时的快照）

const deepLink = (p) => `#/account/${encodeURIComponent(p)}`;

/** 一句"给谁看"的范围说明。★ `*` 是**根**，不是"没有"。 */
function scopeText(s) {
  if (!s) return '（空）';
  if (s === '*') return '全校区';
  return s.split('|').join(' · ');
}

/** 角色码 → 中文名。查不到就**原样回码**，不回 "undefined"。 */
function roleName(code) {
  const r = _roles.find((x) => x.code === code);
  return r ? r.name : code;
}

/** 「口令只显示一次」的那块牌子。 */
function pwBanner(pw, note) {
  if (!pw) return null;
  return el('div', { class: 'ac-pw', role: 'alert' },
    el('div', { class: 'ac-pw-h', text: '★ 口令（只显示这一次，关掉就找不回来了）' }),
    el('code', { class: 'ac-pw-v', text: pw }),
    el('p', { class: 'ac-pw-n', text: note || '' }));
}

async function reload(root) {
  const d = await API.auth.users();
  _roles = d.roles || [];
  return d;
}

/**
 * @param {HTMLElement} root
 * @param {string} sub  `#/account/<账号名>` 时是那个人的名字，用来定位一行
 */
export async function render(root, sub) {
  mount(root, el('div', { class: 'loading', text: '正在读账号…' }));
  let d;
  try {
    d = await reload(root);
  } catch (e) {
    mount(root, el('div', { class: 'chk-panic' },
      el('h2', { class: 'chk-panic-h', text: '读不到账号' }),
      el('p', { class: 'chk-panic-msg', text: String(e && e.message ? e.message : e) })));
    return;
  }

  const banner = el('div', { class: 'ac-banner' });     // 口令牌子的位置
  const body = el('div', { class: 'ac-body' });
  const refresh = async () => {
    try { d = await reload(root); } catch (e) {
      mount(banner, el('p', { class: 'ac-err', text: `刷新失败：${e.message}` }));
      return;
    }
    paint();
  };
  const showPw = (pw, note) => { mount(banner, pwBanner(pw, note)); };

  // ── 开号 ────────────────────────────────────────────────────────
  function createBox() {
    const u = el('input', { class: 'ac-in', type: 'text', required: true,
      pattern: '[A-Za-z0-9_.\\-]+', placeholder: 'zhangsan（只能字母数字._-）' });
    const dn = el('input', { class: 'ac-in', type: 'text', placeholder: '张三（显示用，可留空）' });
    const note = el('input', { class: 'ac-in', type: 'text', placeholder: '备注，例如：环工学院 · 2026 秋' });
    const role = el('select', { class: 'ac-in' },
      _roles.map((r) => el('option', { value: r.code,
        text: `${r.name}（${r.caps.join('/') || '无能力'}）` })));
    const scope = el('input', { class: 'ac-in', type: 'text', value: '*',
      placeholder: '范围节点：* 或 c006 或 c006|3' });
    const out = el('p', { class: 'ac-msg' });

    const form = el('form', { class: 'ac-new' },
      el('label', { class: 'ac-f' }, el('span', { class: 'ac-l', text: '账号' }), u),
      el('label', { class: 'ac-f' }, el('span', { class: 'ac-l', text: '姓名' }), dn),
      el('label', { class: 'ac-f' }, el('span', { class: 'ac-l', text: '角色' }), role),
      el('label', { class: 'ac-f' }, el('span', { class: 'ac-l', text: '范围' }), scope),
      el('label', { class: 'ac-f ac-f-wide' }, el('span', { class: 'ac-l', text: '备注' }), note),
      el('div', { class: 'ac-f' },
        el('span', { class: 'ac-l', text: ' ' }),
        el('button', { class: 'ac-btn ac-btn-ok', type: 'submit', text: '开号并生成口令' })),
      out);

    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      out.textContent = '正在建…';
      try {
        const r = await API.auth.createUser({
          username: u.value.trim(), display_name: dn.value.trim(),
          note: note.value.trim(), role_code: role.value,
          scope_node: scope.value.trim() || '*',
        });
        // ★ 口令摆在 banner 里（不在 out 里）—— out 在重新加载这一屏时会被
        //   整块换掉，而那个口令**找不回来**。
        showPw(r.password, r.note);
        u.value = ''; dn.value = ''; note.value = '';
        await refresh();
      } catch (e) {
        out.textContent = `没建成：${e && e.message ? e.message : String(e)}`;
      }
    });
    return el('section', { class: 'ac-sec' },
      el('h2', { text: '开一个号' }),
      el('p', { class: 'ac-hint' },
        rich('账号名要能让人认出来是谁（拼音），它全校可见、也出现在审计里。'
          + '**口令由系统生成、只显示一次**；对方首次登录会被强制改密。')),
      form);
  }

  // ── 一行账号 ────────────────────────────────────────────────────
  function rowOf(u) {
    // ★ 按**账号名**比，不按 id —— `/api/auth/session` 的 `brief()` 里没有
    //   user_id（只有 username / roles / caps / scopes / via）。拿一个不存在的
    //   字段去比，恒为 false ⇒ "停用自己"这颗按钮**永远是可点的**，
    //   而屏幕上一切正常（本仓踩过：字段名不等于字段在）。
    const isMe = u.username === (getPrincipal() && getPrincipal().username);
    const chips = (u.grants || []).map((g) => el('span', { class: 'ac-chip' },
      el('b', { text: roleName(g.role_code) }),
      el('span', { class: 'ac-chip-scope', text: scopeText(g.scope_node) }),
      el('button', { class: 'ac-x', type: 'button', text: '×',
        title: `撤掉「${roleName(g.role_code)} @ ${scopeText(g.scope_node)}」`,
        'aria-label': `撤掉 ${roleName(g.role_code)} 在 ${scopeText(g.scope_node)} 的授权`,
        onclick: async (ev) => {
          ev.preventDefault();
          if (!confirm(`撤掉 ${u.username} 的「${roleName(g.role_code)} @ ${scopeText(g.scope_node)}」？`)) return;
          try { await API.auth.dropGrant(u.id, g.role_code, g.scope_node); await refresh(); }
          catch (e) { alert(`没撤成：${e.message}`); }
        } })));
    if (!chips.length) chips.push(el('span', { class: 'ac-chip ac-chip-none', text: '没有任何授权' }));

    const addRole = el('select', { class: 'ac-in ac-in-s' },
      _roles.map((r) => el('option', { value: r.code, text: r.name })));
    const addScope = el('input', { class: 'ac-in ac-in-s', type: 'text', value: '*',
      placeholder: '范围，如 c006' });

    return el('tr', { class: (u.is_active ? '' : 'ac-off') + (sub === u.username ? ' ac-hit' : '') },
      el('td', {},
        el('a', { class: 'ac-u', href: deepLink(u.username), text: u.username }),
        el('div', { class: 'ac-dn', text: u.display_name || '' })),
      el('td', {}, chips),
      el('td', {}, el('div', { class: 'ac-add' }, addRole, addScope,
        el('button', { class: 'ac-btn', type: 'button', text: '加',
          onclick: async () => {
            try {
              await API.auth.addGrant(u.id, addRole.value, addScope.value.trim() || '*');
              await refresh();
            } catch (e) { alert(`没加上：${e.message}`); }
          } }))),
      el('td', {},
        el('span', { class: 'ac-st ' + (u.is_active ? 'is-on' : 'is-off'),
          text: u.is_active ? '在用' : '已停用' }),
        u.must_change ? el('span', { class: 'ac-st is-wait', text: '待改密' }) : null),
      el('td', { class: 'ac-t' },
        el('div', { text: `建 ${u.created_at || '—'}` }),
        el('div', { text: u.last_login_at ? `末次登录 ${u.last_login_at}` : '从未登录' })),
      el('td', {},
        el('button', { class: 'ac-btn', type: 'button',
          disabled: isMe,
          title: isMe ? '不能停用自己 —— 那会让你立刻失去管理权限，且没人能救回来' : '',
          text: u.is_active ? '停用' : '启用',
          onclick: async () => {
            try { await API.auth.setActive(u.id, !u.is_active); await refresh(); }
            catch (e) { alert(`没改成：${e.message}`); }
          } }),
        el('button', { class: 'ac-btn', type: 'button', text: '重置口令',
          onclick: async () => {
            if (!confirm(`重置 ${u.username} 的口令？他手里所有登录会立刻失效。`)) return;
            try {
              const r = await API.auth.resetPw(u.id);
              showPw(r.password, `这是 ${u.username} 的新口令。${r.note || ''}`);
              await refresh();
            } catch (e) { alert(`没重置成：${e.message}`); }
          } })));
  }

  // ── 汇总 ────────────────────────────────────────────────────────
  function paint() {
    const users = d.users || [];
    const active = users.filter((u) => u.is_active).length;
    const noGrant = users.filter((u) => !(u.grants || []).length).length;
    mount(body,
      el('div', { class: 'ac-stats' },
        el('span', {}, el('b', { text: String(users.length) }), ' 个账号'),
        el('span', {}, el('b', { text: String(active) }), ' 个在用'),
        el('span', { class: noGrant ? 'is-warn' : '' },
          el('b', { text: String(noGrant) }), ' 个没有任何授权'),
        el('span', {}, el('b', { text: String(_roles.length) }), ' 个角色')),
      createBox(),
      el('section', { class: 'ac-sec' },
        el('h2', { text: '账号清单' }),
        table(
          [{ label: '账号' }, { label: '授权（角色 @ 范围）' }, { label: '加授权' },
           { label: '状态' }, { label: '时间' }, { label: '操作' }],
          users.map(rowOf),
          { cls: 'ac-table' })));
  }

  paint();
  mount(root, el('div', { class: 'ac-page' },
    el('h1', { text: '账号与权限' }),
    el('p', { class: 'ac-hint' },
      '身份（谁）、角色（能干什么）、授权（在哪、以什么身份）—— 三者分开。'
      + '权限沿空间树向下继承：在 c006 授权，就自动覆盖它的所有楼层与房间。'),
    banner, body));

  // 定位：`#/account/<账号名>` 时把那一行滚进视野
  if (sub) {
    const hit = root.querySelector('.ac-hit');
    if (hit && hit.scrollIntoView) hit.scrollIntoView({ block: 'center' });
  }
}

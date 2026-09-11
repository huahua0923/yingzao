/* 数字孪生建模控制台 —— 前端逻辑。
 *
 * 设计要点：**参数表与阶段表都不在本文件里**。它们由后端 /api/meta 下发
 * （单一事实源在 backend/web/console_meta.py），本文件只负责渲染与回写。
 * 这样加一个 profile 字段、加一个流程阶段，只改后端一处。
 *
 * 四个面板：
 *   参数 —— 识别参数（档案 profile）+ 构件参数（规格 spec），都是表单
 *   流程 —— 完整阶段链，逐阶段现状（完成 / 过期 / 就地改写 / 需命令行）+ 可跑的按钮
 *   规格 JSON —— spec 原文（与构件参数同一份数据）
 *   预览 —— three.js 加载 GLB
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

const state = {
  buildings: [], current: null, profile: null, spec: null,
  status: null, meta: null, running: false,
};
const findB = (n) => state.buildings.find((x) => x.name === n);

/* ---------------- 元数据 ---------------- */
async function loadMeta() {
  const r = await fetch('/api/meta');
  const j = await r.json();
  if (!j.success) throw new Error('元数据加载失败');
  state.meta = j.data;
}

/* ---------------- 表单渲染（通用） ----------------
 * type: text | num | int | bool | select | list | json
 *   list → 逗号分隔数字，空串 = null（例如 wall_thicknesses / outline_unify_floors）
 *   json → 结构化数组或对象，原样 JSON
 */
function parseList(v, itype) {
  const s = String(v).trim();
  if (!s) return null;
  const parts = s.split(',').map((x) => x.trim()).filter((x) => x !== '');
  const nums = parts.map((x) => (itype === 'int' ? parseInt(x, 10) : parseFloat(x)));
  return nums.some((n) => Number.isNaN(n)) ? NaN : nums;
}

function applyField(obj, f, input) {
  const v = input.value;
  if (f.type === 'int') obj[f.k] = v === '' ? null : parseInt(v, 10);
  else if (f.type === 'num') obj[f.k] = v === '' ? null : parseFloat(v);
  else if (f.type === 'list') obj[f.k] = parseList(v, f.itype);
  else obj[f.k] = v;
}

function fieldRow(obj, f) {
  const wrap = el('label', 'field');
  wrap.appendChild(el('span', 'flabel', f.label));
  let input;
  if (f.type === 'bool') {
    input = el('input', 'cb');
    input.type = 'checkbox';
    input.checked = !!obj[f.k];
    input.onchange = () => { obj[f.k] = input.checked; };
  } else if (f.type === 'select') {
    input = el('select');
    for (const o of (f.options || [])) input.appendChild(el('option', null, o));
    input.value = obj[f.k] ?? '';
    input.onchange = () => { obj[f.k] = input.value; };
  } else if (f.type === 'json') {
    input = el('textarea', 'json');
    input.spellcheck = false;
    input.value = obj[f.k] === undefined || obj[f.k] === null
      ? '' : JSON.stringify(obj[f.k], null, 1);
    input.oninput = () => {
      const t = input.value.trim();
      // 清空 = 显式传 null。不能删键：后端是合并写，删掉会被旧值搬回来
      if (t === '') { obj[f.k] = null; input.style.borderColor = ''; return; }
      try { obj[f.k] = JSON.parse(t); input.style.borderColor = ''; }
      catch (e) { input.style.borderColor = 'var(--err)'; }
    };
  } else {
    input = el('input', 'in');
    input.type = (f.type === 'int' || f.type === 'num') ? 'number' : 'text';
    if (f.step) input.step = f.step;
    if (f.type === 'list') {
      const cur = obj[f.k];
      input.value = Array.isArray(cur) ? cur.join(', ') : (cur ?? '');
      input.placeholder = '逗号分隔，留空=不启用';
    } else {
      input.value = obj[f.k] ?? '';
    }
    input.oninput = () => {
      applyField(obj, f, input);
      input.style.borderColor = Number.isNaN(obj[f.k]) ? 'var(--err)' : '';
    };
  }
  input.id = 'pf-' + f.k;   // 供跨面板联动（如 glb_windows ↔ 流程页开关）
  wrap.appendChild(input);
  if (f.help) wrap.appendChild(el('span', 'fhelp', f.help));
  return wrap;
}

function renderGroups(container, groups, obj) {
  container.innerHTML = '';
  for (const g of groups) {
    const sec = el('section', 'fgroup');
    sec.appendChild(el('h3', null, g.group));
    const grid = el('div', 'fgrid');
    for (const f of g.fields) {
      if (f.type === 'json') continue;          // json 字段单独放到下面的「高级」
      grid.appendChild(fieldRow(obj, f));
    }
    sec.appendChild(grid);
    const jsons = g.fields.filter((f) => f.type === 'json');
    if (jsons.length) {
      const jg = el('div', 'fgrid');
      jg.style.gridTemplateColumns = '1fr';
      for (const f of jsons) jg.appendChild(fieldRow(obj, f));
      sec.appendChild(jg);
    }
    container.appendChild(sec);
  }
}

function colorRow(obj, key, label) {
  const wrap = el('label', 'field');
  wrap.appendChild(el('span', 'flabel', label));
  const row = el('div', 'colorrow');
  const c = el('input', 'cpick'); c.type = 'color';
  const t = el('input', 'in hex'); t.type = 'text'; t.spellcheck = false;
  obj[key] = obj[key] || '#888888';
  c.value = obj[key]; t.value = obj[key];
  c.oninput = () => { t.value = c.value; obj[key] = c.value; };
  t.oninput = () => { if (/^#[0-9a-fA-F]{6}$/.test(t.value)) { c.value = t.value; obj[key] = t.value; } };
  row.appendChild(c); row.appendChild(t);
  wrap.appendChild(row);
  return wrap;
}

function renderProfile() {
  const p = state.profile;
  if (!p || !state.meta) return;
  p.style = p.style || {};
  const form = $('profileForm');
  renderGroups(form, state.meta.profile, p);
  // 外观样式（在 spec 里，但识别时按档案 style 重写，故也放这里）
  const ssec = el('section', 'fgroup');
  ssec.appendChild(el('h3', null, '外观样式 style（识别时写进 spec）'));
  const sgrid = el('div', 'fgrid');
  for (const sk of state.meta.styleKeys) sgrid.appendChild(colorRow(p.style, sk.k, sk.label));
  const roofWrap = el('label', 'field');
  roofWrap.appendChild(el('span', 'flabel', '屋顶形式 roofType'));
  const sel = el('select');
  sel.appendChild(el('option', null, 'flat — 平顶'));
  sel.appendChild(el('option', null, 'gable — 坡顶'));
  sel.value = p.style.roofType || 'gable';
  sel.onchange = () => { p.style.roofType = sel.value; };
  roofWrap.appendChild(sel);
  roofWrap.appendChild(el('span', 'fhelp', '坡顶 = 沿长轴设脊的双坡屋面；平顶 = 屋面板 + 一圈女儿墙'));
  sgrid.appendChild(roofWrap);
  ssec.appendChild(sgrid);
  form.appendChild(ssec);
}

function renderSpecForm() {
  if (!state.meta) return;
  state.spec = state.spec || {};
  renderGroups($('specForm'), state.meta.spec, state.spec);
}

/* ---------------- 楼栋列表 ---------------- */
const chip = (txt, cls) => el('span', 'chip ' + (cls || ''), txt);

function renderList() {
  const q = $('search').value.trim().toLowerCase();
  const box = $('blist');
  box.innerHTML = '';
  for (const b of state.buildings) {
    if (q && !(b.name + b.title).toLowerCase().includes(q)) continue;
    const it = el('div', 'bld' + (state.current === b.name ? ' active' : ''));
    const t = el('div', 't');
    t.appendChild(el('span', null, b.title));
    t.appendChild(el('span', 'n', b.name));
    it.appendChild(t);
    const meta = el('div', 'meta');
    meta.appendChild(chip(b.roofType === 'flat' ? '平顶' : '坡顶', b.roofType));
    meta.appendChild(chip(b.classifier, null));
    meta.appendChild(chip(b.floors + ' 层', null));
    if (b.glbStale) {
      const c = chip('模型过期', 'stale');
      c.title = 'GLB 早于最新楼层数据 —— 改过楼层但没重出模型（点「流程 → 生成 GLB」重出）。'
        + '注意：此判据按文件时间比，拷贝/还原过的旧 GLB 会看起来是新鲜的';
      meta.appendChild(c);
    }
    const dot = el('span', 'gdot' + (b.glb ? ' on' : ''));
    dot.title = b.glb ? 'GLB 已生成' : '无 GLB';
    meta.appendChild(dot);
    it.appendChild(meta);
    if (b.dxfPlan) {
      const row = el('div', 'dxfrow');
      const a = el('a', null, '📐 每层源图纸');
      a.href = `data/buildings/${b.name}/dxf_plan/index.html`;
      a.target = '_blank'; a.rel = 'noopener';
      a.onclick = (ev) => ev.stopPropagation();
      row.appendChild(a);
      it.appendChild(row);
    }
    it.onclick = () => selectBuilding(b.name);
    box.appendChild(it);
  }
}

function renderBadges() {
  const b = state.buildings.find((x) => x.name === state.current);
  if (!b) return;
  const box = $('bBadges');
  box.innerHTML = '';
  box.appendChild(chip(b.name, null));
  box.appendChild(chip(b.roofType === 'flat' ? '平顶' : '坡顶', b.roofType));
  box.appendChild(chip(b.classifier, null));
  box.appendChild(chip(b.floors + ' 层', null));
  box.appendChild(chip(b.glb ? 'GLB ✓' : 'GLB ✗', null));
  box.appendChild(chip(b.source === 'batch' ? '批次楼' : '注册表楼', null));
  const st = state.status;
  if (st) {
    const nStale = st.stages.filter((s) => s.stale).length;
    if (nStale) box.appendChild(chip(`${nStale} 步过期`, 'stale'));
  }
  if (b.dxfPlan) {
    const a = el('a', 'chip', '📐 每层源图纸 ↗');
    a.href = `data/buildings/${b.name}/dxf_plan/index.html`;
    a.target = '_blank'; a.rel = 'noopener';
    a.style.color = 'var(--accent)'; a.style.textDecoration = 'none';
    box.appendChild(a);
  }
}

/* ---------------- 流程图 ---------------- */
function stageState(s) {
  if (s.inplace) return { text: '就地改写', cls: 'manual' };
  if (!s.artifacts.length) return { text: '无产物', cls: '' };
  if (s.stale) return { text: '过期 ⚠', cls: 'warn' };
  if (s.done) return { text: '完成 ✓', cls: 'ok' };
  return { text: '未做', cls: '' };
}

function fmtSize(n) {
  if (!n) return '';
  if (n > 1048576) return (n / 1048576).toFixed(1) + 'MB';
  if (n > 1024) return (n / 1024).toFixed(0) + 'KB';
  return n + 'B';
}

function renderFlow() {
  const box = $('flow');
  box.innerHTML = '';
  const st = state.status;
  if (!st) { box.appendChild(el('div', 'note', '选择一栋楼查看流程进度')); return; }

  for (const s of st.stages) {
    const ss = stageState(s);
    const row = el('div', 'stage' + (s.stale ? ' stale' : (s.done ? ' done' : ''))
      + (s.runnable ? '' : ' manual'));
    row.appendChild(el('div', 'no', String(s.no)));

    const body = el('div', 'body');
    const title = el('div', 'title');
    title.appendChild(el('b', null, s.label));
    title.appendChild(el('span', 'status ' + ss.cls, ss.text));
    title.appendChild(chip(s.scope === 'single' ? '单栋' : (s.scope === 'all' ? '全仓' : '图纸源'),
      null));
    if (s.writes) title.appendChild(chip('写盘', null));
    if (s.slow) title.appendChild(chip('慢', null));
    if (s.danger === 'high') title.appendChild(chip('⚠ 改数据', 'stale'));
    body.appendChild(title);
    if (s.desc) body.appendChild(el('div', 'desc', s.desc));
    if (s.artifacts.length) {
      const txt = s.artifacts.map((a) => a.exists
        ? `${a.rel} ${fmtSize(a.size)}${a.stale ? ' ← 过期' : ''}`
        : `${a.rel} 缺`).join('　|　');
      body.appendChild(el('div', 'arts', txt));
    }
    if (!s.runnable && s.whyManual) body.appendChild(el('div', 'why', '需命令行：' + s.whyManual));
    row.appendChild(body);

    const acts = el('div', 'acts');
    if (s.runnable) {
      const btn = el('button', 'btn sm' + (s.danger === 'high' ? ' danger' : ''),
        s.scope === 'single' ? '运行' : '跑全仓');
      btn.disabled = state.running;
      btn.onclick = () => runStage(s);
      acts.appendChild(btn);
    } else {
      acts.appendChild(el('span', 'status manual', '手动'));
    }
    row.appendChild(acts);
    box.appendChild(row);
  }
}

/* ---------------- 规格 ---------------- */
function renderSpec() {
  $('specJson').value = JSON.stringify(state.spec || {}, null, 2);
}

function setHint(id, text, kind) {
  const h = $(id);
  h.textContent = text;
  h.className = 'hint ' + (kind || '');
}

function setStatus(text, kind) {
  const s = $('status');
  s.textContent = text;
  s.className = 'status ' + (kind || '');
}

function setRunning(on) {
  state.running = on;
  ['btnRecognize', 'btnGlb', 'btnSaveProfile', 'btnSaveSpec', 'btnSaveSpecForm']
    .forEach((i) => { const n = $(i); if (n) n.disabled = on; });
  renderFlow();
}

/* ---------------- 运行 ---------------- */
async function runStage(s) {
  if (s.danger === 'high') {
    const warn = s.whyManual ? '\n\n' + s.whyManual : '';
    if (!window.confirm(`即将运行「${s.label}」：会改写本楼楼层数据（逐层 .orig 备份 + 自动回滚）。\n`
      + `确认继续？${warn}`)) return;
  }
  if (s.scope === 'all' && !window.confirm(`「${s.label}」作用于全部楼，确认运行？`)) return;

  setRunning(true);
  setStatus('运行中…', 'run');
  $('log').textContent = `启动 ${s.label} …\n`;
  const res = await fetch(`/api/buildings/${state.current}/run`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ step: s.id, windows: $('winToggle').checked }),
  });
  const j = await res.json();
  if (!j.success) {
    $('log').textContent = '无法启动: ' + (j.error || '未知错误');
    setStatus('启动失败', 'err');
    setRunning(false);
    return;
  }
  await pollJob(j.data.jobId, s);
}

async function pollJob(jobId, s) {
  const r = await fetch(`/api/jobs/${jobId}`);
  const j = await r.json();
  if (!j.success) return;
  const d = j.data;
  $('log').textContent = d.log || '';
  $('log').scrollTop = $('log').scrollHeight;
  if (d.running) { setTimeout(() => pollJob(jobId, s), 700); return; }
  setRunning(false);
  const ok = d.code === 0;
  setStatus(ok ? '完成 ✓' : '失败 ✗', ok ? 'ok' : 'err');
  await refreshBuildings();
  await refreshStatus();
  if (ok && (s.id === 'glb' || s.id === 'recognize' || s.id === 'full')) reloadPreview();
}

/* ---------------- 预览 ---------------- */
const viewer = { renderer: null, scene: null, camera: null, controls: null, loader: null, obj: null, inited: false };

function initViewer() {
  const holder = $('viewer');
  viewer.renderer = new THREE.WebGLRenderer({ antialias: true });
  viewer.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  viewer.renderer.setSize(holder.clientWidth, holder.clientHeight);
  holder.appendChild(viewer.renderer.domElement);
  viewer.scene = new THREE.Scene();
  viewer.scene.background = new THREE.Color(0x10151d);
  viewer.camera = new THREE.PerspectiveCamera(50, holder.clientWidth / holder.clientHeight, 0.1, 4000);
  viewer.camera.position.set(60, 40, 60);
  viewer.controls = new OrbitControls(viewer.camera, viewer.renderer.domElement);
  viewer.controls.target.set(0, 10, 0);
  viewer.controls.enableDamping = true;
  viewer.scene.add(new THREE.HemisphereLight(0xe8f1fb, 0x22272e, 1.0));
  const dir = new THREE.DirectionalLight(0xffffff, 1.7); dir.position.set(80, 140, 60); viewer.scene.add(dir);
  const dir2 = new THREE.DirectionalLight(0xffffff, 0.4); dir2.position.set(-70, 40, -50); viewer.scene.add(dir2);
  viewer.scene.add(new THREE.GridHelper(240, 24, 0x3a4654, 0x212a34));
  viewer.loader = new GLTFLoader();
  viewer.inited = true;
  const loop = () => { requestAnimationFrame(loop); viewer.controls.update(); viewer.renderer.render(viewer.scene, viewer.camera); };
  loop();
  window.addEventListener('resize', () => {
    if (!viewer.renderer) return;
    viewer.camera.aspect = holder.clientWidth / holder.clientHeight;
    viewer.camera.updateProjectionMatrix();
    viewer.renderer.setSize(holder.clientWidth, holder.clientHeight);
  });
}

function reloadPreview() {
  const b = state.buildings.find((x) => x.name === state.current);
  if (!b) return;
  if (!b.glb) { $('previewHint').textContent = '尚未生成 GLB，先跑「流程 → 生成 GLB」'; $('previewHint').className = 'hint'; return; }
  if (!viewer.inited) initViewer();
  const overlay = $('viewerOverlay');
  overlay.textContent = '加载中…';
  $('previewHint').textContent = '加载 ' + b.glbRel;
  $('previewHint').className = 'hint';
  viewer.loader.load(`/data/${b.glbRel}?t=${Date.now()}`, (gltf) => {
    if (viewer.obj) viewer.scene.remove(viewer.obj);
    viewer.obj = gltf.scene;
    viewer.scene.add(viewer.obj);
    const box = new THREE.Box3().setFromObject(viewer.obj);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const d = Math.max(size.x, size.y, size.z) * 1.7 || 80;
    viewer.camera.position.set(center.x + d * 0.75, center.y + d * 0.6, center.z + d * 0.95);
    viewer.controls.target.copy(center);
    viewer.controls.update();
    overlay.textContent = '';
    $('previewHint').textContent = '已加载 ' + b.glbRel;
    $('previewHint').className = 'hint ok';
  }, (xhr) => {
    if (xhr.total) overlay.textContent = '加载 ' + Math.round(xhr.loaded / 1048576) + ' / ' + Math.round(xhr.total / 1048576) + ' MB';
  }, (err) => {
    overlay.textContent = '加载失败';
    $('previewHint').textContent = '加载失败: ' + (err.message || err);
    $('previewHint').className = 'hint err';
  });
}

/* ---------------- 导出合成窗口径 ----------------
   为什么单独一组函数：所有 floor JSON 的窗都是 synthetic=True，而 run_step /
   run_building --glb 的 INCLUDE_SYNTHETIC_WINDOWS 默认 False。也就是说
   「生成 GLB」这个按钮**不勾选就会把窗户全剥掉**，且没有任何报错。
   这个口径必须记在楼栋档案里，而不是每次点按钮时重新猜。 */
function refreshWinHint() {
  const h = $('winHint');
  if (!h) return;
  const rec = !!(state.profile && state.profile.glb_windows);
  const cur = !!(state.profile && $('winToggle').checked);
  h.textContent = rec
    ? (cur ? '本楼档案口径：带合成窗 ✓' : '本楼档案口径：带合成窗，当前开关未勾选 —— 重出会剥掉窗户')
    : (cur ? '本楼档案口径：不带窗，当前开关已勾选 —— 重出会加上窗户' : '本楼档案口径：不带窗');
  h.className = 'hint' + (rec === cur ? '' : ' err');
}

/* 只把档案值映到开关上，不写盘（选中楼栋时用） */
function applyWinToggle(on) {
  const t = $('winToggle');
  if (t) t.checked = !!on;
  const cb = document.getElementById('pf-glb_windows');
  if (cb) cb.checked = !!on;
  refreshWinHint();
}

/* 用户在流程页改了开关 → 记进档案 */
async function onWinToggleChange() {
  refreshWinHint();
  if (!state.profile) return;
  state.profile.glb_windows = $('winToggle').checked;
  const cb = document.getElementById('pf-glb_windows');
  if (cb) cb.checked = state.profile.glb_windows;
  const res = await fetch(`/api/buildings/${state.current}/profile`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state.profile),
  });
  const j = await res.json();
  if (!j.success) setHint('winHint', '口径未能记入档案: ' + j.error, 'err');
  else refreshWinHint();
}

/* ---------------- 保存 ---------------- */
async function saveProfile() {
  const p = state.profile;
  const res = await fetch(`/api/buildings/${state.current}/profile`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p),
  });
  const j = await res.json();
  setHint('profileHint', j.success ? '已保存 ✓（下次「识别」生效）' : ('保存失败: ' + j.error),
    j.success ? 'ok' : 'err');
  if (j.success) await refreshBuildings();
}

async function saveSpecObj(obj, hintId) {
  const res = await fetch(`/api/buildings/${state.current}/spec`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj),
  });
  const j = await res.json();
  setHint(hintId, j.success ? '已保存 ✓（下次「生成 GLB」生效）' : ('保存失败: ' + j.error),
    j.success ? 'ok' : 'err');
}

/* ---------------- 载入 ---------------- */
async function refreshBuildings() {
  const r = await fetch('/api/buildings');
  const j = await r.json();
  if (j.success) {
    state.buildings = j.data;
    renderList();
    renderBadges();
    const stale = j.data.filter((b) => b.glbStale).length;
    const nGlb = j.data.filter((b) => b.glb).length;
    $('topInfo').textContent = `${j.data.length} 栋楼 · GLB ${nGlb}`
      + (stale ? `（${stale} 栋过期）` : '')
      + ` · ${state.meta ? state.meta.pipeline.length : '?'} 个流程阶段 · 本地 127.0.0.1`;
  }
}

async function refreshStatus() {
  if (!state.current) return;
  try {
    const r = await fetch(`/api/buildings/${state.current}/status`);
    const j = await r.json();
    state.status = j.success ? j.data : null;
  } catch (e) { state.status = null; }
  renderFlow();
  renderBadges();
}

async function selectBuilding(name) {
  state.current = name;
  const b = state.buildings.find((x) => x.name === name);
  $('bTitle').textContent = b ? b.title : name;
  $('btnDxfPlan').style.display = (b && b.dxfPlan) ? '' : 'none';
  $('btnCompare').style.display = (b && b.compare) ? '' : 'none';
  renderList();
  setHint('profileHint', ''); setHint('specHint', ''); setHint('specFormHint', ''); setHint('previewHint', '');
  setStatus('就绪', 'idle');

  const pr = await fetch(`/api/buildings/${name}/profile`);
  const pj = await pr.json();
  state.profile = pj.success ? pj.data : null;
  renderProfile();
  applyWinToggle(state.profile && state.profile.glb_windows);

  const sr = await fetch(`/api/buildings/${name}/spec`);
  const sj = await sr.json();
  state.spec = sj.success ? sj.data : {};
  renderSpecForm();
  renderSpec();

  await refreshStatus();
  $('log').textContent = '';
  $('viewerOverlay').textContent = b && b.glb ? '点击「重新加载 GLB」预览' : '生成 GLB 后在此预览';
}

/* ---------------- 事件 ---------------- */
function wire() {
  $('search').oninput = renderList;
  $('btnSaveProfile').onclick = saveProfile;
  $('btnSaveSpec').onclick = () => {
    let obj;
    try { obj = JSON.parse($('specJson').value); }
    catch (e) { setHint('specHint', 'JSON 解析失败: ' + e.message, 'err'); return; }
    state.spec = obj; renderSpecForm();
    saveSpecObj(obj, 'specHint');
  };
  $('btnSaveSpecForm').onclick = () => {
    const bad = state.meta.spec.some((g) => g.fields.some((f) => Number.isNaN(state.spec[f.k])));
    if (bad) { setHint('specFormHint', '有字段不是合法数字（红框处）', 'err'); return; }
    saveSpecObj(state.spec, 'specFormHint').then(renderSpec);
  };
  $('btnFillSpecDefault').onclick = () => {
    const d = state.meta.specDefaults || {};
    let n = 0;
    for (const k of Object.keys(d)) {
      if (state.spec[k] === undefined || state.spec[k] === null) { state.spec[k] = d[k]; n++; }
    }
    renderSpecForm(); renderSpec();
    setHint('specFormHint', n ? `已按默认值补齐 ${n} 项，记得保存` : '没有缺失项', 'ok');
  };
  $('btnFmtSpec').onclick = () => {
    try { $('specJson').value = JSON.stringify(JSON.parse($('specJson').value), null, 2); }
    catch (e) { setHint('specHint', 'JSON 解析失败: ' + e.message, 'err'); }
  };
  $('btnRecognize').onclick = () => runStage({ id: 'recognize', label: '识别出图', scope: 'single' });
  $('btnGlb').onclick = () => runStage({ id: 'glb', label: '生成 GLB', scope: 'single' });
  $('btnRefreshStatus').onclick = refreshStatus;
  $('winToggle').onchange = onWinToggleChange;
  // 参数页里的同名复选（⑩ 建模输出口径）改动后，流程页开关跟着动
  $('profileForm').addEventListener('change', (e) => {
    if (e.target.id === 'pf-glb_windows') applyWinToggle(e.target.checked);
  });
  $('btnDxfPlan').onclick = () => {
    const b = findB(state.current);
    if (b && b.dxfPlan) window.open(`data/buildings/${b.name}/dxf_plan/index.html`, '_blank');
  };
  $('btnCompare').onclick = () => {
    const b = findB(state.current);
    if (b && b.compare) window.open(`data/buildings/${b.name}/compare.html`, '_blank');
  };
  $('btnRefresh').onclick = reloadPreview;
  document.querySelectorAll('.tab').forEach((t) => {
    t.onclick = () => {
      document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
      document.querySelectorAll('.panel').forEach((x) => x.classList.remove('active'));
      t.classList.add('active');
      $('panel-' + t.dataset.tab).classList.add('active');
    };
  });
  document.querySelectorAll('.subtab').forEach((t) => {
    t.onclick = () => {
      document.querySelectorAll('.subtab').forEach((x) => x.classList.remove('active'));
      t.classList.add('active');
      $('sub-recog').style.display = t.dataset.sub === 'recog' ? '' : 'none';
      $('sub-model').style.display = t.dataset.sub === 'model' ? '' : 'none';
    };
  });
}

/* ---------------- 启动 ---------------- */
wire();
try {
  await loadMeta();
} catch (e) {
  $('topInfo').textContent = '元数据加载失败: ' + e.message;
}
await refreshBuildings();
if (state.buildings.length) {
  const first = state.buildings.find((x) => x.name === 'lihua') || state.buildings[0];
  await selectBuilding(first.name);
}

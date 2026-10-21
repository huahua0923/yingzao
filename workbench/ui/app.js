/* 建模工作台前端 —— 无框架；所有状态来自服务端现场读盘。
   路由：#/  总览矩阵  #/b/<bid>  单栋  #/params  参数  #/run  执行 */
(() => {
  "use strict";
  const main = document.getElementById("main");
  const dlg = document.getElementById("dlg");
  const dlgT = document.getElementById("dlg-t");
  const dlgSub = document.getElementById("dlg-sub");
  const dlgInput = document.getElementById("dlg-input");
  const dlgHint = document.getElementById("dlg-hint");
  const GATES = ["J-10.8-00", "J-10.8-01", "J-10.9-07"];
  // 页面上先给「人话」名字，编号作小字注释（名字表由服务端 gate_info 下发）。
  const gi = (info, g) => (info && info[g]) || { 名: g, 副: "" };
  const state = { ov: null, filter: "all", q: "", job: null };

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  const bytes = (n) => {
    if (n == null) return "—";
    const u = ["B", "KB", "MB", "GB"]; let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return (i ? v.toFixed(1) : v) + " " + u[i];
  };
  const short = (p) => String(p || "").replace(/^.*[\\/](?=[^\\/]+$)/, "");
  const stamp = (s) => s ? String(s).replace("T", " ").slice(0, 19) : "—";

  function toast(msg, bad) {
    const d = document.createElement("div");
    if (bad) d.className = "bad";
    d.textContent = msg;
    document.getElementById("toast").appendChild(d);
    setTimeout(() => d.remove(), bad ? 7000 : 4200);
  }

  async function api(path, opt) {
    const r = await fetch(path, opt);
    const j = await r.json().catch(() => ({ ok: false, error: "返回不是 JSON" }));
    if (!r.ok || j.ok === false) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }
  const post = (p, o) => api(p, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(o)
  });

  function ask({ title, sub, value, hint }) {
    return new Promise((resolve) => {
      dlgT.textContent = title;
      dlgSub.textContent = sub || "";
      dlgHint.innerHTML = hint || "";
      dlgInput.value = value == null ? "" : String(value);
      const done = () => {
        dlg.removeEventListener("close", done);
        resolve(dlg.returnValue === "ok" ? dlgInput.value : null);
      };
      dlg.returnValue = "";
      dlg.addEventListener("close", done);
      dlg.showModal();
      dlgInput.focus();
      dlgInput.select();
    });
  }

  const passLabel = (c) => {
    if (!c) return ["na", "—"];
    if (c.missing) return ["unk", "没跑过"];
    // ★ verdict 里条数在 counts 里；overview 里已摊平到顶层 —— 两处都认
    const red = c.red != null ? c.red : (c.counts || {}).red;
    const un = c.unmeasured != null ? c.unmeasured : (c.counts || {}).unmeasured;
    if (c.pass === true) return ["pass", "✔ 通过"];
    if (c.pass === false) return ["fail", "✗ " + (red == null ? "" : red + " 条")];
    return ["unk", "? 没量到" + (un ? " " + un + " 条" : "")];
  };

  /* ---------------- 路由 ---------------- */
  function route() {
    const h = location.hash || "#/";
    const m = h.match(/^#\/b\/([A-Za-z0-9_]+)(?:\?g=([\w.\-]+))?/);
    document.querySelectorAll(".rail nav a").forEach(a => a.classList.remove("on"));
    if (m) {
      document.querySelector('[data-nav="overview"]')?.classList.add("on");
      return renderBuilding(m[1], m[2]);
    }
    if (h.startsWith("#/params")) {
      document.querySelector('[data-nav="params"]')?.classList.add("on");
      return renderParams();
    }
    if (h.startsWith("#/run")) {
      document.querySelector('[data-nav="run"]')?.classList.add("on");
      return renderRun();
    }
    if (h.startsWith("#/flow")) {
      document.querySelector('[data-nav="flow"]')?.classList.add("on");
      return renderFlow();
    }
    if (h.startsWith("#/model")) {
      document.querySelector('[data-nav="model"]')?.classList.add("on");
      return renderModel();
    }
    if (h.startsWith("#/draw")) {
      document.querySelector('[data-nav="draw"]')?.classList.add("on");
      return renderDraw();
    }
    if (h.startsWith("#/rooms")) {
      document.querySelector('[data-nav="rooms"]')?.classList.add("on");
      return renderRooms();
    }
    if (h.startsWith("#/photo")) {
      document.querySelector('[data-nav="photo"]')?.classList.add("on");
      return renderPhoto();
    }
    if (h.startsWith("#/lib")) {          // 旧链接：#/lib 两库合一页，现在分家
      location.hash = "#/draw";
      return;
    }
    document.querySelector('[data-nav="overview"]')?.classList.add("on");
    return renderOverview();
  }
  window.addEventListener("hashchange", route);

  function head(kicker, title, block) {
    return `<header class="sheet-head">
      <div><div class="kicker">${esc(kicker)}</div><h1>${title}</h1></div>
      <div class="titleblock">${block}</div></header>`;
  }

  /* 楼栋显示名一律「编号 + 建筑名」：只给编号时看不出是哪栋。
     名称来自 楼栋.json 的 title（库接口在出口处已补 `名称`）。 */
  const NAMES = {};
  function noteNames(lib) {
    for (const [bid, b] of Object.entries((lib || {})["楼栋"] || {})) {
      if (b && (b["名称"] || b["title"])) NAMES[bid] = b["名称"] || b["title"];
    }
    // 总览接口的 bids 是数组，字段是 bid/title（与库接口的 {楼栋:{}} 形状不同）
    for (const r of (lib || {}).bids || []) {
      if (r && r.bid && r.title) NAMES[r.bid] = r.title;
    }
  }
  function bname(bid, title) {
    const t = title == null ? (NAMES[bid] || "") : title;
    return t ? `${bid} ${t}` : String(bid);
  }

  /* ---------------- 总览 ---------------- */
  async function renderOverview() {
    main.innerHTML = `<p class="empty">读盘中…</p>`;
    try {
      const ov = await api("/api/overview");
      state.ov = ov;
      document.getElementById("rail-time").textContent = stamp(ov.generated_at);
      paintOverview();
    } catch (e) {
      main.innerHTML = `<div class="note">读不到总览：${esc(e.message)}</div>`;
    }
  }

  function paintOverview() {
    const ov = state.ov;
    const rows = ov.bids;
    const nPack = rows.filter(r => r.pack && r.pack.exists).length;
    const nStale = rows.filter(r => r.pack && r.pack.stale).length;
    const nRed = rows.reduce((s, r) => s + (r.red || 0), 0);
    const nUn = rows.reduce((s, r) => s + (r.unmeasured || 0), 0);
    const nFail = rows.filter(r => r.red > 0).length;

    const visible = rows.filter(r => {
      const hay = (r.bid + " " + r.title).toLowerCase();
      if (state.q && !hay.includes(state.q.toLowerCase())) return false;
      if (state.filter === "red") return r.red > 0;
      if (state.filter === "unk") return r.unmeasured > 0;
      if (state.filter === "green") return r.red === 0 && r.unmeasured === 0;
      if (state.filter === "stale") return r.pack && r.pack.stale;
      return true;
    });

    main.innerHTML =
      head("判据矩阵 · 现场读数",
        `六十七栋楼，<span class="thin">哪一栋红了</span>`,
        `<b>生成</b>${esc(stamp(ov.generated_at))}<br>
         <b>判据</b>${ov.gates.map(g => esc(gi(ov.gate_info, g).名)).join(" · ")}<br>
         <b>数据</b>rebuild/构件库 + gates/_out`) +
      `<div class="tally">
        <div><div class="n">${rows.length}</div><div class="l">楼栋</div></div>
        <div class="ok"><div class="n">${nPack}</div><div class="l">有交付包</div></div>
        <div class="bad"><div class="n">${nFail}</div><div class="l">有红的栋</div></div>
        <div class="bad"><div class="n">${nRed}</div><div class="l">红条目</div></div>
        <div class="warn"><div class="n">${nUn}</div><div class="l">没量到</div></div>
        <div class="warn"><div class="n">${nStale}</div><div class="l">包过期</div></div>
      </div>
      ${(ov.fix_counts || []).length ? `<div class="fixbar">
        <span class="fl">红往哪改 · 先修涉及面最大的</span>
        ${ov.fix_counts.map(x => {
          const d = (ov.fix_info || {})[x.方向] || {};
          return `<span class="fchip" title="${esc(d.说明 || "")}　动：${esc(d.动 || "")}　之后：${esc(d.后 || "")}">
            <b>${esc(x.方向)}</b><em>${x.栋} 栋 / ${x.条} 条</em></span>`;
        }).join("")}
      </div>` : ""}
      <div class="bar">
        <input type="search" id="q" placeholder="搜楼栋 id 或名称…" value="${esc(state.q)}">
        <div class="seg" id="seg">
          ${[["all", "全部"], ["red", "有红"], ["unk", "没量到"], ["green", "全绿"], ["stale", "包过期"]]
            .map(([k, l]) => `<button data-f="${k}" class="${state.filter === k ? "on" : ""}">${l}</button>`).join("")}
        </div>
        <span class="hint" style="margin:0 0 0 auto">${visible.length} / ${rows.length} 栋</span>
      </div>
      <div class="matrix-wrap"><table class="matrix">
        <thead><tr><th>楼栋</th><th>层</th><th>包</th>
          ${ov.gates.map(g => {
            const info = gi(ov.gate_info, g);
            return `<th title="${esc(info.副)}">${esc(info.名)}<span class="gid">${esc(g)}</span></th>`;
          }).join("")}<th style="text-align:right">红</th></tr></thead>
        <tbody>${visible.map(r => {
          const cells = ov.gates.map(g => {
            const c = r.gates[g] || {};
            const [cls, lab] = passLabel(c);
            // ★ 2026-10-19：红格/黄格直接印第一句原因（哪层哪件、实测多少、阈值多少），
            //   其余句子进悬浮。原来只印「✗ N 条」⇒ 用户看不到具体原因。
            const why = c.why || [];
            const one = why[0] || "";
            const tip = [g, c.measured_at, c.note].concat(why).filter(Boolean).join("\n");
            return `<td class="cell ${cls}"><a href="#/b/${r.bid}?g=${g}" title="${esc(tip)}">
              <b class="cl">${esc(lab)}</b>${one ? `<i class="cw">${esc(one)}</i>` : ""}</a></td>`;
          }).join("");
          const p = r.pack || {};
          const pk = !p.exists ? `<span class="stale">缺包</span>`
            : `${bytes(p.bytes)}${p.stale ? ` <span class="stale">·过期</span>` : ""}`;
          return `<tr>
            <td class="bidcell"><a href="#/b/${r.bid}"><span class="b">${esc(r.bid)}</span><span class="t">${esc(r.title)}</span></a></td>
            <td class="num">${r.floors == null ? "—" : (r.basement ? esc(r.basement) + "+" : "") + r.floors}</td>
            <td class="num">${pk}</td>
            ${cells}
            <td class="num" style="color:${r.red ? "var(--red)" : "var(--muted)"}">${r.red || "·"}</td>
          </tr>`;
        }).join("")}</tbody>
      </table></div>
      <p class="hint">绿=通过 · 红=判红（格内是条数） · 黄=没量到（<b>不是通过</b>，铁律 199） · 灰=没跑过。点格进单栋。</p>`;

    const q = document.getElementById("q");
    q.addEventListener("input", (e) => {
      state.q = e.target.value; paintOverview();
      const q2 = document.getElementById("q"); q2.focus(); q2.setSelectionRange(q2.value.length, q2.value.length);
    });
    document.getElementById("seg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-f]"); if (!b) return;
      state.filter = b.dataset.f; paintOverview();
    });
  }

  /* ---------------- 单栋 ---------------- */
  async function renderBuilding(bid, focusGate) {
    main.innerHTML = `<p class="empty">读 ${esc(bid)} 的件与读数…</p>`;
    try {
      const b = await api("/api/building?bid=" + encodeURIComponent(bid));
      document.getElementById("rail-time").textContent = stamp(b.generated_at);
      paintBuilding(b, focusGate);
    } catch (e) {
      main.innerHTML = `<a class="back" href="#/">← 总览</a><div class="note">${esc(e.message)}</div>`;
    }
  }

  function gateStrip(v, info) {
    return `<div class="gates">${GATES.map(g => {
      const c = v[g] || {};
      const [cls, lab] = passLabel(c);
      const it = gi(info, g);
      return `<div class="g ${cls}" id="g-${g}">
        <div class="gn">${esc(it.名)}<span class="gid">${esc(g)}</span></div>
        <div class="gv">${esc(lab)}</div>
        <div class="gd">${c.missing ? "没跑过" : esc(stamp(c.measured_at))}</div></div>`;
    }).join("")}</div>`;
  }

  function fixList(v, fixInfo) {
    const groups = new Map();
    for (const g of GATES) {
      for (const it of (v[g].items || [])) {
        if (it.status === "skip") continue;
        const key = it.status === "unmeasured" ? "没量到（不是红）" : (it.fix || "待判方向");
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push({ ...it, gate: g });
      }
    }
    if (!groups.size) return `<div class="note ok">三把尺子都没报红。</div>`;
    const order = ["改档案字段", "补足迹声明", "改源图", "改算法", "既有已知红", "待判方向", "没量到（不是红）"];
    const keys = [...groups.keys()].sort((a, b) => order.indexOf(a) - order.indexOf(b));
    const def = (k) => {
      const d = (fixInfo || {})[k === "待判方向" ? "待判" : k];
      return d ? `${esc(d.说明)} · 动：${esc(d.动)} · 之后：${esc(d.后)}` : "";
    };
    return keys.map(k => `
      <div class="fixgroup"><div class="fx">${esc(k)}<i>${groups.get(k).length} 条 · 按这个方向改</i></div>
      ${def(k) ? `<div class="fxdef">${def(k)}</div>` : ""}
      ${groups.get(k).map(it => `<div class="item">
        <div class="r ${it.status === "unmeasured" ? "un" : ""}">${esc(it.rule || (it.status === "unmeasured" ? "?" : "·"))}</div>
        <div><div class="x">${esc(it.text)}</div>
        <div class="meta">${esc(it.gate)}${it.floor ? " · " + esc(it.floor) : ""}${it.evidence ? " · " + esc(it.evidence) : ""}</div></div>
      </div>`).join("")}</div>`).join("");
  }

  function stepsHtml(steps) {
    return `<div class="steps">${steps.map(s => `
      <div class="step ${s.ok ? "ok" : "no"}">
        <span class="sn">${s.ok ? "✔" : "✗"}</span>
        <span>${esc(s.name)}</span>
        <span class="sp">${esc(s.path)}</span>
        <span class="sm">${s.exists ? (s.dir ? s.files + " 件 · " : "") + bytes(s.bytes) + " · " + esc(s.mtime || "") : "缺"}</span>
      </div>`).join("")}</div>`;
  }

  function profileRows(b) {
    const p = b.profile;
    const out = [];
    const row = (k, v, editable) => out.push(`<tr>
      <th>${esc(k)}</th>
      <td class="v" ${k === "scope" ? 'style="font-family:var(--sans)"' : ""}>${k === "roof_stair"
        ? (v ? "有 · 周边墙高 3.5 m" : "没有")
        : esc(typeof v === "object" ? JSON.stringify(v) : v)}</td>
      <td class="act">${editable ? `<button class="btn ghost" data-pf="${esc(k)}">改</button>` : ""}</td></tr>`);
    for (const k of Object.keys(p)) {
      if (k === "drawing" || k === "scope") continue;
      if (k === "roof_stair") {
        out.push(`<tr><th>roof_stair</th><td class="v">${p[k]
          ? "有 · 周边墙高 3.5 m" : "没有"}</td>
          <td class="act"><button class="btn ghost" data-rstair="1" title="CAD 源图没有出屋面层时，直接设为没有；保存后从「建件」重跑">${p[k] ? "设为没有" : "设为有"}</button></td></tr>`);
      } else {
        row(k, p[k], true);
      }
    }
    if (p.scope) row("scope", p.scope, true);
    if (p.drawing) {
      for (const k of Object.keys(p.drawing)) row("drawing." + k, p.drawing[k], true);
    }
    return out.join("");
  }

  function paintBuilding(b, focusGate) {
    const p = b.pack || {};
    main.innerHTML = `
      <a class="back" href="#/">← 总览</a>
      ${head(`楼栋 ${b.bid} · 现场读数`,
        `${esc(bname(b.bid, b.title))}<span class="thin"> · ${b.floors.length} 层${b.profile.basement ? " + " + esc(b.profile.basement) : ""}</span>`,
        `<b>数据根</b>${esc(b.root)}<br><b>出件名</b>${esc(b.out_name)}<br>
         <b>生成</b>${esc(stamp(b.generated_at))}`)}
      <div class="cols">
        <div>
          <section class="block"><h2>判据 <small>三把尺子</small></h2>
            ${gateStrip(b.verdicts, b.gate_info)}
            <h3>修正清单 —— 每条红都带方向</h3>
            ${fixList(b.verdicts, b.fix_info)}
            <details class="hint" style="margin-top:14px"><summary>三把尺子各自的盲区（量不到什么）</summary>
              ${GATES.map(g => {
                const bl = (b.verdicts[g].blind || []);
                return `<p><b>${esc(gi(b.gate_info, g).名)}</b>（${esc(g)}）：${bl.length ? bl.map(x => esc(x)).join("；") : "未声明"}</p>`;
              }).join("")}
            </details>
          </section>

          <section class="block"><h2>生成依据链 <small>每一步都要有件</small></h2>
            ${stepsHtml(b.steps)}
            <p class="hint">判「这一步跑没跑成」只看它<b>该出的那件在不在</b>（不是退出码）——缺的件就是断点。</p>
          </section>

          <section class="block"><h2>楼栋档案 <small>rebuild/构件库/楼栋.json · ${esc(b.bid)}</small></h2>
            <table class="kv">${profileRows(b)}</table>
            <p class="hint">改完要按「影响步骤」重跑；层高<b>不在</b>这里，唯一真源是参数.json::共用/层高。</p>
          </section>
        </div>

        <aside>
          <section class="block"><h2>交付包</h2>
            ${p.exists ? `
              <table class="kv">
                <tr><th>时刻</th><td class="v">${esc(stamp(p.created_at))}</td></tr>
                <tr><th>大小</th><td class="v">${bytes(p.bytes)} · ${p.n_artifacts} 件</td></tr>
                <tr><th>sha256</th><td class="v" style="word-break:break-all">${esc(p.package_sha256 || "—")}</td></tr>
                <tr><th>包内最新</th><td class="v">${esc(stamp(p.newest_artifact))}</td></tr>
              </table>
              ${p.stale ? `<div class="note warn">包时刻早于包内某件 ⇒ 这包没把最新件装进去。</div>` : ""}
              <p class="hint">${esc(p.dir)}</p>` : `<div class="note">还没有交付包。</div>`}
          </section>
          <section class="block"><h2>重跑</h2>
            <p class="hint">按档案的影响面选起点，别无脑从「切图幅」全跑。</p>
            <button class="btn primary" id="run-here">跑到这栋…</button>
          </section>
          <section class="block"><h2>参数</h2>
            <p class="hint">${countParams(b.params)} 个参数，每个都有 标注 / 出处 / 作用。</p>
            <a class="btn" href="#/params">去参数页看依据 →</a>
          </section>
        </aside>
      </div>`;

    main.querySelectorAll("[data-pf]").forEach(btn => {
      btn.addEventListener("click", () => editProfile(b, btn.dataset.pf));
    });
    main.querySelectorAll("[data-rstair]").forEach(btn => {
      btn.addEventListener("click", () => toggleRoofStair(b));
    });
    document.getElementById("run-here").addEventListener("click", () => {
      location.hash = "#/run?bid=" + encodeURIComponent(b.bid);
    });
    if (focusGate) {
      const el = document.getElementById("g-" + focusGate);
      if (el) el.scrollIntoView({ block: "center" });
    }
  }

  async function toggleRoofStair(b) {
    const next = !b.profile.roof_stair;
    try {
      const r = await post("/api/profile/save", { bid: b.bid, 字段: "roof_stair", 值: next });
      toast(`出屋面楼梯间已设为「${next ? "有" : "没有"}」；请从「建件」重跑。备份 ${short(r.backup)}`);
      renderBuilding(b.bid);
    } catch (e) {
      toast("保存被拒：" + e.message, true);
    }
  }

  function countParams(params) {
    let n = 0;
    const w = (o) => {
      for (const k of Object.keys(o || {})) {
        const v = o[k];
        if (v && typeof v === "object" && "值" in v) n++;
        else if (v && typeof v === "object") w(v);
      }
    };
    w(params["构件"] || {});
    return n;
  }

  async function editProfile(b, field) {
    const cur = field.split(".").reduce((o, k) => (o == null ? o : o[k]), b.profile);
    const isObj = cur !== null && typeof cur === "object";
    const val = await ask({
      title: "改档案字段",
      sub: `${b.bid} · ${field}`,
      value: isObj ? JSON.stringify(cur, null, 1) : String(cur),
      hint: `影响步骤：${(b.impact[field.split(".")[0]] || ["建件"]).join(" → ")}<br>
             写完立刻备份，并按字节回读验一遍。`
    });
    if (val === null) return;
    let v = val;
    if (isObj || /^[\[{]/.test(val.trim())) {
      try { v = JSON.parse(val); } catch (e) { return toast("JSON 解析失败：" + e.message, true); }
    } else if (val === "true" || val === "false") v = val === "true";
    else if (val === "null") v = null;
    else if (val.trim() !== "" && !isNaN(Number(val))) v = Number(val);
    try {
      const r = await post("/api/profile/save", { bid: b.bid, 字段: field, 值: v });
      toast(`已保存 ${field} = ${JSON.stringify(r.new)}（备份 ${short(r.backup)}）`);
      if (/floor_names|basement|keep_layers|drop_layers|drawing|door_carve|podium_roof|roof/.test(field)) {
        toast(`这处改动要重跑：${r.impact.join(" → ")}`, true);
      }
      renderBuilding(b.bid);
    } catch (e) { toast("保存被拒：" + e.message, true); }
  }

  /* ---------------- 图纸库：每层 DXF（与房间库分开两页） ---------------- */
  async function renderDraw() {
    main.innerHTML = `<p class="empty">读图纸库…</p>`;
    try {
      paintDraw(await api("/api/library?what=draw"));
    } catch (e) {
      main.innerHTML = `<div class="note">读不到图纸库：${esc(e.message)}</div>`;
    }
  }

  function paintDraw(draw) {
    noteNames(draw);
    const da = draw["合计"] || {};
    main.innerHTML = head("图纸库 · 每层 DXF", "每层 DXF 在线看 / 下载",
      `<b>生成</b>${esc(stamp(draw["生成"]))}<br>
       <b>索引</b>rebuild/构件库/图纸库.json<br>
       <b>真源</b>各楼栋 06_su/contours/`) +
      `<div class="tally">
        <div><div class="n">${da["楼栋"] || 0}</div><div class="l">有 DXF 的栋</div></div>
        <div><div class="n">${da["层"] || 0}</div><div class="l">层 DXF</div></div>
        <div class="${da["缺文件"] ? "bad" : "ok"}"><div class="n">${da["缺文件"] || 0}</div><div class="l">缺文件</div></div>
      </div>
      <div class="bar"><span class="hint" style="margin:0">点栋展开层表；「看」在线浏览，「下载」取原文件</span></div>
      <div id="libbody">${libDrawHtml(draw)}</div>`;

    main.querySelectorAll("[data-dxf-view]").forEach(btn => {
      btn.addEventListener("click", () => {
        const [b2, f2] = btn.dataset.dxfView.split("|");
        openDxfViewer(b2, f2);
      });
    });
  }

  /* ---------------- 房间库：逐层明细 / 统计分析 ---------------- */
  const roomState = { tab: "rooms", bid: "", floor: "" };

  async function renderRooms() {
    main.innerHTML = `<p class="empty">读房间库…</p>`;
    try {
      paintRooms(await api("/api/library?what=rooms"));
    } catch (e) {
      main.innerHTML = `<div class="note">读不到房间库：${esc(e.message)}</div>`;
    }
  }

  function paintRooms(rooms) {
    noteNames(rooms);
    const ra = rooms["合计"] || {};
    const haveRooms = Object.keys(rooms["楼栋"] || {})
      .filter(b => Object.keys((rooms["楼栋"][b] || {}).层 || {}).length).sort();
    if (!haveRooms.includes(roomState.bid)) roomState.bid = haveRooms[0] || "";

    main.innerHTML = head("房间库 · 统计与分析", "每层房间统计（可改）",
      `<b>生成</b>${esc(stamp(rooms["生成"]))}<br>
       <b>合并视图</b>rebuild/构件库/房间库.json<br>
       <b>人工改动</b>构件库/房间_改动.json`) +
      `<div class="tally">
        <div><div class="n">${ra["楼栋有房间"] || 0}</div><div class="l">有房间的栋</div></div>
        <div class="${ra["楼栋空表"] ? "warn" : ""}"><div class="n">${ra["楼栋空表"] || 0}</div><div class="l">空表（量不到）</div></div>
        <div><div class="n">${ra["间数"] || 0}</div><div class="l">房间</div></div>
        <div class="${ra["人工改动"] ? "warn" : ""}"><div class="n">${ra["人工改动"] || 0}</div><div class="l">人工改动</div></div>
      </div>
      <div class="bar">
        <div class="seg" id="roomseg">
          <button data-t="rooms" class="${roomState.tab === "rooms" ? "on" : ""}">逐层明细</button>
          <button data-t="stats" class="${roomState.tab === "stats" ? "on" : ""}">统计分析</button>
        </div>
        <span class="hint" style="margin:0 0 0 auto">${roomState.tab === "rooms"
          ? "改完立刻重建合并视图，算得值不动" : "全部由房间库现算，不另存一份统计"}</span>
      </div>
      <div id="libbody">${roomState.tab === "rooms" ? libRoomsHtml(rooms, haveRooms) : libStatsHtml(rooms)}</div>`;

    document.getElementById("roomseg").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-t]"); if (!b) return;
      roomState.tab = b.dataset.t; paintRooms(rooms);
    });
    if (roomState.tab === "rooms") wireRoomPickers(rooms, haveRooms);
  }

  function libDrawHtml(draw) {
    const bids = Object.keys(draw["楼栋"] || {}).sort();
    const rows = bids.map(bid => {
      const b = draw["楼栋"][bid] || {};
      const fl = b["层"] || [];
      const ok = fl.filter(f => f["文件"]);
      return `<details class="libb">
        <summary><b>${esc(bname(bid))}</b>
          <span class="hint">${fl.length} 层 · ${ok.length} 份 DXF · ${bytes(b["字节合计"] || 0)}</span></summary>
        ${fl.length ? `<table class="kv">
          <tr><th>层</th><th>标高 m</th><th>层高 m</th><th>面数</th><th>大小</th><th>sha256</th><th></th></tr>
          ${fl.map(f => f["文件"] ? `<tr>
            <td class="v">${esc(f["层"])}</td>
            <td class="v">${f.z0_m == null ? "—" : (+f.z0_m).toFixed(2)}</td>
            <td class="v">${f.h_m == null ? "—" : (+f.h_m).toFixed(2)}</td>
            <td class="v">${f.polys == null ? "—" : f.polys}</td>
            <td class="v">${bytes(f["字节"])}</td>
            <td class="v">${esc(String(f.sha256 || "").slice(0, 12))}…</td>
            <td class="act"><button class="btn ghost" data-dxf-view="${esc(bid)}|${esc(f["层"])}">看</button>
              <a class="btn ghost" href="/api/dxf?bid=${encodeURIComponent(bid)}&floor=${encodeURIComponent(f["层"])}">下载</a></td>
          </tr>` : `<tr><td class="v">${esc(f["层"])}</td>
            <td class="v" colspan="6" style="color:var(--error-text)">缺文件</td></tr>`).join("")}
        </table>` : `<div class="note warn">${esc(b["状态"] || "没有层")}</div>`}
      </details>`;
    }).join("");
    return `<p class="hint">文件真源在各自楼栋 <code>06_su/contours/</code>；本库只记路径 / 字节 / sha256，
      不复制第二份。要集中副本：<code>python -I rebuild/tools/build_libraries.py --导出 &lt;dir&gt;</code>。</p>${rows}`;
  }

  function libRoomsHtml(rooms, haveRooms) {
    if (!haveRooms.length) {
      return `<div class="note warn">还没有任何一栋有房间表。先跑
        <code>CDUT_BUILDING=&lt;bid&gt; python -I rebuild/tools/build_rooms.py</code>，再跑
        <code>build_libraries.py --房间</code>。</div>`;
    }
    const b = (rooms["楼栋"] || {})[roomState.bid] || {};
    const floors = Object.keys(b["层"] || {});
    if (!floors.includes(roomState.floor)) roomState.floor = floors[0] || "";
    const fl = (b["层"] || {})[roomState.floor] || {};
    const rows = (fl["房间"] || []);
    return `<div class="bar">
        <label class="hint" style="margin:0">楼栋
          <select id="libbid">${haveRooms.map(x => `<option value="${esc(x)}" ${x === roomState.bid ? "selected" : ""}>${esc(bname(x))}</option>`).join("")}</select></label>
        <label class="hint" style="margin:0">层
          <select id="libfloor">${floors.map(x => `<option ${x === roomState.floor ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
        <span class="hint" style="margin:0 0 0 auto">${b["状态"] ? esc(b["状态"]) : `环数 ${fl["环数"] ?? "—"} · 底面积 ${fl["底面积_m2"] ?? "—"} m²`}
          ${b["墙厚_mm"] ? ` · 墙厚 ${b["墙厚_mm"]} mm（${esc(b["墙厚_来源"] || "")}）` : ""}</span>
      </div>
      ${rows.length ? `<div class="matrix-wrap"><table class="matrix">
        <thead><tr><th>房间号</th><th>用途</th><th>单位</th><th>图上面积 m²</th><th>算得面积 m²</th><th>差 m²</th><th>情形</th><th>标注</th><th></th></tr></thead>
        <tbody>${rows.map(r => `<tr>
          <td class="bidcell"><span class="b">${esc(r["房间号"] || "—")}</span></td>
          <td>${esc(r["用途"] || "—")}</td>
          <td>${esc(r["单位"] || "—")}</td>
          <td class="num">${r["图上面积_m2"] ?? "—"}</td>
          <td class="num">${r["算得面积_m2"] ?? "—"}</td>
          <td class="num">${r["差_m2"] ?? "—"}</td>
          <td>${esc(r["情形"] || "")}</td>
          <td>${r["标注"] === "改动" ? `<span class="tag jiashe">改动</span>` : ""}</td>
          <td class="act">${["用途", "单位", "图上面积_m2"].map(f =>
            `<button class="btn ghost" data-room-edit="${esc(roomState.bid)}|${esc(roomState.floor)}|${esc(r["房间号"])}|${f}">${f === "图上面积_m2" ? "面积" : f}</button>`).join("")}</td>
        </tr>`).join("")}</tbody>
      </table></div>
      <p class="hint">合计 ${fl["合计"] ? `${fl["合计"]["间数"]} 间 · 算得 ${fl["合计"]["算得面积_m2"]} m² · 图上 ${fl["合计"]["图上面积_m2"]} m²` : "—"}。
      改动写在 <code>构件库/房间_改动.json</code>，重建房间库时保留；源件房间表不动。</p>`
      : `<div class="note warn">这一层没有房间行（房间表里 0 间）。</div>`}`;
  }

  /* ---------------- 房间统计分析（全部现算，不另存统计表） ---------------- */
  function libStatsHtml(rooms) {
    const bids = Object.keys(rooms["楼栋"] || {}).sort();
    const perB = [], byUse = new Map(), byUnit = new Map(), top = [];
    const BUCKETS = [[0, 10], [10, 20], [20, 40], [40, 80], [80, 160], [160, Infinity]];
    const buckets = BUCKETS.map(() => 0);
    const empty = [], none = [];
    let nAll = 0, saAll = 0, paAll = 0;
    const bump = (m, k, a) => {
      const x = m.get(k) || { n: 0, a: 0 }; x.n++; x.a += a; m.set(k, x);
    };
    for (const bid of bids) {
      const b = rooms["楼栋"][bid] || {};
      const floors = b["层"] || {};
      let n = 0, sa = 0, pa = 0, mx = 0;
      for (const [fname, f] of Object.entries(floors)) {
        for (const r of f["房间"] || []) {
          const a = +r["算得面积_m2"] || 0;
          n++; sa += a; pa += +r["图上面积_m2"] || 0;
          if (a > mx) mx = a;
          bump(byUse, r["用途"] || "（未填）", a);
          bump(byUnit, r["单位"] || "（未填）", a);
          for (let i = 0; i < BUCKETS.length; i++) {
            if (a >= BUCKETS[i][0] && a < BUCKETS[i][1]) { buckets[i]++; break; }
          }
          top.push({ bid, 层: fname, 房间号: r["房间号"], a });
        }
      }
      nAll += n; saAll += sa; paAll += pa;
      if (!Object.keys(floors).length) { none.push(bid); continue; }
      if (!n) { empty.push(bid); continue; }
      perB.push({ bid, 层数: Object.keys(floors).length, n, sa, pa, mx,
                  墙厚: b["墙厚_mm"], 来源: b["墙厚_来源"] });
    }
    perB.sort((x, y) => y.n - x.n);
    top.sort((x, y) => y.a - x.a);

    const fmt = (v, d = 1) => (v == null || !isFinite(v)) ? "—" : (+v).toFixed(d);
    const avg = nAll ? saAll / nAll : 0;
    const grp = (m) => [...m.entries()].sort((x, y) => y[1].n - x[1].n);
    const useList = grp(byUse), unitList = grp(byUnit);
    const maxBucket = Math.max(1, ...buckets);
    const bar = (v, max) => `<div class="sbar"><i style="width:${Math.max(1, Math.round(v / max * 100))}%"></i></div>`;

    // 用途 255 种 / 单位 126 种 ⇒ 全列出来一页两万像素，没法看。只列前 12 名，余下并成「其他」。
    const trim = (list, k = 12) => {
      const top = list.slice(0, k);
      const rest = list.slice(k);
      if (rest.length) {
        top.push([`其他（${rest.length} 种）`,
                  { n: rest.reduce((s, x) => s + x[1].n, 0),
                    a: rest.reduce((s, x) => s + x[1].a, 0) }]);
      }
      return top;
    };

    const groupTable = (title, list) => {
      const rows = trim(list);
      const max = Math.max(1, ...rows.map(x => x[1].n));
      return `<h3>${title} <span class="hint">共 ${list.length} 种，列前 12 名</span></h3>
      <div class="matrix-wrap"><table class="matrix">
        <thead><tr><th>${title.includes("用途") ? "用途" : "单位"}</th><th>间数</th><th>算得面积 m²</th><th>占全库面积</th><th>占比分布</th></tr></thead>
        <tbody>${rows.map(([k, v]) => `<tr>
          <td><b>${esc(k)}</b></td><td class="num">${v.n}</td><td class="num">${fmt(v.a)}</td>
          <td class="num">${saAll ? (v.a / saAll * 100).toFixed(1) : "0.0"}%</td>
          <td>${bar(v.n, max)}</td></tr>`).join("")}</tbody></table></div>`;
    };

    return `<div class="tally">
        <div><div class="n">${nAll}</div><div class="l">房间（有统计的栋）</div></div>
        <div><div class="n">${fmt(saAll, 0)}</div><div class="l">算得面积合计 m²</div></div>
        <div><div class="n">${fmt(paAll, 0)}</div><div class="l">图上面积合计 m²</div></div>
        <div><div class="n">${fmt(saAll - paAll, 0)}</div><div class="l">差（算得−图上）m²</div></div>
        <div><div class="n">${fmt(avg)}</div><div class="l">平均每间 m²</div></div>
        <div><div class="n">${perB.length}</div><div class="l">有房间的栋</div></div>
      </div>

      <h3>每栋汇总 <span class="hint">按间数降序；面积一律用「算得面积」，图上面积并列</span></h3>
      <div class="matrix-wrap"><table class="matrix">
        <thead><tr><th>楼栋</th><th>层</th><th>间数</th><th>算得 m²</th><th>图上 m²</th><th>平均 m²</th><th>最大 m²</th><th>墙厚 mm</th><th>墙厚来源</th></tr></thead>
        <tbody>${perB.map(x => `<tr>
          <td class="bidcell"><span class="b">${esc(bname(x.bid))}</span></td>
          <td class="num">${x.层数}</td><td class="num">${x.n}</td>
          <td class="num">${fmt(x.sa)}</td><td class="num">${fmt(x.pa)}</td>
          <td class="num">${fmt(x.sa / x.n)}</td><td class="num">${fmt(x.mx)}</td>
          <td class="num">${x.墙厚 ?? "—"}</td><td>${esc(x.来源 || "—")}</td></tr>`).join("")}</tbody>
        <tfoot><tr><th>合计</th><th>—</th><th>${nAll}</th><th>${fmt(saAll)}</th><th>${fmt(paAll)}</th>
          <th>${fmt(avg)}</th><th>—</th><th></th><th></th></tr></tfoot></table></div>

      ${groupTable("按用途", useList)}
      ${groupTable("按单位", unitList)}

      <h3>单间面积分布</h3>
      <div class="matrix-wrap"><table class="matrix">
        <thead><tr><th>面积区间 m²</th><th>间数</th><th>占比</th><th>分布</th></tr></thead>
        <tbody>${BUCKETS.map((b, i) => `<tr>
          <td>${b[1] === Infinity ? `≥ ${b[0]}` : `${b[0]} – ${b[1]}`}</td>
          <td class="num">${buckets[i]}</td>
          <td class="num">${nAll ? (buckets[i] / nAll * 100).toFixed(1) : "0.0"}%</td>
          <td>${bar(buckets[i], maxBucket)}</td></tr>`).join("")}</tbody></table></div>

      <h3>面积最大的 10 间</h3>
      <div class="matrix-wrap"><table class="matrix">
        <thead><tr><th>楼栋</th><th>层</th><th>房间号</th><th>算得面积 m²</th></tr></thead>
        <tbody>${top.slice(0, 10).map(x => `<tr>
          <td class="bidcell"><span class="b">${esc(bname(x.bid))}</span></td><td>${esc(x.层)}</td>
          <td>${esc(x.房间号 || "—")}</td><td class="num">${fmt(x.a)}</td></tr>`).join("")}</tbody></table></div>

      ${empty.length ? `<div class="note warn"><b>表在、0 间（统计不到）</b>：${empty.map(esc).join(" ")}
        <br>原因：墙厚配对没成（缝环没走到）或面积文字缺失 —— 不是「这栋没有房间」。</div>` : ""}
      ${none.length ? `<div class="note warn"><b>无房间表</b>：${none.map(esc).join(" ")}</div>` : ""}
      <p class="hint">全部数字由 <code>构件库/房间库.json</code> 现算；人工改动已并入（标注「改动」的行按改后值算）。</p>`;
  }

  function wireRoomPickers(rooms, haveRooms) {
    const bid = document.getElementById("libbid");
    const fl = document.getElementById("libfloor");
    bid?.addEventListener("change", () => { roomState.bid = bid.value; roomState.floor = ""; paintRooms(rooms); });
    fl?.addEventListener("change", () => { roomState.floor = fl.value; paintRooms(rooms); });
    main.querySelectorAll("[data-room-edit]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const [b2, f2, no, field] = btn.dataset.roomEdit.split("|");
        const cur = rooms["楼栋"][b2]["层"][f2]["房间"].find(r => String(r["房间号"]) === no) || {};
        const v = await ask({
          title: "改房间字段",
          sub: `${b2} · ${f2} · ${no} · ${field}`,
          value: cur[field] ?? "",
          hint: "改的是<b>人工覆盖值</b>；算得面积不动。系统会把改动与原值并排记在 房间_改动.json。"
        });
        if (v == null) return;
        let val = v;
        if (field === "图上面积_m2") {
          val = Number(v);
          if (!isFinite(val)) return toast("面积必须是数", true);
        }
        try {
          const r = await post("/api/room/save", { bid: b2, 层: f2, 房间号: no, 字段: { [field]: val } });
          toast(`已保存（改动 ${r["改动条数"]} 条，备份 ${r.backup || "无"}）`);
          renderRooms();
        } catch (e) { toast("保存被拒：" + e.message, true); }
      });
    });
  }

  /* ---------------- 在线看 DXF（生成件 + 原始件叠加比对） ---------------- */
  async function openDxfViewer(bid, floor) {
    document.getElementById("dxfview")?.remove();
    const ov = document.createElement("div");
    ov.id = "dxfview"; ov.className = "dxfview";
    ov.innerHTML = `<div class="dxfpanel">
      <div class="dxfhead"><b>${esc(bname(bid))} · ${esc(floor)}</b>
        <span class="dxfseg" id="dxfmode">
          <button data-mode="both" class="on">叠加比对</button>
          <button data-mode="gen">只看生成</button>
          <button data-mode="raw">只看原始</button>
        </span>
        <span class="dxfstat" id="dxfstat">读几何…</span>
        <span class="dxfsp"></span>
        <span class="hint" style="margin:0">滚轮缩放 · 拖动平移 · 双击整体 · 单击取点</span>
        <button class="btn ghost" id="dxffit">整体</button>
        <button class="btn ghost" id="dxfclose">关闭</button></div>
      <div class="dxfbody">
        <div class="dxflayers" id="dxflayers"></div>
        <canvas id="dxfcanvas"></canvas>
        <div class="dxfpickbar" id="dxfpickbar" style="display:none">
          <span id="dxfpick"></span><button class="btn ghost" id="dxfcopy">复制坐标</button></div>
      </div></div>`;
    document.body.appendChild(ov);

    const cv = ov.querySelector("#dxfcanvas");
    const ctx = cv.getContext("2d");
    const statEl = ov.querySelector("#dxfstat");
    const layerEl = ov.querySelector("#dxflayers");
    const st = { geoms: {}, on: new Set(), paths: new Map(), k: 1, tx: 0, ty: 0,
                 cx: 0, cy: 0, W: 1, H: 1, dpr: 1, drag: null, fitK: 1,
                 mode: "both", rawErr: "", cmp: null,
                 pick: null, downAt: null };      // pick=取点标记；downAt=判「拖动还是单击」
    const RAW_COLOR = "#9aa0a6";             // 原始图统一灰：让生成件的颜色一眼能挑出来

    const close = () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", resize);
      ov.remove();
    };
    function onKey(e) { if (e.key === "Escape") close(); }
    window.addEventListener("keydown", onKey);

    function resize() {
      const r = cv.getBoundingClientRect();
      st.dpr = window.devicePixelRatio || 1;
      st.W = Math.max(1, Math.round(r.width));
      st.H = Math.max(1, Math.round(r.height));
      cv.width = Math.round(st.W * st.dpr);
      cv.height = Math.round(st.H * st.dpr);
      draw();
    }
    window.addEventListener("resize", resize);

    function setWorld() {
      const d = st.dpr, k = st.k;
      // 世界 → 屏幕：sx=(x−cx)k+W/2+tx，sy=H/2−(y−cy)k+ty（CAD 的 y 朝上，canvas 朝下）
      ctx.setTransform(d * k, 0, 0, -d * k,
                       d * (st.W / 2 + st.tx - st.cx * k),
                       d * (st.H / 2 + st.ty + st.cy * k));
    }

    function draw() {
      if (!st.W) return;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, cv.width, cv.height);
      if (!st.k) return;
      setWorld();
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      // 原始在下（灰、细），生成在上（彩色、略粗）：叠在一起时偏离处才看得清
      for (const [kind, width, fixed] of [["raw", 0.9, RAW_COLOR], ["gen", 1.2, null]]) {
        if (st.mode !== "both" && st.mode !== kind) continue;
        const g = st.geoms[kind]; if (!g) continue;
        ctx.lineWidth = width / st.k;         // ≈ 固定 CSS 像素，缩放后线宽不跟着变
        for (const L of g["层"] || []) {
          if (!st.on.has(kind + "|" + L["名"])) continue;
          const p = st.paths.get(kind + "|" + L["名"]); if (!p) continue;
          ctx.strokeStyle = fixed || L["色"] || "#666";
          ctx.stroke(p);
        }
      }
      // 判据 J-10.8-04 点出来的「未贴边」：生成件上有、原始图 300 mm 内没有的边
      if (st.cmp && st.cmp.ok && st.mode !== "raw" && (st.cmp["未贴边"] || []).length) {
        ctx.strokeStyle = "#e53935";
        ctx.lineWidth = 2.2 / st.k;
        const p = new Path2D();
        for (const e of st.cmp["未贴边"]) {
          p.moveTo(e[0], e[1]); p.lineTo(e[2], e[3]);
        }
        ctx.stroke(p);
      }
      // ★ 2026-10-19 用户「你能不能让我能在dxf点到」：单击落一个十字标记，报**世界坐标 mm**
      //   与最近图元所在层。标记半径按屏幕像素折回世界单位 ⇒ 放大缩小时看起来一样大。
      //   坐标原样用 canvas 的世界系（与 `/api/dxf/geom` 同一框架），不做任何换算、不猜单位。
      if (st.pick) {
        const r0 = 7 / st.k;
        ctx.strokeStyle = "#1e88e5"; ctx.lineWidth = 1.6 / st.k;
        ctx.beginPath();
        ctx.moveTo(st.pick.x - r0, st.pick.y); ctx.lineTo(st.pick.x + r0, st.pick.y);
        ctx.moveTo(st.pick.x, st.pick.y - r0); ctx.lineTo(st.pick.x, st.pick.y + r0);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(st.pick.x, st.pick.y, r0 * 1.9, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    function cmpBadge(c) {
      if (!c) return "";
      if (!c.ok) return `<span class="badge bad" title="${esc(c.why || "")}">比对没量到</span>`;
      const tie = c["贴源率"], cov = c["覆盖"];
      const cls = (v, min) => v == null ? "" : (v >= min ? "ok" : "bad");
      return `<span class="badge ${cls(tie, .95)}">贴源 ${fmtPct(tie)}</span>`
        + `<span class="badge ${cls(cov, .85)}">覆盖 ${fmtPct(cov)}</span>`
        + (c["未贴边_总"] ? `<span class="badge bad">红边 ${c["未贴边_总"]} 处</span>` : "");
    }
    const fmtPct = (v) => v == null ? "—" : (v * 100).toFixed(1) + "%";

    function fit() {
      // ★ 不用原始 bbox：图里常混着极远的零星块/标记（实测 c001 的 D1 散布在 74 km 见方里），
      //   按全量 bbox 取景会把真正的平面缩成一小团。按点数取 2%–98% 分位，稀疏的远点不进画框；
      //   远点仍然画（缩小时看得见），只是不作为「整体」的参照。
      const g = st.geoms.gen || st.geoms.raw;
      const bb = (st.robust && st.robust[0] != null) ? st.robust : (g && g.bbox);
      if (!bb || bb[0] == null) return;
      const w = Math.max(1e-6, bb[2] - bb[0]), h = Math.max(1e-6, bb[3] - bb[1]);
      st.cx = (bb[0] + bb[2]) / 2; st.cy = (bb[1] + bb[3]) / 2;
      st.k = Math.min((st.W - 48) / w, (st.H - 48) / h);
      st.fitK = st.k; st.tx = 0; st.ty = 0;
      draw();
    }

    ov.querySelector("#dxfclose").addEventListener("click", close);
    ov.querySelector("#dxffit").addEventListener("click", fit);
    ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
    ov.querySelector("#dxfmode").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-mode]"); if (!b) return;
      st.mode = b.dataset.mode;
      ov.querySelectorAll("#dxfmode button").forEach(x => x.classList.toggle("on", x === b));
      draw();
    });

    cv.addEventListener("wheel", (e) => {
      if (!st.geoms.gen && !st.geoms.raw) return;
      e.preventDefault();
      const r = cv.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const wx = (mx - st.W / 2 - st.tx) / st.k + st.cx;
      const wy = st.cy - (my - st.H / 2 - st.ty) / st.k;
      const k2 = Math.min(st.fitK * 500, Math.max(st.fitK / 500, st.k * Math.exp(-e.deltaY * 0.0015)));
      st.k = k2;
      st.tx = mx - st.W / 2 - (wx - st.cx) * k2;
      st.ty = my - st.H / 2 + (wy - st.cy) * k2;
      draw();
    }, { passive: false });

    cv.addEventListener("mousedown", (e) => {
      st.drag = { x: e.clientX, y: e.clientY, tx: st.tx, ty: st.ty };
      st.downAt = { x: e.clientX, y: e.clientY };   // 供 click 判「这次是拖还是点」
      cv.classList.add("grab");
    });
    window.addEventListener("mouseup", () => { st.drag = null; cv.classList.remove("grab"); });
    cv.addEventListener("mousemove", (e) => {
      if (!st.drag) return;
      st.tx = st.drag.tx + (e.clientX - st.drag.x);
      st.ty = st.drag.ty + (e.clientY - st.drag.y);
      draw();
    });

    /* ---------------- 单击取点（2026-10-19 用户「你能不能让我能在dxf点到」） ----------------
       ★ 判据（铁律 158）：量具只量**屏幕上真画出来的**线——层没勾/模式不是 it 的线一律不算命中，
         否则会报一个「图上看不见的层名」，用户拿它来指位置就会指错。
       ★ 吸附：12 CSS px 内有线就吸到线上最近点（指缺陷通常要贴线），没有就落原始点、并明说「附近没线」。 */
    function toWorld(mx, my) {
      return { x: (mx - st.W / 2 - st.tx) / st.k + st.cx,
               y: st.cy - (my - st.H / 2 - st.ty) / st.k };
    }
    function segNear(px, py, x1, y1, x2, y2) {
      const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy;
      let t = L > 0 ? ((px - x1) * dx + (py - y1) * dy) / L : 0;
      t = Math.max(0, Math.min(1, t));
      const qx = x1 + t * dx, qy = y1 + t * dy;
      return { d: Math.hypot(px - qx, py - qy), x: qx, y: qy };
    }
    function nearestOnScreen(wx, wy, tolPx) {
      let best = null;
      const tol = tolPx / st.k;
      for (const kind of ["gen", "raw"]) {
        if (st.mode !== "both" && st.mode !== kind) continue;
        const g = st.geoms[kind]; if (!g) continue;
        for (const ln of g["线"] || []) {
          if (!st.on.has(kind + "|" + ln[0])) continue;
          for (let i = 1; i + 3 < ln.length; i += 2) {
            const h = segNear(wx, wy, ln[i], ln[i + 1], ln[i + 2], ln[i + 3]);
            if (!best || h.d < best.d) best = { d: h.d, x: h.x, y: h.y, kind, layer: ln[0] };
          }
        }
      }
      return best && best.d <= tol ? best : null;
    }
    const pickEl = ov.querySelector("#dxfpick");
    const pickBar = ov.querySelector("#dxfpickbar");
    const copyBtn = ov.querySelector("#dxfcopy");
    cv.addEventListener("click", (e) => {
      if (!st.k) return;
      const d0 = st.downAt;
      if (d0 && Math.hypot(e.clientX - d0.x, e.clientY - d0.y) > 3) return;   // 拖动，不是取点
      const r = cv.getBoundingClientRect();
      const w = toWorld(e.clientX - r.left, e.clientY - r.top);
      const hit = nearestOnScreen(w.x, w.y, 12);
      const X = Math.round(hit ? hit.x : w.x), Y = Math.round(hit ? hit.y : w.y);
      st.pick = { x: X, y: Y };
      const who = hit ? `${hit.kind === "gen" ? "生成件" : "原始图"} · ${hit.layer} · 距 ${Math.round(hit.d)} mm`
                      : "附近 12 px 内没有线";
      pickEl.textContent = `X=${X} Y=${Y} mm · ${who}`;
      pickBar.style.display = "flex";
      draw();
    });
    copyBtn.addEventListener("click", async () => {
      if (!st.pick) return;
      const t = `X=${st.pick.x} Y=${st.pick.y}`;
      try { await navigator.clipboard.writeText(t); toast("已复制：" + t); }
      catch (e) { toast("复制被浏览器拒：" + e.message + " —— 坐标是 " + t, true); }
    });

    cv.addEventListener("dblclick", () => { st.pick = null; pickBar.style.display = "none"; fit(); });

    const geomUrl = (kind) => `/api/dxf/geom?bid=${encodeURIComponent(bid)}`
      + `&floor=${encodeURIComponent(floor)}&kind=${kind}`;

    function buildPaths(g, kind) {
      for (const L of g["层"] || []) {
        const key = kind + "|" + L["名"];
        st.on.add(key);
        const p = new Path2D();
        for (const ln of g["线"] || []) {
          if (ln[0] !== L["名"]) continue;
          for (let i = 1; i + 1 < ln.length; i += 2) {
            if (i === 1) p.moveTo(ln[1], ln[2]);
            else p.lineTo(ln[i], ln[i + 1]);
          }
        }
        st.paths.set(key, p);
      }
    }

    // ★ 2026-10-19 用户令「你改成中文和英文显示，我看不懂英文」：
    //   生成件那一栏的层名原本是轮廓数据里的**类键**（WALL / DOOR / …）。这些键是数据契约
    //   （`06_su/contours/*.json` 的 `layer` 字段、SU 的硬编码类名表都按它取值）⇒ **不许改数据**，
    //   只在**显示**时映射成「中文 ENGLISH」。表里没有的键**原样显示**：不猜、不吞（铁律 199）。
    const CLASS_ZH = {
      WALL: "墙体", COL: "柱", DOOR: "门", LINTEL: "门头墙", STAIR: "楼梯",
      SLAB: "楼板", LIFT: "竖井", ROOF: "屋面", PARAPET: "女儿墙",
      ROOF_ROOM: "屋面楼梯间", ROOF_STAIR: "屋面楼梯间", ROOF_STEP: "屋面台阶",
    };
    const clsLabel = (name) => {
      const zh = CLASS_ZH[String(name).toUpperCase()];
      return zh ? zh + " " + name : name;
    };

    function layerGroup(kind, title, g, fixed) {
      if (!g) {
        return `<div class="dxfgrp"><div class="dxfgrph">${title}
          <span class="dxfmiss">${esc(kind === "raw" ? (st.rawErr || "读不到原始图") : "读不到生成件")}</span></div></div>`;
      }
      // data-layer 仍写**原始类键**（勾选/过滤都按它认），只有给人看的 `.nm` 换成中英双语
      const list = (g["层"] || []).map(L => `<label class="dxflayer">
        <input type="checkbox" checked data-kind="${kind}" data-layer="${esc(L["名"])}">
        <i style="background:${esc(fixed || L["色"] || "#666")}"></i>
        <span class="nm">${esc(kind === "gen" ? clsLabel(L["名"]) : L["名"])}</span><span class="ct">${L["条"]}</span></label>`).join("");
      return `<div class="dxfgrp"><div class="dxfgrph">${title}
        <span class="ct">${(g["层"] || []).length} 层 · ${g["点数"] || 0} 点</span></div>
        ${list || `<div class="note warn">没有可画的线（只有文字/块，或图元类型不在支持范围）。</div>`}</div>`;
    }

    try {
      const cmpUrl = `/api/dxf/compare?bid=${encodeURIComponent(bid)}`
        + `&floor=${encodeURIComponent(floor)}`;
      const [gen, raw, cmp] = await Promise.all([
        api(geomUrl("gen")),
        api(geomUrl("raw")).catch((e) => { st.rawErr = e.message; return null; }),
        api(cmpUrl).catch(() => null),           // 比对读不到不挡看图，但状态栏会如实说
      ]);
      st.cmp = cmp;
      st.geoms.gen = gen;
      st.geoms.raw = raw;
      buildPaths(gen, "gen");
      if (raw) buildPaths(raw, "raw");

      // 取景按生成件算（原始件同坐标系，叠加不会错位）；生成件没线时退回原始件
      const base = (gen["线"] || []).length ? gen : raw;
      if (base) {
        const xs = [], ys = [];
        for (const ln of base["线"] || []) {
          for (let i = 1; i + 1 < ln.length; i += 2) { xs.push(ln[i]); ys.push(ln[i + 1]); }
        }
        const q = (a, p) => {
          if (!a.length) return null;
          a.sort((x, y) => x - y);
          return a[Math.min(a.length - 1, Math.max(0, Math.floor(a.length * p)))];
        };
        st.robust = xs.length ? [q(xs, 0.02), q(ys, 0.02), q(xs, 0.98), q(ys, 0.98)] : base.bbox;
      }

      layerEl.innerHTML = layerGroup("raw", "原始图 · 01_cad/raw", raw, RAW_COLOR)
        + layerGroup("gen", "生成件 · 06_su/contours", gen, null);
      layerEl.addEventListener("change", (e) => {
        const cb = e.target.closest("input[data-layer]"); if (!cb) return;
        const key = cb.dataset.kind + "|" + cb.dataset.layer;
        if (cb.checked) st.on.add(key); else st.on.delete(key);
        draw();
      });

      const part = (t, g) => g
        ? `${t} ${(g["线"] || []).length} 线 / ${g["点数"] || 0} 点${g["截断"] ? "（截断）" : ""}`
        : `${t} 无`;
      statEl.innerHTML = part("生成", gen) + " · " + part("原始", raw) + " · " + cmpBadge(cmp);
      requestAnimationFrame(() => { resize(); fit(); });
    } catch (e) {
      statEl.innerHTML = `<span class="badge bad">读不到几何：${esc(e.message)}</span>`;
    }
  }

  /* ---------------- 参数 ---------------- */
  async function renderParams() {
    main.innerHTML = `<p class="empty">读参数真源…</p>`;
    try {
      const p = await api("/api/params");
      paintParams(p);
    } catch (e) {
      main.innerHTML = `<div class="note">读不到参数：${esc(e.message)}</div>`;
    }
  }

  function leafRow(bld, name, leaf) {
    const tagCls = leaf["标注"] === "实测" ? "shice" : leaf["标注"] === "假设" ? "jiashe" : "guifan";
    return `<div class="param">
      <div class="pn">${esc(name)}</div>
      <div class="pv">${esc(leaf["值"])}<span class="pu"> ${esc(leaf["单位"] || "")}</span></div>
      <div><span class="tag ${tagCls}">${esc(leaf["标注"] || "未标")}</span></div>
      <div class="pr">${leaf["区间"] ? esc(JSON.stringify(leaf["区间"])) : "—"}</div>
      <div class="pmeta">${esc(leaf["作用"] || "")}<em>出处：${esc(leaf["出处"] || "未写")}</em></div>
      <div class="pa">
        <button class="btn ghost" data-pe="${esc(bld)}|${esc(name)}|值">改值</button>
        <button class="btn ghost" data-pe="${esc(bld)}|${esc(name)}|标注">标注</button>
        <button class="btn ghost" data-pe="${esc(bld)}|${esc(name)}|出处">出处</button>
      </div></div>`;
  }

  function paintParams(p) {
    const groups = p["构件"] || {};
    const all = [];
    for (const g of Object.keys(groups))
      for (const n of Object.keys(groups[g] || {}))
        if (groups[g][n] && typeof groups[g][n] === "object" && "值" in groups[g][n])
          all.push([g, n, groups[g][n]]);
    const nShi = all.filter(x => x[2]["标注"] === "实测").length;
    const nJia = all.filter(x => x[2]["标注"] === "假设").length;
    const nQue = all.filter(x => !x[2]["出处"]).length;

    main.innerHTML = head("参数 · 依据", "每个数都带着<span class='thin'>出处与作用</span>",
      `<b>真源</b>rebuild/构件库/参数.json<br><b>更新</b>${esc(p["更新"] || "—")}<br>
       <b>参数</b>${all.length} 个`) +
      `<div class="tally">
        <div><div class="n">${all.length}</div><div class="l">参数</div></div>
        <div class="ok"><div class="n">${nShi}</div><div class="l">实测</div></div>
        <div class="warn"><div class="n">${nJia}</div><div class="l">假设</div></div>
        <div class="bad"><div class="n">${nQue}</div><div class="l">没写出处</div></div>
      </div>
      <div class="note warn">参数是<b>全校共用</b>的：任一值改动后，所有楼栋都要按影响面重跑。</div>
      <div class="ptree">${Object.keys(groups).map(g => `
        <div class="pgroup"><h2>${esc(g)}</h2>
        ${Object.keys(groups[g]).filter(n => groups[g][n] && typeof groups[g][n] === "object" && "值" in groups[g][n])
          .map(n => leafRow(g, n, groups[g][n])).join("")}
        </div>`).join("")}</div>`;

    main.querySelectorAll("[data-pe]").forEach(btn => {
      btn.addEventListener("click", () => {
        const parts = btn.dataset.pe.split("|");
        editParam(parts[0], parts[1], parts[2], groups[parts[0]][parts[1]]);
      });
    });
  }

  async function editParam(bld, name, field, leaf) {
    const cur = leaf[field];
    const val = await ask({
      title: `改参数 · ${field}`,
      sub: `${bld} / ${name}（当前 ${JSON.stringify(cur)}）`,
      value: field === "区间" ? JSON.stringify(cur) : String(cur == null ? "" : cur),
      hint: `区间：${esc(JSON.stringify(leaf["区间"] || []))}　标注：${esc(leaf["标注"] || "")}<br>
             ${esc(leaf["出处"] || "")}`
    });
    if (val === null) return;
    let v = val;
    if (field === "区间") {
      try { v = JSON.parse(val); } catch (e) { return toast("区间要写成 [下界, 上界]", true); }
    } else if (field === "值") {
      if (val.trim() !== "" && !isNaN(Number(val)) && /^-?\d/.test(val.trim())) v = Number(val);
    }
    try {
      const r = await post("/api/params/save", { 构件: bld, 参数: name, 字段: field, 值: v });
      toast(`已保存 ${bld}/${name}/${field} = ${JSON.stringify(r.new)}（备份 ${short(r.backup)}）`);
      (r.warnings || []).forEach(w => toast("提示：" + w, true));
      renderParams();
    } catch (e) { toast("保存被拒：" + e.message, true); }
  }

  /* ---------------- 执行 ---------------- */
  async function renderRun() {
    const q = (location.hash.split("?")[1] || "");
    const bid = new URLSearchParams(q).get("bid") || "";
    if (!state.ov) {
      try { state.ov = await api("/api/overview"); } catch (e) { /* 表单仍可用 */ }
    }
    noteNames(state.ov);
    const bids = state.ov ? state.ov.bids.map(r => r.bid) : [];
    const steps = ["切图幅", "导出图幅", "识别", "建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包", "层号对账"];
    main.innerHTML = head("执行 · 重跑", "改到哪里，<span class='thin'>就从哪一步跑</span>",
      `<b>单栋</b>run_chain_bid.py &lt;bid&gt; --from &lt;步骤&gt;<br>
       <b>批量</b>run_batch.py --from 建件 &lt;bids…&gt;<br><b>说明</b>后台跑，日志在这里看`) +
      `<div class="bar">
        <input id="rb" list="bl" value="${esc(bid)}" placeholder="楼栋 id"
          style="min-width:140px;padding:8px;border:1px solid var(--rule-strong);background:#fff9;font-family:var(--mono)">
        <datalist id="bl">${bids.map(b => `<option value="${esc(b)}" label="${esc(bname(b))}">`).join("")}</datalist>
        <select id="rs" class="btn">${steps.map(s => `<option>${s}</option>`).join("")}</select>
        <button class="btn primary" id="go">开跑</button>
        <span class="hint" style="margin:0">一次最多 2 栋；同一栋不许并发。</span>
      </div>
      <div id="jobbox"></div>
      <section class="block" style="margin-top:30px"><h2>最近的任务</h2><div id="jobs" class="hint">…</div></section>`;

    document.getElementById("go").addEventListener("click", async () => {
      const b = document.getElementById("rb").value.trim();
      const from = document.getElementById("rs").value;
      if (!b) return toast("先填楼栋 id", true);
      try {
        const r = await post("/api/run", { bid: b, from });
        toast("已起：" + r.job);
        state.job = r.job;
        pollJob(r.job);
      } catch (e) { toast("起不来：" + e.message, true); }
    });
    const saved = localStorage.getItem("cdut3d.jobs");
    const ids = saved ? JSON.parse(saved) : [];
    document.getElementById("jobs").innerHTML = ids.length
      ? ids.slice(-8).reverse().map(id => `<a href="#" data-jid="${esc(id)}" style="display:block;font-family:var(--mono);padding:4px 0">${esc(id)}</a>`).join("")
      : "还没有从本页起过任务。";
    document.querySelectorAll("[data-jid]").forEach(a => a.addEventListener("click", (e) => {
      e.preventDefault(); pollJob(a.dataset.jid);
    }));
    if (state.job) pollJob(state.job);
  }

  async function pollJob(id) {
    const box = document.getElementById("jobbox");
    if (!box) return;
    const a = JSON.parse(localStorage.getItem("cdut3d.jobs") || "[]");
    if (!a.includes(id)) { a.push(id); localStorage.setItem("cdut3d.jobs", JSON.stringify(a.slice(-30))); }
    try {
      const j = await api("/api/job?id=" + encodeURIComponent(id) + "&tail=300");
      box.innerHTML = `<div class="job">
        <header><span>${esc(j.id)} · ${esc(j.from || "")} · pid ${esc(j.pid || "—")}</span>
          <span class="status-${esc(j.status)}">${esc(j.status)}${j.rc != null ? " · rc=" + j.rc : ""}</span></header>
        <pre class="log">${esc(j.tail || "（暂无输出）")}</pre></div>`;
      if (j.status === "running") setTimeout(() => pollJob(id), 2000);
      else {
        toast(`任务 ${j.id} 结束：${j.status}` + (j.rc != null ? " rc=" + j.rc : ""), j.status !== "ok");
        state.ov = null;
      }
    } catch (e) {
      box.innerHTML = `<div class="note">读日志失败：${esc(e.message)}</div>`;
    }
  }

  /* ---------------- 流程 · 依据链 ---------------- */
  // 档案字段 → 人话名。**只做显示**，影响面本身由服务端从 run_chain_bid 现场取。
  const FIELD_CN = {
    src_dxf: "源图 DXF", basement: "地下室层数", floor_names: "层名表",
    top_floor: "顶层名", keep_layers: "保留图层", drop_layers: "丢弃图层",
    drawing: "图纸号", door_carve: "门洞扣减", podium_roof: "裙房顶",
    roof_stair: "屋顶楼梯间", roof_step_parapet: "退台女儿墙",
    title: "楼栋名", scope: "范围说明"
  };

  // 步骤命令：`cmd` 是**参数数组**。只做展示：去掉 python 解释器、长路径留末两段。
  const cmdShort = (c) => {
    const parts = Array.isArray(c) ? c.slice() : String(c || "").split(/\s+/).filter(Boolean);
    if (parts.length && /python[\w.]*\.exe$/i.test(parts[0])) parts.shift();
    return parts.map(a => {
      const s = String(a);
      const seg = s.split("\\");
      return seg.length > 2 ? "…\\" + seg.slice(-2).join("\\") : s;
    }).join(" ");
  };

  async function renderFlow() {
    main.innerHTML = `<p class="empty">读流程真源…</p>`;
    try {
      paintFlow(await api("/api/flow"));
    } catch (e) {
      main.innerHTML = `<div class="note">读不到流程：${esc(e.message)}</div>`;
    }
  }

  function paintFlow(f) {
    const steps = f.steps || [];
    const impact = f.impact || {};
    const gs = f.gate_of_step || {};
    const total = steps.length;
    const at = (n) => steps.findIndex(s => s.name === n);
    const rows = Object.keys(impact).map(k => {
      const list = impact[k] || [];
      return { k, list, start: list.length ? at(list[0]) : -1, n: list.length };
    }).sort((a, b) => a.start - b.start || b.n - a.n);

    main.innerHTML = head("流程 · 依据链", "一条流水线，<span class='thin'>67 栋共用</span>",
      `<b>来源</b>run_chain_bid._steps()<br><b>步骤</b>${total} 步<br>
       <b>落闸</b>${Object.keys(gs).length} 处<br><b>参数</b>${rows.length} 个字段有影响面`) +
      `<div class="note">哪一步不对，改的是<b>共用流水线</b>，不是给某一栋打补丁。<br>
        参数改了，按右表从对应那一步起重跑；不确定就在「执行」页起任务。</div>
      <div class="cols">
        <section class="block"><h2>十步 <small>每步跑完必须有件</small></h2>
          <div class="steps">${steps.map((s, i) => `
            <div class="step"><span class="sn">${String(i + 1).padStart(2, "0")}</span>
              <span class="sp">${esc(s.name)}</span>
              <span class="sp">${esc(cmdShort(s.cmd))}</span>
              <span class="sm">${gs[s.name] ? `<span class="tag guifan">闸 · ${esc(gs[s.name])}</span> `
                : ""}${(s.need || []).length ? esc(s.need.join(" · ")) : "无必需件"}</span>
            </div>`).join("")}</div>
        </section>
        <section class="block"><h2>参数影响面 <small>改哪个字段，从哪一步重跑</small></h2>
          <table class="kv">${rows.map(r => `
            <tr><th>${esc(FIELD_CN[r.k] || r.k)}<span class="gid">${esc(r.k)}</span></th>
              <td class="v">${r.start >= 0
                ? `从「${esc(steps[r.start].name)}」起 · ${r.n}/${total} 步`
                : "不在链内"}</td>
              <td class="act"><button class="btn ghost" data-fi="${esc(r.k)}">看全链</button></td></tr>`).join("")}
          </table>
        </section>
      </div>
      <div id="fi"></div>`;

    main.querySelectorAll("[data-fi]").forEach(btn => btn.addEventListener("click", () => {
      const k = btn.dataset.fi;
      const list = impact[k] || [];
      const inChain = new Set(list);
      document.getElementById("fi").innerHTML =
        `<section class="block"><h2>${esc(FIELD_CN[k] || k)}
           <small>${esc(k)} · 重跑 ${list.length} 步</small></h2>
         <div class="steps">${steps.map((s, i) => `
           <div class="step ${inChain.has(s.name) ? "no" : ""}">
             <span class="sn">${String(i + 1).padStart(2, "0")}</span>
             <span class="sp">${esc(s.name)}</span>
             <span class="sp">${esc(cmdShort(s.cmd))}</span>
             <span class="sm">${inChain.has(s.name) ? "要重跑" : "沿用"}</span>
           </div>`).join("")}</div></section>`;
      document.getElementById("fi").scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  }

  /* ---------------- 立体 · 模型 ---------------- */
  async function renderModel() {
    let bids = [];
    try {
      if (!state.ov) state.ov = await api("/api/overview");
      noteNames(state.ov);
      bids = state.ov.bids.map(r => r.bid);
    } catch (e) { /* 下拉空着，仍可手填 */ }

    main.innerHTML = head("立体 · 模型", "从一张 CAD <span class='thin'>到能转的体量</span>",
      `<b>正式</b>packs/ 里已打好的包<br><b>快速</b>DXF 墙/柱 → 盒子<br>
       <b>说明</b>快速块只看形体，不是交付件`) +
      `<section class="block"><h2>正式模型 <small>已装包，走查看器</small></h2>
        <div class="bar">
          <input id="mb" list="mbl" placeholder="楼栋 id，如 c006"
            style="min-width:200px;padding:8px;border:1px solid var(--rule-strong);background:#fff9;font-family:var(--mono)">
          <datalist id="mbl">${bids.map(b => `<option value="${esc(b)}" label="${esc(bname(b))}">`).join("")}</datalist>
          <button class="btn primary" id="mgo">打开</button>
          <button class="btn" id="mnew">新窗口</button>
          <span class="hint" style="margin:0">包不在的楼栋，查看器会自己说「清单里没有」。</span>
        </div>
        <div id="mbox" class="frame"><p class="empty">填楼栋 id 后打开。</p></div>
      </section>
      <section class="block"><h2>快速立体块 <small>一张 DXF · 不进正式链</small></h2>
        <div class="bar">
          <label class="btn primary" for="mf">选 DXF</label>
          <input id="mf" type="file" accept=".dxf" hidden>
          <label class="hint" style="margin:0">层数
            <input id="mfl" type="number" min="1" max="40" value="1"
              style="width:64px;padding:6px;border:1px solid var(--rule-strong);background:#fff9;font-family:var(--mono)">
          </label>
          <span class="hint" style="margin:0">层名含「墙」按 240 mm 厚、含「柱」按外接矩形；层高 4.00 m。</span>
        </div>
        <div id="qbox" class="frame"><p class="empty">还没有上传。把 DXF 拖到这里也行。</p></div>
      </section>`;

    const open = (bid) => {
      const b = String(bid || "").trim();
      if (!/^[A-Za-z0-9_]+$/.test(b)) return toast("楼栋 id 只认字母数字下划线", true);
      document.getElementById("mbox").innerHTML =
        `<iframe src="/demo/building.html?pack=cdut-main/${encodeURIComponent(b)}&v=${Date.now()}"
           title="${esc(b)} 的正式模型" loading="eager"></iframe>`;
    };
    document.getElementById("mgo").addEventListener("click", () => {
      const b = document.getElementById("mb").value;
      open(b);
      history.replaceState(null, "", "#/model?bid=" + encodeURIComponent(b.trim()));
    });
    document.getElementById("mnew").addEventListener("click", () => {
      const b = document.getElementById("mb").value.trim();
      if (/^[A-Za-z0-9_]+$/.test(b))
        window.open("/demo/building.html?pack=cdut-main/" + encodeURIComponent(b), "_blank");
    });

    const box = document.getElementById("qbox");
    const upload = async (file) => {
      if (!file) return;
      if (!/\.dxf$/i.test(file.name)) return toast("只认 .dxf（这张图不是 DXF）", true);
      box.innerHTML = `<p class="empty">解析 ${esc(file.name)} …（大图要几秒）</p>`;
      try {
        const r = await fetch("/api/quick3d", {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name) },
          body: await file.arrayBuffer()
        });
        const j = await r.json().catch(() => ({ ok: false, error: "返回不是 JSON" }));
        if (!r.ok || j.ok === false) throw new Error(j.error || ("HTTP " + r.status));
        const fl = Math.max(1, Math.min(40, parseInt(document.getElementById("mfl").value, 10) || 1));
        box.innerHTML = `<iframe src="/quick.html?id=${encodeURIComponent(j.id)}&floors=${fl}&v=${Date.now()}"
            title="${esc(j.name)} 的快速立体块"></iframe>
          <div class="hint">${esc(j.name)} · 盒子 ${j.counts.boxes} ·
            占地 ${(j.bbox.w / 1000).toFixed(1)} × ${(j.bbox.d / 1000).toFixed(1)} m ·
            层：${esc((j.counts.layers || []).join(" · "))}</div>`;
      } catch (e) {
        box.innerHTML = `<div class="note">这张图读不出来：${esc(e.message)}</div>`;
      }
    };
    document.getElementById("mf").addEventListener("change", (e) => upload(e.target.files[0]));
    box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("drop"); });
    box.addEventListener("dragleave", () => box.classList.remove("drop"));
    box.addEventListener("drop", (e) => {
      e.preventDefault(); box.classList.remove("drop");
      upload(e.dataTransfer.files[0]);
    });

    const pre = new URLSearchParams((location.hash.split("?")[1] || "")).get("bid");
    if (pre) { document.getElementById("mb").value = pre; open(pre); }
  }

  /* ---------------- 08 照片比对：2024 航拍 DSM vs 三维件 ----------------
     ★ 2026-10-19 用户令「你把这对别（比对）也写到 8150，不对就可以随时指出」。
     读数**只来自 compare_photo.py 落的件**（rebuild/_work/photo_<栋>[_rotNNN].json），
     页面不重算 —— 两处算同一个数，一致证明不了它对（铁律 018）。
     阈值只有两栋样本、**未标定** ⇒ 页面只报读数，不印「红/黄」。 */
  const phState = { bid: "", rot: null };
  const fm = (v, nd = 2) => (typeof v === "number" && isFinite(v)) ? v.toFixed(nd) : "—";
  const pct = (v) => (typeof v === "number" && isFinite(v)) ? (100 * v).toFixed(1) + "%" : "—";

  async function renderPhoto() {
    main.innerHTML = `<p class="empty">读比对件…</p>`;
    let idx;
    try { idx = await api("/api/photo"); }
    catch (e) {
      main.innerHTML = `<div class="note warn">读不到比对件：${esc(e.message)}</div>`;
      return;
    }
    noteNames(idx);
    const rows = idx["行"] || [];
    if (!rows.some((r) => r.bid === phState.bid)) {
      const have = rows.filter((r) => r["有"]);
      phState.bid = (have[0] || rows[0] || {}).bid || "";
      phState.rot = null;
    }
    if (!phState.bid) {
      main.innerHTML = `<div class="note warn">档案里一栋楼都没有（${esc(idx["工作目录"] || "")}）</div>`;
      return;
    }
    let d;
    try {
      d = await api(`/api/photo?bid=${encodeURIComponent(phState.bid)}`
        + (phState.rot == null ? "" : `&rot=${phState.rot}`));
    } catch (e) {
      main.innerHTML = `<div class="note warn">读这栋的件失败：${esc(e.message)}</div>`;
      return;
    }
    paintPhoto(idx, d);
  }

  function paintPhoto(idx, d) {
    const rows = idx["行"] || [];
    const bid = d.bid;
    const g = d["配准"] || {}, h = d["高度"] || {}, w = d["伪证"] || {};
    const hs = (d["热点"] || {})["条"] || [];
    const blind = d["盲区"] || [];
    const cur = d["_件"] || {};
    const img = d["_图"] || {};
    const ok = d["有"] === true;
    const opt = rows.slice()
      .sort((a, b) => (Number(b["有"]) - Number(a["有"])) || String(a.bid).localeCompare(String(b.bid)))
      .map((r) => `<option value="${esc(r.bid)}"${r.bid === bid ? " selected" : ""}>`
        + `${esc(bname(r.bid, r.title))}${r["有"] ? "（有件）" : "（未跑）"}</option>`).join("");
    const others = (d["_其它"] || []).filter((x) => x.rot != null)
      .map((x) => `<button class="phtag" data-rot="${x.rot}">另一次：${x.rot}°</button>`).join("");
    const preRot = ok && g["rot_deg"] != null ? Math.round(g["rot_deg"]) : "";

    const hsRows = hs.map((q) => {
      const sgn = q["符号中位_m"];
      const hi = typeof sgn === "number" && Math.abs(sgn) > 2;
      return `<tr>
        <td>${fm(q["E"], 0)} / ${fm(q["N"], 0)}</td>
        <td>${q["格数"] == null ? "—" : q["格数"]}</td>
        <td${hi ? ' class="hi"' : ""}>${fm(q["残差中位_m"], 1)}</td>
        <td>${pct(q["超差占比"])}</td>
        <td${hi ? ' class="hi"' : ""}>${fm(sgn, 1)}</td>
        <td>${fm(q["模型高_m"], 1)}</td>
        <td>${fm(q["影像高_m"], 1)}</td>
        <td>${typeof sgn !== "number" ? "—"
          : (sgn < 0 ? "模型比影像高" : "模型比影像低")}</td></tr>`;
    }).join("");

    main.innerHTML = head("照片比对 · 2024 航拍 DSM", "三维件 vs 影像 <span class='thin'>（不经过 CAD 的另一条证据）</span>",
      `<b>量具</b>rebuild/tools/compare_photo.py<br>
       <b>件</b>${ok ? "rebuild/_work/" + esc(cur.file || "") : "还没跑"}${ok ? "<br><b>出件</b>" + esc(stamp(cur.mtime)) : ""}
       <br><b>DSM</b>2024 航拍 · 0.25 m · EPSG:4544`) +
      `<div class="tally">
        <div><div class="n">${idx["有件的栋"] || 0} / ${idx["总栋"] || 0}</div><div class="l">有比对件的栋</div></div>
        <div><div class="n">${ok ? (d["量到的格数"] || 0) : 0}</div><div class="l">比到的 1 m 格</div></div>
        <div><div class="n">${ok ? fm(h["残差中位_m"], 2) : "—"}</div><div class="l">残差中位（m）</div></div>
        <div><div class="n">${ok ? pct(h["超差占比"]) : "—"}</div><div class="l">|残差| &gt; ${fm(h["超差阈_m"], 0)} m 占比</div></div>
        <div><div class="n">${ok ? pct(h["空足迹占比"]) : "—"}</div><div class="l">足迹内判为地面</div></div>
      </div>
      <div class="phbar">
        <select id="phbid" aria-label="选楼栋">${opt}</select>
        ${others}
        <span class="phsp"></span>
        <label class="phtag">转角（空＝按参数.json）
          <input id="phrot" type="number" min="0" max="359" value="${preRot}" placeholder="自动">
        </label>
        <button class="btn primary" id="phgo">跑一次</button>
      </div>
      <div id="phbody">${ok ? "" : `<div class="note warn">${esc(d["说明"] || "这栋还没有比对件")}</div>`}</div>`;

    document.getElementById("phbid").addEventListener("change", (e) => {
      phState.bid = e.target.value; phState.rot = null; renderPhoto();
    });
    main.querySelectorAll("[data-rot]").forEach((b) => b.addEventListener("click", () => {
      phState.rot = Number(b.dataset.rot); renderPhoto();
    }));
    document.getElementById("phgo").addEventListener("click", () => runPhoto(bid));
    main.querySelectorAll("[data-full]").forEach((el) => el.addEventListener("click", (e) => {
      e.preventDefault(); window.open(el.dataset.full, "_blank", "noopener");
    }));

    if (!ok) return;

    document.getElementById("phbody").innerHTML = `
      <div class="gates">
        <div class="g"><div class="gn">转角</div>
          <div class="gv">${fm(g["rot_deg"], 0)}°</div>
          <div class="gd">${esc(g["rot_来源"] || "")}</div></div>
        <div class="g"><div class="gn">足迹内外高差</div>
          <div class="gv">${fm(g["足迹内外高差_m"], 1)} m</div>
          <div class="gd">诊断最佳平移 ${fm((g["诊断最佳平移"] || {})["dE_m"], 1)} / ${fm((g["诊断最佳平移"] || {})["dN_m"], 1)} m（只报不用）</div></div>
        <div class="g"><div class="gn">高度残差 中位 / P90</div>
          <div class="gv">${fm(h["残差中位_m"], 2)} / ${fm(h["残差P90_m"], 1)} m</div>
          <div class="gd">δ ${fm(h["竖向偏移_m"], 2)} m · ${h["比较格数"] || 0} 格</div></div>
        <div class="g"><div class="gn">空足迹</div>
          <div class="gv">${pct(h["空足迹占比"])}</div>
          <div class="gd">足迹内 DSM 是地面 ⇒ 足迹比实体大</div></div>
        <div class="g"><div class="gn">平面粗筛 IoU</div>
          <div class="gv">${fm(g["IoU_屋面粗筛"], 3)}</div>
          <div class="gd">只作粗筛（小屋顶会漏在掩膜外）</div></div>
        <div class="g ${w["通过"] === false ? "fail" : "pass"}"><div class="gn">伪证：挪开能否找回</div>
          <div class="gv">${w["通过"] === false ? "失败" : "通过"}</div>
          <div class="gd">人工平移 ${(w["人工平移_m"] || []).join(",")} m ⇒ 挪后残差 ${fm(w["挪后残差中位_m"], 2)} m</div></div>
      </div>
      ${(() => {
        const rc = g["高度校核"] || {};
        return rc["rot_deg"] == null ? "" : `<div class="note">
          <b>高度校核（第二把尺子）</b>：按高度残差重搜转角 ⇒ ${fm(rc["rot_deg"], 0)}°，
          残差中位 ${fm(rc["残差中位_m"], 2)} m，与主判据差 ${fm(rc["与主判据差_deg"], 0)}°。
          <b>只报，不改主判据</b>：近对称平面存在 180° 多解 —— 两把尺子的差超过 90° 时，
          先看足迹是否近对称，不可据此改转角。
        </div>`;
      })()}
      <section class="block"><h2>热点 <small>按 ${fm((d["热点"] || {})["方格_m"], 0)} m 方格汇总 |DSM−模型−δ|</small></h2>
        ${hs.length ? `<table class="kv phhs"><thead><tr>
          <th>E / N（m）</th><th>格数</th><th>残差中位</th><th>超差占比</th>
          <th>符号中位</th><th>模型顶</th><th>影像高</th><th>判读</th></tr></thead>
          <tbody>${hsRows}</tbody></table>
          <div class="hint">符号 = 影像 − 模型 − δ ⇒ 负 = 模型比影像高。方格是固定窗口，
            跨体量边界的格会混两类读数 —— 要判局部，先看下面的放大图。</div>`
          : `<p class="empty">这栋没有达到最少格数的热点。</p>`}
      </section>
      <section class="block"><h2>图 <small>同窗口、同色标；点图开原尺寸</small></h2>
        <div class="phfigs">
          ${img.map ? `<figure class="phfig"><a href="${img.map}" data-full="${img.map}">
            <img src="${img.map}" alt="残差热力图与放大对照"></a>
            <figcaption>全窗口残差热力：红 = 模型比影像高，蓝 = 模型低（灰底是 DSM 高）</figcaption></figure>` : ""}
          ${img.zoom ? `<figure class="phfig"><a href="${img.zoom}" data-full="${img.zoom}">
            <img src="${img.zoom}" alt="足迹外扩的放大对照"></a>
            <figcaption>足迹外扩 10 m：左 模型顶面 · 右 DSM−模型（蓝 = 模型高，红 = 模型低）</figcaption></figure>` : ""}
          ${(!img.map && !img.zoom) ? `<p class="empty">这件没带出图（旧件或出图失败）。</p>` : ""}
        </div>
      </section>
      <section class="block"><h2>怎么读 <small>三条读数分开看</small></h2>
        <div class="prose">
          <p><b>① 配准</b>：足迹压到影像上，楼内外的高差要够大（说明落位对）。诊断最佳平移只是旁证，
            <b>不拿来改锚点</b>。</p>
          <p><b>② 高度</b>：只比两边都立着的格；δ 吸收绝对高程差，所以看的是<b>相对</b>高。
            残差中位小、P90 大 ⇒ 大部分对、局部有整块错（看热点定位）。</p>
          <p><b>③ 空足迹</b>：足迹内影像判成地面。这个数大是<b>足迹比实体大</b>（圈进院子/通道），
            不是高度差。</p>
        </div>
      </section>
      <section class="block"><h2>盲区 <small>这把尺子看不见什么</small></h2>
        <ul class="hint phblind">${blind.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
      </section>`;
  }

  async function runPhoto(bid) {
    const btn = document.getElementById("phgo");
    const rotEl = document.getElementById("phrot");
    const rv = rotEl && rotEl.value.trim() !== "" ? Number(rotEl.value) : null;
    btn.disabled = true; btn.textContent = "跑中…";
    try {
      const j = await post("/api/photo/run", { bid, rot: rv });
      toast(`已起 ${j.job}：${bid}${rv == null ? "" : " · " + rv + "°"}`);
      const tick = async () => {
        let s;
        try { s = await api(`/api/job?id=${encodeURIComponent(j.job)}&tail=40`); }
        catch (e) { toast("看不到任务：" + e.message, true); btn.disabled = false; btn.textContent = "跑一次"; return; }
        if (s.status === "running") return setTimeout(tick, 1500);
        if (s.status === "ok") {
          phState.rot = rv;          // 强制转角时新件叫 _rotNNN
          toast("比对跑完，读新件");
          return renderPhoto();
        }
        toast(`比对失败 rc=${s.rc}（${s.log || ""}）`, true);
        btn.disabled = false; btn.textContent = "跑一次";
      };
      setTimeout(tick, 800);
    } catch (e) {
      toast("起不来：" + e.message, true);
      btn.disabled = false; btn.textContent = "跑一次";
    }
  }

  route();
})();

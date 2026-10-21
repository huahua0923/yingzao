(() => {
  const $ = (id) => document.getElementById(id);
  const palette = ["#d8b06a", "#6fa8c8", "#72b895", "#bd7f80", "#8c80bb", "#b08b5c", "#7f969e", "#c59d77"];
  const state = { rows: [], selected: "", rooms: [], layering: null, floor: null, q: "" };

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
  const num = (value, digits = 1) => Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
  const floorName = (floor) => `F${Number(floor) + 1}`;

  function toast(message) {
    const el = document.createElement("div");
    el.textContent = message;
    Object.assign(el.style, {
      position: "fixed", right: "24px", bottom: "24px", zIndex: 99,
      padding: "12px 16px", background: "#111d26", border: "1px solid #354451",
      color: "#e8e1d4", fontSize: "12px", boxShadow: "0 16px 40px rgba(0,0,0,.35)",
    });
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }

  function renderBuildingList() {
    const q = $("building-search").value.trim().toLowerCase();
    const rows = state.rows.filter((b) => !q ||
      `${b.id} ${b.title || ""}`.toLowerCase().includes(q));
    $("building-total").textContent = `${state.rows.length} 栋建筑 · ${num(
      state.rows.reduce((sum, b) => sum + Number(b.rooms || 0), 0), 0)} 个房间`;
    $("building-list").innerHTML = rows.map((b) => `
      <button type="button" class="building-item ${b.id === state.selected ? "on" : ""}" data-bid="${esc(b.id)}">
        <i class="dot ${b.status === "green" ? "green" : ""}"></i>
        <span><b>${esc(b.title || b.id)}</b><small>${esc(b.id)} · ${esc(b.floors || "?")} 层</small></span>
        <em>${num(b.rooms || 0, 0)} 房</em>
      </button>`).join("");
    $("building-list").querySelectorAll("[data-bid]").forEach((btn) => {
      btn.addEventListener("click", () => selectBuilding(btn.dataset.bid));
    });
  }

  async function selectBuilding(bid) {
    if (!bid || bid === state.selected) return;
    state.selected = bid;
    state.floor = null;
    state.q = "";
    $("room-search").value = "";
    renderBuildingList();
    $("loading").hidden = false;
    $("content").hidden = true;
    try {
      const [roomsRes, layRes] = await Promise.all([
        fetch(`/packs/cdut-main/${encodeURIComponent(bid)}/ledger/rooms.json`, { cache: "no-store" }),
        fetch(`/packs/cdut-main/${encodeURIComponent(bid)}/meta/layering.json`, { cache: "no-store" }),
      ]);
      if (!roomsRes.ok) throw new Error(`房间台账读取失败：HTTP ${roomsRes.status}`);
      state.rooms = await roomsRes.json();
      state.layering = layRes.ok ? await layRes.json() : null;
      renderContent();
      $("content").hidden = false;
    } catch (error) {
      toast(error.message || "楼栋数据读取失败");
    } finally {
      $("loading").hidden = true;
    }
  }

  function renderContent() {
    const building = state.rows.find((b) => b.id === state.selected);
    if (!building) return;
    const rooms = state.rooms;
    const totalArea = rooms.reduce((sum, r) => sum + Number(r.area_m2 || 0), 0);
    const floors = new Map();
    for (const room of rooms) {
      const key = Number(room.floor);
      const item = floors.get(key) || { floor: key, rooms: 0, area: 0 };
      item.rooms += 1;
      item.area += Number(room.area_m2 || 0);
      floors.set(key, item);
    }
    const floorRows = [...floors.values()].sort((a, b) => a.floor - b.floor);
    $("hero-id").textContent = building.id.toUpperCase();
    $("hero-title").textContent = building.title || building.id;
    $("hero-sub").textContent = `${building.floors || floorRows.length} 层 · ${rooms.length} 个房间 · ${num(totalArea)} m²`;
    $("hero-status").textContent = building.status === "green" ? "已验收" : "待复核";
    $("hero-tags").innerHTML = `
      <span class="tag ${building.status === "green" ? "ok" : "fail"}">${building.status === "green" ? "模型通过" : "仍有红判据"}</span>
      <span class="tag">结构 ${esc(state.layering?.n_floors || building.floors || "—")} 层</span>
      <span class="tag">层高 ${esc(state.layering?.floor_h_m || building.floor_h_m || "—")} m</span>
      <span class="tag">${esc(building.model_sha_ok ? "模型哈希已核" : "模型哈希待核")}</span>`;

    $("metrics").innerHTML = [
      ["建筑层数", building.floors || floorRows.length, "层"],
      ["房间总数", rooms.length, "间"],
      ["建筑面积", num(totalArea), "m²"],
      ["模型体量", num(Number(building.model_bytes || 0) / 1048576), "MB"],
    ].map(([label, value, unit]) => `
      <div class="metric"><label>${label}</label><strong>${value}<small>${unit}</small></strong></div>`).join("");

    renderFloorChart(floorRows);
    renderUseChart(rooms);
    renderTopRooms(rooms);
    renderFloorList(floorRows);
    renderRooms();
  }

  function renderFloorChart(rows) {
    const max = Math.max(...rows.map((r) => r.area), 1);
    $("floor-chart").innerHTML = rows.map((row) => `
      <div class="floor-bar" data-floor="${row.floor}" title="${floorName(row.floor)} · ${num(row.area)} m²">
        <b>${num(row.area, 0)}</b><i style="height:${Math.max(3, row.area / max * 100)}%"></i>
        <span>${floorName(row.floor)}</span>
      </div>`).join("");
    $("floor-chart").querySelectorAll("[data-floor]").forEach((el) => {
      el.addEventListener("click", () => {
        const floor = Number(el.dataset.floor);
        state.floor = state.floor === floor ? null : floor;
        renderFloorList(rows);
        renderRooms();
      });
    });
  }

  function renderUseChart(rooms) {
    const counts = new Map();
    for (const room of rooms) {
      const key = room.purpose || "未标注";
      const item = counts.get(key) || { name: key, count: 0, area: 0 };
      item.count += 1;
      item.area += Number(room.area_m2 || 0);
      counts.set(key, item);
    }
    const uses = [...counts.values()].sort((a, b) => b.count - a.count);
    const total = uses.reduce((sum, x) => sum + x.count, 0) || 1;
    let cursor = 0;
    const stops = uses.map((x, i) => {
      const from = cursor;
      cursor += x.count / total * 100;
      return `${palette[i % palette.length]} ${from}% ${cursor}%`;
    });
    $("use-chart").innerHTML = `
      <div class="donut" style="background:conic-gradient(${stops.join(",")})"><strong>${uses.length}</strong></div>
      <div class="legend">${uses.slice(0, 7).map((x, i) => `
        <div class="legend-row"><i style="background:${palette[i % palette.length]}"></i>
          <span title="${esc(x.name)}">${esc(x.name)}</span><b>${x.count}</b></div>`).join("")}</div>`;
  }

  function renderTopRooms(rooms) {
    const top = [...rooms].sort((a, b) => Number(b.area_m2 || 0) - Number(a.area_m2 || 0)).slice(0, 8);
    const max = Number(top[0]?.area_m2 || 1);
    $("top-rooms").innerHTML = top.map((room) => `
      <div class="top-row"><span title="${esc(room.number)} ${esc(room.purpose || "")}">${esc(room.number)} · ${esc(room.purpose || "未标注")}</span>
        <b>${num(room.area_m2)}</b><div><i style="width:${Number(room.area_m2 || 0) / max * 100}%"></i></div></div>`).join("");
  }

  function renderFloorList(rows) {
    $("floor-all").classList.toggle("on", state.floor === null);
    $("floor-list").innerHTML = rows.map((row) => `
      <button type="button" class="floor-item ${state.floor === row.floor ? "on" : ""}" data-floor="${row.floor}">
        <b>${floorName(row.floor)}</b><span>${row.rooms} 个房间</span><em>${num(row.area)} m²</em>
      </button>`).join("");
    $("floor-list").querySelectorAll("[data-floor]").forEach((el) => {
      el.addEventListener("click", () => {
        const floor = Number(el.dataset.floor);
        state.floor = state.floor === floor ? null : floor;
        renderFloorList(rows);
        renderRooms();
      });
    });
  }

  function renderRooms() {
    const q = state.q.toLowerCase();
    const rows = state.rooms.filter((room) => {
      if (state.floor !== null && Number(room.floor) !== state.floor) return false;
      if (!q) return true;
      return `${room.number || ""} ${room.name || ""} ${room.purpose || ""} ${room.dept || ""} ${room.remark || ""}`
        .toLowerCase().includes(q);
    });
    $("room-count").textContent = `${rows.length} / ${state.rooms.length} 间`;
    $("room-body").innerHTML = rows.map((room) => `
      <tr><td><span class="floor-pill">${floorName(room.floor)}</span></td>
        <td><b>${esc(room.number || "—")}</b></td>
        <td>${esc(room.purpose || room.name || "未标注")}</td>
        <td>${esc(room.dept || "—")}</td>
        <td class="num">${num(room.area_m2)}</td>
        <td>${esc(room.remark || "—")}</td></tr>`).join("");
    $("room-empty").hidden = rows.length > 0;
  }

  async function init() {
    try {
      const response = await fetch("/building-status.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`楼栋索引读取失败：HTTP ${response.status}`);
      const data = await response.json();
      state.rows = (data.buildings || []).sort((a, b) => String(a.id).localeCompare(String(b.id)));
      renderBuildingList();
      const first = state.rows.find((b) => Number(b.rooms) > 0) || state.rows[0];
      if (!first) {
        $("loading").hidden = true;
        $("empty").hidden = false;
        return;
      }
      await selectBuilding(first.id);
    } catch (error) {
      $("loading").hidden = true;
      $("empty").hidden = false;
      $("empty").textContent = error.message || "数据读取失败";
    }
  }

  $("building-search").addEventListener("input", renderBuildingList);
  $("room-search").addEventListener("input", (event) => {
    state.q = event.target.value.trim();
    renderRooms();
  });
  $("floor-all").addEventListener("click", () => {
    state.floor = null;
    const building = state.rows.find((b) => b.id === state.selected);
    const floors = new Map();
    for (const room of state.rooms) {
      const key = Number(room.floor);
      const item = floors.get(key) || { floor: key, rooms: 0, area: 0 };
      item.rooms += 1; item.area += Number(room.area_m2 || 0); floors.set(key, item);
    }
    renderFloorList([...floors.values()].sort((a, b) => a.floor - b.floor));
    renderRooms();
  });
  $("logout").addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: "{}" });
    location.replace("/login");
  });
  init();
})();

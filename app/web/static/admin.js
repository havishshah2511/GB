/* Admin dashboard. Every number comes from /api/admin/* — nothing is derived
   in the browser except layout percentages. */
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  const nf = new Intl.NumberFormat("en-IN");
  const num = (v) => (v == null ? "—" : nf.format(Math.round(Number(v) * 100) / 100));
  const money = (v) => (v == null ? "—" : "₹" + nf.format(Math.round(Number(v))));

  const state = { view: "overview", data: {}, filters: {} };

  // ---------------------------------------------------------------- fetching
  async function api(path, options) {
    const res = await fetch("/api/admin" + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  }

  function toast(text) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = text;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2600);
  }

  async function act(fn, okMessage) {
    try {
      const out = await fn();
      if (okMessage) toast(okMessage);
      await load(state.view);
      return out;
    } catch (err) {
      toast("⚠ " + err.message);
    }
  }

  // ------------------------------------------------------------------ shared
  const strengthTag = (s) => {
    const map = {
      enquiry: ["", "Enquiry"], intent: ["", "Intent"],
      strong_intent: ["ok", "Strong Intent"], ready_to_buy: ["ok", "Ready to Buy"],
      confirmed: ["ok", "Confirmed"],
    };
    const [cls, label] = map[s] || ["", s];
    return `<span class="tag ${cls}">${esc(label)}</span>`;
  };

  const statusTag = (s) => {
    const cls = s === "active" ? "ok" : s === "expired" ? "warn" : s === "cancelled" ? "bad" : "";
    return `<span class="tag ${cls}">${esc(s)}</span>`;
  };

  function progressBar(now, floor, target, accent) {
    if (!target || target <= floor) return `<div class="bar"><i style="width:100%"></i></div>`;
    const pct = Math.max(3, Math.min(100, ((now - floor) / (target - floor)) * 100));
    return `<div class="bar ${accent ? "accent" : ""}"><i style="width:${pct.toFixed(1)}%"></i></div>`;
  }

  function table(headers, rows, empty) {
    if (!rows.length) return `<div class="empty">${esc(empty || "Nothing here yet.")}</div>`;
    return `<div class="scroll"><table><thead><tr>${
      headers.map((h) => `<th class="${h.num ? "num" : ""}">${esc(h.label ?? h)}</th>`).join("")
    }</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  }

  // ---------------------------------------------------------------- overview
  async function renderOverview(root) {
    const d = await api("/overview");
    state.data.overview = d;
    $("#engine-pill").textContent = d.engine.llm_enabled ? "NLU: Claude + rules" : "NLU: rules engine";
    $("#engine-pill").className = "pill" + (d.engine.llm_enabled ? "" : " warn");

    const kpi = (k, v, s, cls) =>
      `<div class="kpi ${cls || ""}"><div class="k">${esc(k)}</div><div class="v">${v}</div><div class="s">${esc(s || "")}</div></div>`;

    const demandRows = d.demand_by_product.map((r) => `<tr>
      <td><strong>${esc(r.category)}</strong></td>
      <td class="num">${num(r.intents)}</td>
      <td class="num">${num(r.qty)}</td>
      <td class="num">${num(r.strong_qty)}</td>
    </tr>`);

    const cityRows = d.demand_by_city.map((r) => `<tr>
      <td>${esc(r.city)}</td><td class="num">${num(r.intents)}</td><td class="num">${num(r.qty)}</td>
    </tr>`);

    const areaRows = d.demand_by_area.map((r) => `<tr>
      <td>${esc(r.area)}</td><td>${esc(r.city)}</td>
      <td class="num">${num(r.intents)}</td><td class="num">${num(r.qty)}</td>
    </tr>`);

    const dateRows = d.demand_by_date.map((r) => `<tr>
      <td class="mono">${esc(r.date)}</td><td class="num">${num(r.intents)}</td><td class="num">${num(r.qty)}</td>
    </tr>`);

    const strengthRows = d.by_strength.map((r) => `<tr>
      <td>${strengthTag(r.intent_strength)}</td>
      <td class="num">${num(r.intents)}</td><td class="num">${num(r.qty)}</td>
    </tr>`);

    const expiringRows = d.expiring.map((r) => `<tr>
      <td><code>${esc(r.id)}</code></td>
      <td>${esc(r.customer_name || "—")}</td>
      <td>${esc(r.category)}</td>
      <td class="num">${num(r.quantity)}</td>
      <td class="mono">${esc(r.expires_at || "—")}</td>
      <td>${r.group_code ? `<a href="#" data-group="${esc(r.group_code)}">${esc(r.group_code)}</a>` : "—"}</td>
    </tr>`);

    root.innerHTML = `
      <div class="grid">
        ${kpi("Active intents", num(d.intents.active), `${num(d.intents.total)} all time`)}
        ${kpi("Strong intents", num(d.intents.strong), "mobile + date captured", "brand")}
        ${kpi("Total demand qty", num(d.intents.demand_qty), "all active intents")}
        ${kpi("Strong intent qty", num(d.intents.strong_qty), "for supplier negotiation", "brand")}
        ${kpi("Active groups", num(d.groups.active_groups), "collecting intent")}
        ${kpi("Customers", num(d.customers), "unique mobiles")}
        ${kpi("Referral quantity", num(d.referrals.qty), `${num(d.referrals.intents)} intents from ${num(d.referrals.clicks)} clicks`, "accent")}
        ${kpi("Expiring soon", num(d.intents.expiring_soon), "need reconfirmation", d.intents.expiring_soon > 0 ? "accent" : "")}
      </div>

      <div class="split" style="margin-top:16px">
        <div class="panel"><header>Product-wise demand</header>
          ${table(["Category", { label: "Intents", num: 1 }, { label: "Qty", num: 1 }, { label: "Strong qty", num: 1 }], demandRows)}</div>
        <div class="panel"><header>Intent strength</header>
          ${table(["Strength", { label: "Intents", num: 1 }, { label: "Qty", num: 1 }], strengthRows)}</div>
      </div>

      <div class="split">
        <div class="panel"><header>City-wise demand</header>
          ${table(["City", { label: "Intents", num: 1 }, { label: "Qty", num: 1 }], cityRows)}</div>
        <div class="panel"><header>Area-wise demand</header>
          ${table(["Area", "City", { label: "Intents", num: 1 }, { label: "Qty", num: 1 }], areaRows)}</div>
      </div>

      <div class="split">
        <div class="panel"><header>Purchase-date demand</header>
          ${table(["Desired date", { label: "Intents", num: 1 }, { label: "Qty", num: 1 }], dateRows)}</div>
        <div class="panel"><header>Expiring intents</header>
          ${table(["Intent", "Customer", "Category", { label: "Qty", num: 1 }, "Expires", "Group"], expiringRows,
            "No intents expiring in the reconfirmation window.")}</div>
      </div>

      <div class="panel"><header>Notification outbox</header>
        <div class="grid" style="padding:14px">
          ${kpi("Queued", num(d.notifications.queued), "waiting for dispatch")}
          ${kpi("Sent", num(d.notifications.sent), "delivered")}
          ${kpi("Failed", num(d.notifications.failed), "retry needed", d.notifications.failed > 0 ? "accent" : "")}
        </div>
      </div>`;
  }

  // ------------------------------------------------------------------ groups
  async function renderGroups(root) {
    const d = await api("/groups");
    state.data.groups = d.groups;

    const groupRow = (g) => {
      const q = g.quantity, p = g.pricing;
      return `<tr>
        <td><a href="#" data-group="${esc(g.code)}"><strong>${esc(g.code)}</strong></a>
            <div class="hint">${esc(g.label)}</div></td>
        <td><span class="tag ${g.match_mode === "exact" ? "warn" : ""}">${esc(g.match_mode)}</span></td>
        <td class="num">${num(g.customers)}</td>
        <td class="num">${num(q.total_intent_qty)}</td>
        <td class="num"><strong>${num(q.strong_intent_qty)}</strong></td>
        <td class="num">${num(q.confirmed_qty)}</td>
        <td class="num">${money(p.current_price)}
            ${p.price_status === "supplier_confirmed" ? '<span class="tag ok">confirmed</span>' : ""}</td>
        <td class="num">${p.next_slab_qty ? num(p.next_slab_qty) + " → " + money(p.next_price) : "top slab"}</td>
        <td style="min-width:140px">
          ${progressBar(q.strong_intent_qty, p.current_slab_min_qty || 0, p.next_slab_qty, true)}
          <div class="hint">${g.gap_to_next_price != null ? "gap " + num(g.gap_to_next_price) : "—"}</div>
        </td>
        <td class="mono">${esc(g.purchase_window.label)}</td>
        <td class="num">${num(g.referral_quantity)}</td>
      </tr>`;
    };

    // One panel per product category -- demand is read per product first, and
    // groups of different products are never comparable side by side.
    const byCategory = new Map();
    d.groups.forEach((g) => {
      const key = g.product.category;
      if (!byCategory.has(key)) {
        byCategory.set(key, {
          label: g.product.category_label || key,
          emoji: g.product.emoji || "",
          unit: g.quantity.unit,
          groups: [],
        });
      }
      byCategory.get(key).groups.push(g);
    });

    const sum = (list, fn) => list.reduce((t, g) => t + (Number(fn(g)) || 0), 0);

    const sections = [...byCategory.entries()].map(([key, bucket]) => {
      const list = bucket.groups;
      const unit = bucket.unit === "kg" ? "kg" : "";
      const totals = [
        `${list.length} group${list.length === 1 ? "" : "s"}`,
        `${num(sum(list, (g) => g.customers))} customers`,
        `${num(sum(list, (g) => g.quantity.total_intent_qty))} ${unit} total demand`.trim(),
        `${num(sum(list, (g) => g.quantity.strong_intent_qty))} ${unit} strong`.trim(),
        `${num(sum(list, (g) => g.quantity.confirmed_qty))} ${unit} confirmed`.trim(),
      ].join(" · ");

      return `<div class="panel" data-category="${esc(key)}">
        <header>${esc(bucket.emoji)} ${esc(bucket.label)}<span class="sp"></span>
          <span class="hint">${totals}</span></header>
        ${table(["Group", "Mode", { label: "Customers", num: 1 }, { label: "Total qty", num: 1 },
                 { label: "Strong qty", num: 1 }, { label: "Confirmed", num: 1 }, { label: "Price", num: 1 },
                 { label: "Next target", num: 1 }, "Progress", "Window", { label: "Referral qty", num: 1 }],
                list.map(groupRow), "No groups in this product yet.")}
      </div>`;
    });

    root.innerHTML = `
      <div class="toolbar">
        <span class="hint">Grouped by product. Click a group code to open customers, pricing slabs,
          merge/split and messaging.</span>
        <span class="sp" style="flex:1"></span>
        <button class="act" id="merge-open">Merge groups</button>
      </div>
      ${sections.join("") || `<div class="panel"><header>Buying groups</header>
        <p class="empty">No groups yet — the first purchase intent creates one.</p></div>`}`;

    $("#merge-open")?.addEventListener("click", openMergeDialog);
  }

  async function openGroup(code) {
    const g = await api("/groups/" + encodeURIComponent(code));
    const q = g.quantity, p = g.pricing;

    const memberRows = g.members.map((m) => `<tr>
      <td><a href="#" data-intent="${esc(m.id)}"><code>${esc(m.id)}</code></a></td>
      <td>${esc(m.customer_name || "—")}<div class="hint">${esc(m.customer_mobile || "")}</div></td>
      <td class="num">${num(m.quantity)}</td>
      <td>${strengthTag(m.intent_strength)}</td>
      <td>${statusTag(m.status)}</td>
      <td>${esc(m.area || "—")}</td>
      <td class="mono">${esc(m.desired_purchase_date || "—")} → ${esc(m.maximum_purchase_date || "—")}</td>
      <td>${m.brand_flexible ? '<span class="tag ok">flexible</span>' : '<span class="tag warn">brand-locked</span>'}</td>
    </tr>`);

    const slabRows = g.slabs.map((s, i) => `<tr class="${s.active ? "" : ""}">
      <td><input type="number" min="1" value="${s.minimum_qty}" data-slab="${i}" data-f="minimum_qty" style="width:80px"></td>
      <td><input type="number" min="0" value="${s.maximum_qty ?? ""}" data-slab="${i}" data-f="maximum_qty" style="width:80px" placeholder="∞"></td>
      <td><input type="number" min="1" step="0.01" value="${s.price}" data-slab="${i}" data-f="price" style="width:110px"></td>
      <td>${s.active ? '<span class="tag ok">current</span>' : s.unlocked ? '<span class="tag">unlocked</span>' : '<span class="tag">locked</span>'}</td>
    </tr>`);

    const notifRows = g.notifications.map((n) => `<tr>
      <td><span class="tag">${esc(n.type)}</span></td>
      <td>${esc(n.customer_name || "—")}</td>
      <td>${esc(n.channel)}</td>
      <td>${statusTag(n.status)}</td>
      <td class="mono">${esc((n.created_at || "").slice(0, 16).replace("T", " "))}</td>
    </tr>`);

    const refRows = g.referrals.map((r) => `<tr>
      <td><code>${esc(r.referral_code)}</code></td>
      <td>${esc(r.referrer_name || "—")}</td>
      <td class="num">${num(r.clicks)}</td>
      <td class="num">${num(r.chats_started)}</td>
      <td class="num">${num(r.intents_submitted)}</td>
      <td class="num"><strong>${num(r.quantity_generated)}</strong></td>
    </tr>`);

    showModal(g.label + " · " + g.code, `
      <div class="grid">
        <div class="kpi"><div class="k">Active customers</div><div class="v">${num(g.customers)}</div></div>
        <div class="kpi"><div class="k">Total intent qty</div><div class="v">${num(q.total_intent_qty)}</div></div>
        <div class="kpi brand"><div class="k">Strong intent qty</div><div class="v">${num(q.strong_intent_qty)}</div></div>
        <div class="kpi"><div class="k">Confirmed qty</div><div class="v">${num(q.confirmed_qty)}</div></div>
        <div class="kpi brand"><div class="k">Current price</div><div class="v">${money(p.current_price)}</div>
          <div class="s">${p.price_status === "supplier_confirmed" ? "supplier confirmed" : "indicative"}</div></div>
        <div class="kpi accent"><div class="k">Next target</div><div class="v">${p.next_slab_qty ? num(p.next_slab_qty) : "—"}</div>
          <div class="s">${p.next_price ? money(p.next_price) : "on best slab"}</div></div>
        <div class="kpi accent"><div class="k">Gap</div><div class="v">${g.gap_to_next_price != null ? num(g.gap_to_next_price) : "—"}</div>
          <div class="s">${esc(q.unit)} to next level</div></div>
        <div class="kpi"><div class="k">Referral qty</div><div class="v">${num(g.referral_quantity)}</div>
          <div class="s">from shared links</div></div>
      </div>

      <h2>Purchase window</h2>
      <p class="hint">${esc(g.purchase_window.label)} · status <span class="tag">${esc(g.status)}</span></p>

      <h2>Customers</h2>
      <div class="panel">${table(["Intent", "Customer", { label: "Qty", num: 1 }, "Strength", "Status", "Area", "Window", "Brand"], memberRows)}</div>

      <h2>Pricing slabs</h2>
      <div class="panel">${table([{ label: "Min qty", num: 0 }, "Max qty", "Price", "State"], slabRows)}</div>
      <div class="toolbar" style="margin-top:10px">
        <button class="act primary" id="save-slabs">Save slabs</button>
        <button class="act" id="confirm-price">${p.price_status === "supplier_confirmed" ? "Un-confirm supplier price" : "Mark supplier price confirmed"}</button>
        <select id="group-status">
          ${["collecting_intent", "negotiating", "closed"].map((s) =>
            `<option value="${s}" ${g.status === s ? "selected" : ""}>${s}</option>`).join("")}
        </select>
        <button class="act" id="save-status">Set status</button>
        <button class="act" id="split-open">Split selected…</button>
      </div>

      <h2>Send a group message</h2>
      <textarea id="broadcast" placeholder="Message to every active, contactable member of this group…"></textarea>
      <div class="toolbar"><button class="act primary" id="send-broadcast">Send to ${num(g.customers)} customers</button></div>

      <h2>Referral performance</h2>
      <div class="panel">${table(["Code", "Referrer", { label: "Clicks", num: 1 }, { label: "Chats", num: 1 },
        { label: "Intents", num: 1 }, { label: "Qty generated", num: 1 }], refRows)}</div>

      <h2>Recent notifications</h2>
      <div class="panel">${table(["Type", "Customer", "Channel", "Status", "Created"], notifRows)}</div>
    `);

    $("#save-slabs").addEventListener("click", () => {
      const slabs = [];
      $$("#modal-body input[data-slab]").forEach((inp) => {
        const i = Number(inp.dataset.slab);
        slabs[i] = slabs[i] || {};
        const v = inp.value.trim();
        slabs[i][inp.dataset.f] = v === "" ? null : Number(v);
      });
      act(() => api(`/groups/${encodeURIComponent(code)}/slabs`, {
        method: "PUT", body: JSON.stringify({ slabs: slabs.filter(Boolean) }),
      }).then(() => openGroup(code)), "Slabs updated and group re-priced");
    });

    $("#confirm-price").addEventListener("click", () => {
      act(() => api(`/groups/${encodeURIComponent(code)}/supplier-price`, {
        method: "POST",
        body: JSON.stringify({ confirmed: p.price_status !== "supplier_confirmed" }),
      }).then(() => openGroup(code)), "Supplier price updated");
    });

    $("#save-status").addEventListener("click", () => {
      const s = $("#group-status").value;
      act(() => api(`/groups/${encodeURIComponent(code)}/status?new_status=${s}`, { method: "POST" })
        .then(() => openGroup(code)), "Group status updated");
    });

    $("#send-broadcast").addEventListener("click", () => {
      const message = $("#broadcast").value.trim();
      if (!message) return toast("Write a message first");
      act(() => api(`/groups/${encodeURIComponent(code)}/notify`, {
        method: "POST", body: JSON.stringify({ message }),
      }), "Message queued");
    });

    $("#split-open").addEventListener("click", () => {
      const ids = prompt("Intent IDs to move into a new group (comma separated):");
      if (!ids) return;
      act(() => api(`/groups/${encodeURIComponent(code)}/split`, {
        method: "POST",
        body: JSON.stringify({ intent_ids: ids.split(",").map((s) => s.trim()).filter(Boolean) }),
      }), "Group split");
    });
  }

  async function openMergeDialog() {
    const groups = state.data.groups || (await api("/groups")).groups;
    const opts = groups.map((g) =>
      `<option value="${esc(g.id)}">${esc(g.code)} — ${esc(g.label)} (${num(g.quantity.strong_intent_qty)})</option>`).join("");
    showModal("Merge groups", `
      <p class="hint">All intents from the source group move into the target group. The source is marked merged.</p>
      <div class="kv">
        <dt>Source group</dt><dd><select id="merge-src" style="width:100%">${opts}</select></dd>
        <dt>Target group</dt><dd><select id="merge-dst" style="width:100%">${opts}</select></dd>
      </div>`, [
      { label: "Merge", primary: true, onClick: () =>
          act(() => api("/groups/merge", {
            method: "POST",
            body: JSON.stringify({
              source_group_id: $("#merge-src").value,
              target_group_id: $("#merge-dst").value,
            }),
          }).then(() => document.getElementById("modal").close()), "Groups merged") },
    ]);
  }

  // ----------------------------------------------------------------- intents
  async function renderIntents(root) {
    const f = state.filters;
    const qs = new URLSearchParams();
    if (f.status) qs.set("status_filter", f.status);
    if (f.strength) qs.set("strength", f.strength);
    if (f.category) qs.set("category", f.category);
    if (f.city) qs.set("city", f.city);
    const d = await api("/intents?" + qs.toString());

    const rows = d.intents.map((i) => `<tr>
      <td><a href="#" data-intent="${esc(i.id)}"><code>${esc(i.id)}</code></a></td>
      <td>${esc(i.customer_name || "—")}<div class="hint">${esc(i.customer_mobile || "")}</div></td>
      <td>${esc(i.category)}<div class="hint">${esc(i.product || "")}</div></td>
      <td class="num">${num(i.quantity)} ${esc(i.unit)}</td>
      <td>${esc(i.city || "—")}<div class="hint">${esc(i.area || "")}</div></td>
      <td class="mono">${esc(i.desired_purchase_date || "—")}</td>
      <td class="mono">${esc(i.expires_at || "—")}</td>
      <td>${strengthTag(i.intent_strength)}</td>
      <td>${statusTag(i.status)}</td>
      <td>${i.group_code ? `<a href="#" data-group="${esc(i.group_code)}">${esc(i.group_code)}</a>` : "—"}</td>
    </tr>`);

    root.innerHTML = `
      <div class="toolbar">
        <select id="f-status"><option value="">All statuses</option>
          ${["active", "expired", "cancelled", "fulfilled"].map((s) =>
            `<option ${f.status === s ? "selected" : ""}>${s}</option>`).join("")}</select>
        <select id="f-strength"><option value="">All strengths</option>
          ${["enquiry", "intent", "strong_intent", "ready_to_buy", "confirmed"].map((s) =>
            `<option ${f.strength === s ? "selected" : ""}>${s}</option>`).join("")}</select>
        <select id="f-category"><option value="">All categories</option>
          ${["AC", "RICE"].map((s) => `<option ${f.category === s ? "selected" : ""}>${s}</option>`).join("")}</select>
        <input type="search" id="f-city" placeholder="City…" value="${esc(f.city || "")}">
        <button class="act" id="apply-filters">Apply</button>
        <span class="hint">${d.intents.length} shown</span>
      </div>
      <div class="panel"><header>Purchase intents</header>
        ${table(["Intent", "Customer", "Product", { label: "Qty", num: 1 }, "Location",
                 "Desired date", "Expires", "Strength", "Status", "Group"], rows)}</div>`;

    $("#apply-filters").addEventListener("click", () => {
      state.filters = {
        status: $("#f-status").value, strength: $("#f-strength").value,
        category: $("#f-category").value, city: $("#f-city").value.trim(),
      };
      load("intents");
    });
  }

  async function openIntent(id) {
    const d = await api("/intents/" + encodeURIComponent(id));
    const i = d.intent;
    const specs = Object.entries(i.specifications || {})
      .map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(v)}</dd>`).join("");

    const candidates = d.match_candidates.map((c) => `<tr>
      <td><a href="#" data-group="${esc(c.group_code)}"><code>${esc(c.group_code)}</code></a></td>
      <td>${c.compatible ? '<span class="tag ok">compatible</span>' : '<span class="tag bad">no</span>'}</td>
      <td class="num">${num(c.score)}</td>
      <td class="num">${num(c.strong_intent_qty)}</td>
      <td class="hint">${esc((c.compatible ? c.reasons : c.blockers).join(" · "))}</td>
    </tr>`);

    const chat = d.conversation
      ? `<div class="chatlog">${d.conversation.messages.map((m) => {
          if (m.card) return `<div class="m"><span class="card-note">[${esc(m.card.type)} card]</span></div>`;
          return `<div class="m ${m.role === "user" ? "user" : ""}">${esc(m.text || "")}</div>`;
        }).join("")}</div>`
      : '<div class="empty">No chat transcript (intent created via API).</div>';

    showModal("Intent " + i.id, `
      <div class="split">
        <div>
          <h2>Extracted intent</h2>
          <dl class="kv">
            <dt>Customer</dt><dd>${esc(i.customer_name || "—")} · ${esc(i.customer_mobile || "—")}</dd>
            <dt>Category</dt><dd>${esc(i.category)}</dd>
            <dt>Product</dt><dd>${esc(i.product || "—")}</dd>
            <dt>Quantity</dt><dd><input type="number" id="e-quantity" value="${i.quantity}" style="width:110px"> ${esc(i.unit)}</dd>
            <dt>City</dt><dd><input type="text" id="e-city" value="${esc(i.city || "")}"></dd>
            <dt>Area</dt><dd><input type="text" id="e-area" value="${esc(i.area || "")}"></dd>
            <dt>Desired date</dt><dd><input type="date" id="e-desired" value="${esc(i.desired_purchase_date || "")}"></dd>
            <dt>Maximum date</dt><dd><input type="date" id="e-max" value="${esc(i.maximum_purchase_date || "")}"></dd>
            <dt>Can wait</dt><dd>${i.can_wait ? "Yes" : "No"}</dd>
            <dt>Brand flexible</dt><dd>${i.brand_flexible ? "Yes" : "No"}</dd>
            <dt>Budget</dt><dd>${i.budget ? money(i.budget) : "—"}</dd>
            <dt>Strength</dt><dd>${strengthTag(i.intent_strength)}</dd>
            <dt>Status</dt><dd>${statusTag(i.status)}</dd>
            <dt>Group</dt><dd>${i.group_code ? `<a href="#" data-group="${esc(i.group_code)}">${esc(i.group_code)}</a>` : "—"}</dd>
            <dt>Expires</dt><dd class="mono">${esc(i.expires_at || "—")}</dd>
          </dl>
          <h2>Specifications</h2>
          <dl class="kv">${specs || "<dt>—</dt><dd></dd>"}</dl>
          <div class="toolbar" style="margin-top:12px">
            <button class="act primary" id="save-intent">Save corrections</button>
            <label class="hint"><input type="checkbox" id="e-rematch"> re-run matching</label>
          </div>
          <div class="toolbar">
            <select id="e-strength">${["enquiry", "intent", "strong_intent", "ready_to_buy", "confirmed"].map((s) =>
              `<option ${i.intent_strength === s ? "selected" : ""}>${s}</option>`).join("")}</select>
            <button class="act" id="set-strength">Set strength</button>
            <select id="e-status">${["active", "expired", "cancelled", "fulfilled"].map((s) =>
              `<option ${i.status === s ? "selected" : ""}>${s}</option>`).join("")}</select>
            <button class="act" id="set-status">Set status</button>
          </div>
          <div class="toolbar">
            <input type="text" id="e-move" placeholder="Target group code…">
            <button class="act" id="move-intent">Move to group</button>
          </div>
        </div>
        <div>
          <h2>Matching engine</h2>
          <div class="panel">${table(["Group", "Verdict", { label: "Score", num: 1 }, { label: "Strong qty", num: 1 }, "Why"],
            candidates, "No candidate groups.")}</div>
          <h2>Conversation</h2>
          ${chat}
        </div>
      </div>`);

    $("#save-intent").addEventListener("click", () => {
      const patch = {
        quantity: Number($("#e-quantity").value),
        city: $("#e-city").value.trim(),
        area: $("#e-area").value.trim(),
        desired_purchase_date: $("#e-desired").value || null,
        maximum_purchase_date: $("#e-max").value || null,
        rematch: $("#e-rematch").checked,
      };
      act(() => api("/intents/" + encodeURIComponent(id), { method: "PUT", body: JSON.stringify(patch) })
        .then(() => openIntent(id)), "Intent updated");
    });
    $("#set-strength").addEventListener("click", () =>
      act(() => api(`/intents/${encodeURIComponent(id)}/strength?strength=${$("#e-strength").value}`, { method: "POST" })
        .then(() => openIntent(id)), "Strength updated"));
    $("#set-status").addEventListener("click", () =>
      act(() => api(`/intents/${encodeURIComponent(id)}/status?new_status=${$("#e-status").value}`, { method: "POST" })
        .then(() => openIntent(id)), "Status updated"));
    $("#move-intent").addEventListener("click", () => {
      const target = $("#e-move").value.trim();
      if (!target) return toast("Enter a group code");
      act(() => api("/intents/move", {
        method: "POST", body: JSON.stringify({ intent_id: id, target_group_id: target }),
      }).then(() => openIntent(id)), "Intent moved");
    });
  }

  // --------------------------------------------------------------- customers
  async function renderCustomers(root) {
    const search = state.filters.customerSearch || "";
    const d = await api("/customers?search=" + encodeURIComponent(search));
    const rows = d.customers.map((c) => `<tr>
      <td><code>${esc(c.id)}</code></td>
      <td>${esc(c.name || "—")}</td>
      <td class="mono">${esc(c.mobile || "—")}</td>
      <td>${esc(c.city || "—")}<div class="hint">${esc(c.area || "")}</div></td>
      <td class="num">${num(c.intent_count)}</td>
      <td class="num">${num(c.active_qty)}</td>
      <td class="mono">${esc((c.created_at || "").slice(0, 10))}</td>
    </tr>`);
    root.innerHTML = `
      <div class="toolbar">
        <input type="search" id="cust-search" placeholder="Name, mobile or city…" value="${esc(search)}">
        <button class="act" id="cust-go">Search</button>
      </div>
      <div class="panel"><header>Customers</header>
        ${table(["ID", "Name", "Mobile", "Location", { label: "Intents", num: 1 }, { label: "Active qty", num: 1 }, "Joined"], rows)}</div>`;
    $("#cust-go").addEventListener("click", () => {
      state.filters.customerSearch = $("#cust-search").value.trim();
      load("customers");
    });
  }

  // --------------------------------------------------------------- referrals
  async function renderReferrals(root) {
    const d = await api("/referrals");
    const s = d.stats;
    const rows = d.leaderboard.map((r) => `<tr>
      <td><code>${esc(r.referral_code)}</code></td>
      <td>${esc(r.referrer_name || "—")}<div class="hint">${esc(r.referrer_mobile || "")}</div></td>
      <td>${r.group_code ? `<a href="#" data-group="${esc(r.group_code)}">${esc(r.group_code)}</a>` : "—"}</td>
      <td class="num">${num(r.clicks)}</td>
      <td class="num">${num(r.chats_started)}</td>
      <td class="num">${num(r.intents_submitted)}</td>
      <td class="num"><strong>${num(r.quantity_generated)}</strong></td>
    </tr>`);
    root.innerHTML = `
      <div class="grid">
        <div class="kpi"><div class="k">Links created</div><div class="v">${num(s.links)}</div></div>
        <div class="kpi"><div class="k">Clicks</div><div class="v">${num(s.clicks)}</div></div>
        <div class="kpi"><div class="k">Chats started</div><div class="v">${num(s.chats)}</div></div>
        <div class="kpi brand"><div class="k">Intents submitted</div><div class="v">${num(s.intents)}</div></div>
        <div class="kpi accent"><div class="k">Quantity generated</div><div class="v">${num(s.qty)}</div></div>
        <div class="kpi"><div class="k">Click → intent</div><div class="v">${num(s.conversion_rate)}%</div></div>
      </div>
      <div class="panel" style="margin-top:16px"><header>Referral performance</header>
        ${table(["Code", "Referrer", "Group", { label: "Clicks", num: 1 }, { label: "Chats", num: 1 },
                 { label: "Intents", num: 1 }, { label: "Qty generated", num: 1 }], rows,
                "No referral links yet.")}</div>`;
  }

  // ----------------------------------------------------------- notifications
  async function renderNotifications(root) {
    const d = await (await fetch("/api/notifications?limit=100")).json();
    const rows = d.notifications.map((n) => `<tr>
      <td><span class="tag">${esc(n.type)}</span></td>
      <td>${esc(n.customer_name || "—")}<div class="hint">${esc(n.customer_mobile || "")}</div></td>
      <td>${n.group_code ? `<a href="#" data-group="${esc(n.group_code)}">${esc(n.group_code)}</a>` : "—"}</td>
      <td>${esc(n.channel)}</td>
      <td>${statusTag(n.status)}</td>
      <td class="mono">${esc((n.created_at || "").slice(0, 16).replace("T", " "))}</td>
      <td><button class="act" data-msg="${esc(n.id)}">View</button></td>
    </tr>`);
    root.innerHTML = `
      <div class="grid">
        <div class="kpi"><div class="k">Total</div><div class="v">${num(d.stats.total)}</div></div>
        <div class="kpi brand"><div class="k">Sent</div><div class="v">${num(d.stats.sent)}</div></div>
        <div class="kpi accent"><div class="k">Queued</div><div class="v">${num(d.stats.queued)}</div></div>
        <div class="kpi"><div class="k">Failed</div><div class="v">${num(d.stats.failed)}</div></div>
      </div>
      <div class="panel" style="margin-top:16px"><header>Outbox
        <span class="sp"></span><span class="hint">WhatsApp primary · SMS secondary · Email optional</span></header>
        ${table(["Type", "Customer", "Group", "Channel", "Status", "Created", ""], rows, "Nothing sent yet.")}</div>`;

    $$("[data-msg]", root).forEach((b) => b.addEventListener("click", () => {
      const n = d.notifications.find((x) => x.id === b.dataset.msg);
      showModal(n.type, `<pre style="white-space:pre-wrap;font-family:var(--font)">${esc(n.message)}</pre>`);
    }));
  }

  // ------------------------------------------------------------ conversations
  async function renderConversations(root) {
    const d = await api("/conversations");
    const rows = d.conversations.map((c) => `<tr>
      <td><a href="#" data-conv="${esc(c.session_id)}"><code>${esc(c.session_id)}</code></a></td>
      <td>${esc(c.customer_name || "—")}<div class="hint">${esc(c.customer_mobile || "")}</div></td>
      <td><span class="tag ${c.stage === "done" ? "ok" : ""}">${esc(c.stage)}</span></td>
      <td>${c.intent_id ? `<a href="#" data-intent="${esc(c.intent_id)}"><code>${esc(c.intent_id)}</code></a>` : "—"}</td>
      <td class="mono">${esc((c.updated_at || "").slice(0, 16).replace("T", " "))}</td>
    </tr>`);
    root.innerHTML = `<div class="panel"><header>Chat sessions</header>
      ${table(["Session", "Customer", "Stage", "Intent", "Last activity"], rows, "No conversations yet.")}</div>`;
  }

  async function openConversation(sessionId) {
    const d = await api("/conversations/" + encodeURIComponent(sessionId));
    const c = d.conversation;
    const chat = c.messages.map((m) => {
      if (m.card) return `<div class="m"><span class="card-note">[${esc(m.card.type)} card]</span></div>`;
      return `<div class="m ${m.role === "user" ? "user" : ""}">${esc(m.text || "")}</div>`;
    }).join("");
    const extracted = Object.entries(c.extracted_information)
      .filter(([k]) => !k.startsWith("_"))
      .map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(JSON.stringify(v))}</dd>`).join("");
    showModal("Conversation " + sessionId, `
      <div class="split">
        <div><h2>Transcript</h2><div class="chatlog">${chat}</div></div>
        <div><h2>AI-extracted information</h2><dl class="kv">${extracted}</dl></div>
      </div>`);
  }

  // ------------------------------------------------------------------ pricing
  async function renderPricing(root) {
    const d = await api("/slab-templates");
    const blocks = Object.entries(d.templates).map(([key, slabs]) => `
      <div class="panel"><header><code>${esc(key)}</code></header>
        <table><thead><tr><th>Range</th><th class="num">Price</th><th>Status</th></tr></thead><tbody>
        ${slabs.map((s) => `<tr>
          <td>${num(s.minimum_qty)}${s.maximum_qty ? "–" + num(s.maximum_qty) : "+"}</td>
          <td class="num">${money(s.price)}</td>
          <td><span class="tag ${s.price_status === "supplier_confirmed" ? "ok" : ""}">${esc(s.price_status)}</span></td>
        </tr>`).join("")}</tbody></table></div>`).join("");
    root.innerHTML = `
      <p class="hint">Product-level slab templates. New groups copy these; edit a specific group's slabs from its detail view.</p>
      ${blocks || '<div class="empty">No templates loaded.</div>'}`;
  }

  // ------------------------------------------------------------------ modal
  function showModal(title, html, buttons) {
    $("#modal-title").textContent = title;
    $("#modal-body").innerHTML = html;
    const foot = $("#modal-foot");
    foot.innerHTML = "";
    (buttons || []).forEach((b) => {
      const el = document.createElement("button");
      el.className = "act" + (b.primary ? " primary" : "");
      el.textContent = b.label;
      el.addEventListener("click", b.onClick);
      foot.appendChild(el);
    });
    const dlg = $("#modal");
    if (!dlg.open) dlg.showModal();
  }

  // ------------------------------------------------------------------ router
  const VIEWS = {
    overview: renderOverview, groups: renderGroups, intents: renderIntents,
    customers: renderCustomers, referrals: renderReferrals,
    notifications: renderNotifications, conversations: renderConversations,
    pricing: renderPricing,
  };

  async function load(view) {
    state.view = view;
    $$("nav.tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
    $$("section.view").forEach((s) => s.classList.toggle("on", s.id === "view-" + view));
    const root = $("#view-" + view);
    root.innerHTML = '<div class="empty">Loading…</div>';
    try {
      await VIEWS[view](root);
      $("#updated").textContent = "updated " + new Date().toLocaleTimeString();
    } catch (err) {
      root.innerHTML = `<div class="empty">⚠ ${esc(err.message)}</div>`;
    }
  }

  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-group]");
    if (g) { e.preventDefault(); openGroup(g.dataset.group); return; }
    const i = e.target.closest("[data-intent]");
    if (i) { e.preventDefault(); openIntent(i.dataset.intent); return; }
    const c = e.target.closest("[data-conv]");
    if (c) { e.preventDefault(); openConversation(c.dataset.conv); return; }
    const t = e.target.closest("nav.tabs button");
    if (t) load(t.dataset.view);
  });

  $("#refresh").addEventListener("click", () => load(state.view));
  $("#run-jobs").addEventListener("click", () =>
    act(() => api("/maintenance/run-jobs", { method: "POST" }), "Background jobs run"));
  $("#recalc-all").addEventListener("click", () =>
    act(() => api("/maintenance/recalculate-all", { method: "POST" }), "All groups recalculated"));

  load("overview");
})();

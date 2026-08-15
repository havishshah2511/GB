/* Customer chat client. Renders whatever the backend sends -- it never
   computes prices, quantities or savings of its own. */
(() => {
  "use strict";

  const log = document.getElementById("log");
  const chipBar = document.getElementById("chips");
  const form = document.getElementById("form");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const progress = document.getElementById("progress");

  // Every visit starts a brand-new conversation -- opening the site never
  // replays an old chat. Returning buyers are recognised from their mobile
  // number instead, which is asked right after the product.
  const sessionId = "S-"
    + Math.random().toString(36).slice(2, 10).toUpperCase()
    + Date.now().toString(36).toUpperCase();

  let busy = false;

  // ---------------------------------------------------------------- helpers
  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const md = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");

  const el = (html) => {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  };

  const scroll = () => { log.scrollTop = log.scrollHeight; };

  function addBubble(role, text) {
    const node = el(`<div class="msg ${role}"><div class="bubble">${md(text)}</div></div>`);
    log.appendChild(node);
    scroll();
    return node;
  }

  function addCard(html) {
    const node = el(`<div class="msg bot">${html}</div>`);
    log.appendChild(node);
    scroll();
    return node;
  }

  function typing(on) {
    const existing = document.getElementById("typing");
    if (!on) { if (existing) existing.remove(); return; }
    if (existing) return;
    const node = el('<div class="msg bot" id="typing"><div class="bubble"><div class="typing"><i></i><i></i><i></i></div></div></div>');
    log.appendChild(node);
    scroll();
  }

  // ------------------------------------------------------------------ cards
  function groupCard(c) {
    const confirmed = c.price_confirmed
      ? '<span class="confirmed">Supplier confirmed</span>'
      : '<p class="indicative">Indicative group price — confirmed once the supplier quote is locked.</p>';

    let savings = "";
    if (c.saving_per_unit > 0) {
      savings = `<div class="save">You're saving ${esc(c.saving_per_unit_text)} per ${esc(c.unit)}
        ${c.your_saving > 0 ? `<span>For your ${esc(c.your_quantity_text)}: ${esc(c.your_saving_text)} total</span>` : ""}
      </div>`;
    }

    return addCard(`<div class="card">
      <h3>Current group</h3>
      <div class="label">${esc(c.group_label)}</div>
      <div class="stat">
        <div class="k">Buyers together need</div>
        <div class="v">${esc(c.group_quantity_text)}</div>
      </div>
      <div class="stat">
        <div class="k">Group price</div>
        <div class="pricerow">
          ${c.reference_price_text && c.saving_per_unit > 0 ? `<span class="strike">${esc(c.reference_price_text)}</span>` : ""}
          <span class="price">${esc(c.current_price_text || "—")}</span>
        </div>
        <div class="sub">per ${esc(c.unit)}${c.price_confirmed ? "" : ""}</div>
      </div>
      ${savings}
      ${confirmed}
    </div>`);
  }

  function targetCard(c) {
    const from = Number(c.current_slab_min_qty || 0);
    const to = Number(c.next_target_qty || 0);
    const now = Number(c.group_quantity || 0);
    const pct = to > from ? Math.max(4, Math.min(100, ((now - from) / (to - from)) * 100)) : 100;

    return addCard(`<div class="card target">
      <h3>Next price target</h3>
      <div class="label">Only ${esc(c.gap_text)} more needed</div>
      <div class="meter">
        <div class="track"><div class="fill" style="width:${pct.toFixed(1)}%"></div></div>
        <div class="ends"><span>${esc(c.group_quantity_text)} now</span><span>${esc(c.next_target_text)} target</span></div>
      </div>
      <div class="stat">
        <div class="k">Possible next price</div>
        <div class="pricerow">
          <span class="strike">${esc(c.current_price_text)}</span>
          <span class="price">${esc(c.next_price_text)}</span>
        </div>
      </div>
      <div class="save">Another ${esc(c.next_saving_per_unit_text)} off per ${esc(c.unit)}
        ${c.your_next_saving > 0 ? `<span>That's ${esc(c.your_next_saving_text)} extra for your ${esc(c.your_quantity_text)}</span>` : ""}
      </div>
    </div>`);
  }

  function shareCard(c) {
    const node = addCard(`<div class="card">
      <h3>Invite someone. Lower everyone's price.</h3>
      <div class="label">Share your group link</div>
      <div class="sharebox">
        <button class="btn-wa" type="button">📲 Share on WhatsApp</button>
        <button class="btn-copy" type="button">🔗 Copy Link</button>
      </div>
      <div class="sharelink">${esc(c.url)}</div>
    </div>`);

    node.querySelector(".btn-wa").addEventListener("click", () => {
      window.open(c.whatsapp_url, "_blank", "noopener");
    });
    const copy = node.querySelector(".btn-copy");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(c.url);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = c.url; document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); ta.remove();
      }
      copy.textContent = "✓ Copied";
      setTimeout(() => { copy.textContent = "🔗 Copy Link"; }, 1800);
    });
    return node;
  }

  function doneCard(c) {
    return addCard(`<div class="card">
      <h3>${esc(c.title)}</h3>
      <div class="label">${esc(c.subtitle)}</div>
      <ul>${c.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
      <div class="foot">${esc(c.footer)}</div>
    </div>`);
  }

  function statusCard(c) {
    const rows = (c.rows || []).map((r) => `
      <tr>
        <td>${esc(r.summary)}</td>
        <td><span class="tag ${esc(r.status)}">${esc(r.status)}</span></td>
      </tr>`).join("");

    const node = addCard(`<div class="card">
      <h3>${esc(c.title)}</h3>
      <div class="label">Open any time — no login needed</div>
      ${rows ? `<table class="slabs mine">${rows}</table>` : ""}
      <div class="sharebox">
        <a class="btn-wa" href="${esc(c.url)}" target="_blank" rel="noopener">📋 Open my requests</a>
        <button class="btn-copy" type="button">🔗 Copy Link</button>
      </div>
      <div class="sharelink">${esc(c.url)}</div>
    </div>`);

    const copy = node.querySelector(".btn-copy");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(c.url);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = c.url; document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); ta.remove();
      }
      copy.textContent = "✓ Copied";
      setTimeout(() => { copy.textContent = "🔗 Copy Link"; }, 1800);
    });
    return node;
  }

  function slabCard(c) {
    return addCard(`<div class="card">
      <h3>Price levels</h3>
      <div class="label">${esc(c.label || "More quantity, lower price")}</div>
      <table class="slabs">${c.rows.map((r) => `
        <tr class="${r.active ? "active" : ""}${!r.unlocked ? " locked" : ""}">
          <td>${esc(r.range)}</td><td>${esc(r.price_text)}</td>
        </tr>`).join("")}</table>
    </div>`);
  }

  function renderCard(card) {
    switch (card.type) {
      case "group": return groupCard(card);
      case "next_target": return targetCard(card);
      case "share": return shareCard(card);
      case "done": return doneCard(card);
      case "status": return statusCard(card);
      case "slabs": return slabCard(card);
      default: return null;
    }
  }

  // --------------------------------------------------------------- progress
  function renderProgress(s) {
    if (!s) return;
    const bits = [];
    if (s.quantity_text) bits.push(s.quantity_text);
    if (s.product) bits.push(s.product);
    if (s.city) bits.push(s.area ? `${s.area}, ${s.city}` : s.city);
    if (s.desired_purchase_date) bits.push(`by ${s.desired_purchase_date}`);
    progress.innerHTML = bits.map((b) => `<span>${esc(b)}</span>`).join("");
  }

  // ------------------------------------------------------------------ chips
  function renderChips(chips) {
    chipBar.innerHTML = "";
    (chips || []).forEach((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = c.label;
      b.addEventListener("click", () => submit(c.value, c.label));
      chipBar.appendChild(b);
    });
  }

  // --------------------------------------------------------------- exchange
  async function submit(value, label) {
    if (busy) return;
    const text = (value != null ? value : input.value).trim();
    if (!text) return;
    addBubble("user", label || text);
    input.value = "";
    await exchange(text);
  }

  async function exchange(message) {
    busy = true;
    send.disabled = true;
    renderChips([]);
    typing(true);

    let data;
    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: message,
          ref: window.GB.ref || null,
          group: window.GB.group || null,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (err) {
      typing(false);
      addBubble("bot", "Sorry — I couldn't reach the server just then. Please try again.");
      busy = false; send.disabled = false;
      return;
    }

    typing(false);

    // On resume we replay the stored transcript, so skip the typing pacing.
    const pace = data.resumed ? 0 : 1;

    for (const m of data.messages || []) {
      if (m.text) {
        addBubble(m.role === "user" ? "user" : "bot", m.text);
        if (pace) await new Promise((r) => setTimeout(r, 260));
      }
      if (m.card) {
        renderCard(m.card);
        if (pace) await new Promise((r) => setTimeout(r, 200));
      }
    }

    renderChips(data.chips);
    renderProgress(data.summary);

    // Watch the group only once the customer is actually in one.
    if (data.summary && data.summary.group_code) liveEnabled = true;

    if (data.input) {
      input.type = data.input.type === "tel" ? "tel"
        : data.input.type === "number" ? "number"
        : data.input.type === "date" ? "date" : "text";
      input.inputMode = data.input.type === "tel" ? "numeric"
        : data.input.type === "number" ? "numeric" : "text";
      input.placeholder = data.input.placeholder || "Type your message…";
    }

    busy = false;
    send.disabled = false;
    scroll();
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });

  // ------------------------------------------------------- live group updates
  // Once the requirement is captured we keep watching the group: if another
  // buyer's matching request merges in while this page is still open, it lands
  // in the same conversation instead of waiting for a WhatsApp message.
  const LIVE_INTERVAL_MS = 15000;
  let livePolling = false;
  let liveEnabled = false;

  async function pollLive() {
    if (!liveEnabled || busy || document.hidden || livePolling) return;
    livePolling = true;
    try {
      const res = await fetch(`/api/chat/${encodeURIComponent(sessionId)}/live`);
      if (!res.ok) return;
      const data = await res.json();
      if (!data.changed) return;
      for (const m of data.messages || []) {
        if (m.text) { addBubble("bot", m.text); await new Promise((r) => setTimeout(r, 260)); }
        if (m.card) { renderCard(m.card); }
      }
      renderProgress(data.summary);
    } catch {
      /* transient network problem -- the next tick retries */
    } finally {
      livePolling = false;
    }
  }

  setInterval(pollLive, LIVE_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) pollLive(); });

  // ------------------------------------------------------------------ start
  exchange("");
})();

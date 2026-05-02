// Job tray + global progress + cost meter live updates.
// Connects to /events/jobs (SSE), updates the docked tray on the right and
// the page-top progress strip when anything is running. When jobs settle
// (done/failed/killed) it refetches /api/cost-summary so the header meter
// matches reality immediately.

(function () {
  const tray     = document.getElementById("job-tray");
  const trayBody = document.getElementById("job-tray-body");
  const trayCount = document.getElementById("job-count");
  const globalBar = document.getElementById("global-progress");
  const costSession = document.getElementById("cost-session");
  const costLifetime = document.getElementById("cost-lifetime");
  const costDetail = document.getElementById("cost-detail");

  if (!tray) return;

  // jobs keyed by id, ordered insertion -> first-in-tray is first-rendered
  const jobs = new Map();
  const expanded = new Set();
  let pageReloadOnSettle = new Set();   // job ids whose completion should reload the page

  function fmtMoney(n) {
    if (n == null) return "$0.00";
    if (n < 0.01 && n > 0) return "$" + n.toFixed(4);
    return "$" + n.toFixed(2);
  }

  function fmtElapsed(s) {
    if (s == null) return "—";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  function statusClass(j) {
    return "is-" + (j.status || "queued");
  }

  function isActive(j) {
    return j.status === "queued" || j.status === "running";
  }

  function shouldStillShow(j) {
    if (isActive(j)) return true;
    if (j.status === "failed") return true;            // sticky until acknowledged
    if (j.ended_at && (Date.now() / 1000 - j.ended_at) < 12) return true;
    return false;
  }

  function render() {
    const visible = Array.from(jobs.values()).filter(shouldStillShow);
    visible.sort((a, b) => (b.started_at || 0) - (a.started_at || 0));

    trayCount.textContent = visible.length;
    if (visible.length === 0) {
      tray.classList.add("is-empty");
      globalBar.classList.remove("is-active");
    } else {
      tray.classList.remove("is-empty");
      const anyRunning = visible.some(j => j.status === "running");
      globalBar.classList.toggle("is-active", anyRunning);
    }

    trayBody.innerHTML = visible.map(renderJob).join("");

    // Wire kill buttons + expand toggles
    trayBody.querySelectorAll("[data-kill]").forEach(btn => {
      btn.addEventListener("click", e => {
        e.stopPropagation();
        const id = btn.getAttribute("data-kill");
        fetch(`/jobs/${id}/kill`, { method: "POST" });
      });
    });
    trayBody.querySelectorAll("[data-job-id]").forEach(row => {
      row.addEventListener("click", () => {
        const id = row.getAttribute("data-job-id");
        if (expanded.has(id)) expanded.delete(id);
        else expanded.add(id);
        renderNow();
      });
    });
  }

  function escape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderJob(j) {
    const sc = statusClass(j);
    const cost = j.cost_actual > 0 ? j.cost_actual : j.cost_estimate;
    const isExpanded = expanded.has(j.id);
    const indeterminate = j.status === "running" && (!j.progress || j.progress === 0);
    const progressStyle = indeterminate
      ? ""
      : `right: ${(100 - (j.progress || 0) * 100).toFixed(1)}%`;
    const target = j.target ? `· ${escape(j.target)}` : "";
    const log = (j.log_tail || []).join("\n");

    const killBtn = isActive(j)
      ? `<button class="kill" data-kill="${j.id}" title="Cancel">×</button>`
      : "";

    const status = j.error ? `failed · ${escape(j.error)}` : escape(j.status);

    return `
      <div class="job-row ${sc} ${isExpanded ? "is-expanded" : ""}" data-job-id="${j.id}">
        <div class="job-line-1">
          <span class="job-label">${escape(j.label)}</span>
          ${killBtn}
        </div>
        <div class="job-line-2">
          <span>${status} ${target}</span>
          <span>${fmtMoney(cost)} · ${fmtElapsed(j.elapsed_s)}</span>
        </div>
        <div class="progress-rail">
          <div class="progress-bar ${indeterminate ? "indeterminate" : ""}" style="${progressStyle}"></div>
        </div>
        ${log ? `<div class="job-log">${escape(log)}</div>` : ""}
      </div>
    `;
  }

  // Pipeline jobs can publish dozens of SSE messages per second (every log line).
  // Rebuilding the tray DOM + dispatching bf:job-update on each call freezes the tab.
  let renderRaf = null;
  let broadcastRaf = null;
  const pendingBroadcast = new Map(); // job id -> latest payload

  function scheduleRender() {
    if (renderRaf != null) return;
    renderRaf = requestAnimationFrame(() => {
      renderRaf = null;
      render();
    });
  }

  function renderNow() {
    if (renderRaf != null) {
      cancelAnimationFrame(renderRaf);
      renderRaf = null;
    }
    render();
  }

  function flushBroadcasts() {
    broadcastRaf = null;
    for (const job of pendingBroadcast.values()) {
      window.dispatchEvent(new CustomEvent("bf:job-update", { detail: job }));
    }
    pendingBroadcast.clear();
  }

  function onJobUpdate(j) {
    jobs.set(j.id, j);
    const terminal = j.status === "done" || j.status === "failed" || j.status === "killed";

    if (terminal) {
      pendingBroadcast.delete(j.id);
      renderNow();
      window.dispatchEvent(new CustomEvent("bf:job-update", { detail: j }));
      refreshCost();
      if (j.status === "done" && pageReloadOnSettle.has(j.operation)) {
        setTimeout(() => {
          const setupMatch =
            /^\/b\/([^/]+)\/setup\/?$/i.exec(window.location.pathname || "");
          if (j.operation === "style" && setupMatch) {
            const bid = setupMatch[1];
            window.location.assign(`/b/${bid}/?t=${Date.now()}`);
            return;
          }
          window.location.reload();
        }, 1200);
      }
      return;
    }

    scheduleRender();
    pendingBroadcast.set(j.id, j);
    if (broadcastRaf == null) {
      broadcastRaf = requestAnimationFrame(flushBroadcasts);
    }
  }

  // Connect SSE
  function connect() {
    let es;
    try {
      es = new EventSource("/events/jobs");
    } catch (e) {
      return;
    }
    es.addEventListener("snapshot", ev => {
      const data = JSON.parse(ev.data);
      jobs.clear();
      (data.jobs || []).forEach(j => jobs.set(j.id, j));
      renderNow();
    });
    es.addEventListener("job", ev => {
      const j = JSON.parse(ev.data);
      onJobUpdate(j);
    });
    es.addEventListener("error", () => {
      // Browser will auto-reconnect; do nothing.
    });
  }

  function refreshCost() {
    fetch("/api/cost-summary")
      .then(r => r.json())
      .then(data => {
        if (costSession) costSession.textContent = "$" + data.session_usd.toFixed(2);
        if (costLifetime) costLifetime.textContent = "$" + data.lifetime_usd.toFixed(2);
        if (costDetail) {
          const rows = (data.by_operation || []).map(row =>
            `<div class="row"><span class="op">${escape(row.op)}</span><span>$${row.usd.toFixed(4)} <span class="op">· ${row.count}</span></span></div>`
          ).join("");
          const totalRow = `<div class="row"><span class="op">session total</span><span>$${data.session_usd.toFixed(4)}</span></div>`;
          costDetail.innerHTML = (rows || `<div class="row"><span class="op">No paid operations yet</span><span>—</span></div>`) + totalRow;
        }
      })
      .catch(() => {});
  }

  // Page-author API: any element with data-reload-on="op_name" triggers
  // a soft page reload when a job of that op finishes successfully.
  document.querySelectorAll("[data-reload-on]").forEach(el => {
    el.getAttribute("data-reload-on").split(",").forEach(op =>
      pageReloadOnSettle.add(op.trim())
    );
  });

  // Wire any <form data-action> so forms submit via fetch and we get the job id back.
  document.querySelectorAll("form[data-action]").forEach(form => {
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const submit = form.querySelector("[type=submit]");
      if (submit) submit.setAttribute("disabled", "true");
      try {
        const res = await fetch(form.action, {
          method: form.method || "POST",
          body: new FormData(form),
          headers: { "Accept": "application/json" },
        });
        if (!res.ok) {
          const txt = await res.text();
          alert("Action failed: " + txt);
        }
      } finally {
        if (submit) submit.removeAttribute("disabled");
      }
    });
  });

  connect();
})();

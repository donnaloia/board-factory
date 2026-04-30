/* Account modal — opens from the header avatar.
 *
 * Three tabs (profile / api key / security). Each tab calls back to a small
 * REST surface in server.py:
 *   GET    /api/profile             -> populate fields, glyphs list, masked key
 *   PUT    /api/profile             -> save display name / email / icon
 *   PUT    /api/profile/api-key     -> save PixelLab key
 *   POST   /api/profile/password    -> change password
 *   GET    /api/profile/api-status  -> three concurrent connectivity checks
 *
 * Status idiom for save buttons:
 *   - 'Saving…' while in flight
 *   - 'Saved'   on 2xx, fades after a beat
 *   - inline error text on 4xx (we surface server-side validation messages)
 */
(() => {
  const modal = document.getElementById("account-modal");
  if (!modal) return;
  const avatar = document.getElementById("user-avatar");
  if (!avatar) return;

  let profile = null;          // last fetched /api/profile body
  let pendingGlyph = null;     // staged but unsaved glyph
  let pendingColor = null;     // staged but unsaved color

  // ────────── open / close ──────────

  let statusRunOnce = false;

  function open() {
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    if (!profile) loadProfile();
    // Kick off status checks once per page load — they're slow (~2-8s) and
    // benign to leave running in the background. By the time the user clicks
    // the API key tab, the dots are usually already populated.
    if (!statusRunOnce) {
      statusRunOnce = true;
      runStatusChecks();
      runOpenAiCheck();
    }
  }

  function close() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
  }

  avatar.addEventListener("click", (e) => { e.preventDefault(); open(); });
  modal.querySelectorAll("[data-close-modal]").forEach((el) => {
    el.addEventListener("click", close);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("is-open")) close();
  });

  // ────────── tab switching ──────────

  modal.querySelectorAll(".account-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      modal.querySelectorAll(".account-tab").forEach((t) =>
        t.classList.toggle("is-active", t === tab));
      modal.querySelectorAll(".account-tab-panel").forEach((p) =>
        p.classList.toggle("is-active", p.dataset.tabPanel === target));
      if (target === "apikey") { runStatusChecks(); runOpenAiCheck(); }
    });
  });

  // ────────── profile load + glyph grid ──────────

  async function loadProfile() {
    try {
      const r = await fetch("/api/profile");
      if (!r.ok) return;
      profile = await r.json();
      renderGlyphGrid(profile.glyphs, profile.icon_glyph);
      pendingGlyph = profile.icon_glyph;
      pendingColor = profile.icon_color;
      refreshOpenAiStatus(profile.openai_api_key_set);
    } catch (_) { /* surface nothing — modal still works for static fields */ }
  }

  function renderGlyphGrid(glyphs, current) {
    const grid = document.getElementById("glyph-grid");
    if (!grid) return;
    grid.innerHTML = "";
    glyphs.forEach((g) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "glyph-cell" + (g === current ? " is-active" : "");
      cell.textContent = g;
      cell.dataset.glyph = g;
      cell.addEventListener("click", () => {
        grid.querySelectorAll(".glyph-cell").forEach((c) => c.classList.remove("is-active"));
        cell.classList.add("is-active");
        pendingGlyph = g;
        document.getElementById("profile-icon-glyph").textContent = g;
      });
      grid.appendChild(cell);
    });
  }

  document.getElementById("profile-icon-color").addEventListener("input", (e) => {
    pendingColor = e.target.value;
    const preview = document.getElementById("profile-icon-preview");
    if (preview) preview.style.setProperty("--avatar-color", pendingColor);
    avatar.style.setProperty("--avatar-color", pendingColor);
  });

  // ────────── save profile ──────────

  document.getElementById("profile-save").addEventListener("click", async () => {
    const status = document.getElementById("profile-status");
    status.textContent = "Saving…";
    status.className = "account-status is-busy";
    const body = {
      display_name: document.getElementById("profile-display-name").value,
      email: document.getElementById("profile-email").value,
      icon_glyph: pendingGlyph,
      icon_color: pendingColor,
    };
    try {
      const r = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.text();
        // Server returns a JSON {detail: "..."} body on HTTPException.
        let msg = err;
        try { msg = JSON.parse(err).detail || err; } catch (_) {}
        status.textContent = msg.slice(0, 200);
        status.className = "account-status is-error";
        return;
      }
      const updated = await r.json();
      profile = { ...profile, ...updated };
      // Reflect updated avatar in the header without reloading.
      const headerGlyph = avatar.querySelector(".user-avatar-glyph");
      if (headerGlyph) headerGlyph.textContent = updated.icon_glyph;
      avatar.style.setProperty("--avatar-color", updated.icon_color);
      avatar.title = updated.display_name;
      status.textContent = "Saved";
      status.className = "account-status is-ok";
      setTimeout(() => { status.textContent = ""; status.className = "account-status"; }, 1800);
    } catch (e) {
      status.textContent = "Network error";
      status.className = "account-status is-error";
    }
  });

  // ────────── Connection API keys ──────────
  //
  // Each provider has its own save button. The back-end route uses
  // "absent field = no change" semantics, so we only put the key for
  // the provider the user actually edited on the wire.

  async function saveApiKey(fieldId, bodyKey, statusId, inputPlaceholderKey, afterSave) {
    const input = document.getElementById(fieldId);
    const status = document.getElementById(statusId);
    const value = input.value.trim();
    if (!value) {
      status.textContent = "Type a new key to save";
      status.className = "account-status is-error";
      return;
    }
    status.textContent = "Saving…";
    status.className = "account-status is-busy";
    try {
      const r = await fetch("/api/profile/api-key", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [bodyKey]: value }),
      });
      if (!r.ok) {
        const err = await r.text();
        let msg = err;
        try { msg = JSON.parse(err).detail || err; } catch (_) {}
        status.textContent = msg.slice(0, 200);
        status.className = "account-status is-error";
        return;
      }
      const updated = await r.json();
      profile = { ...profile, ...updated };
      input.value = "";
      input.placeholder = "•••••• " + (updated[inputPlaceholderKey] || "");
      status.textContent = "Saved";
      status.className = "account-status is-ok";
      setTimeout(() => { status.textContent = ""; status.className = "account-status"; }, 1800);
      if (afterSave) afterSave(updated);
    } catch (e) {
      status.textContent = "Network error";
      status.className = "account-status is-error";
    }
  }

  document.getElementById("apikey-pixellab-save").addEventListener("click", () => {
    saveApiKey(
      "apikey-pixellab",
      "pixellab_api_key",
      "apikey-pixellab-status",
      "pixellab_api_key_last4",
      () => runStatusChecks(),
    );
  });

  document.getElementById("apikey-openai-save").addEventListener("click", () => {
    saveApiKey(
      "apikey-openai",
      "openai_api_key",
      "apikey-openai-status",
      "openai_api_key_last4",
      (updated) => refreshOpenAiStatus(updated.openai_api_key_set),
    );
  });

  document.getElementById("apikey-test").addEventListener("click", () => runStatusChecks());
  document.getElementById("apikey-openai-test").addEventListener("click", () => runOpenAiCheck());

  function refreshOpenAiStatus(keySet) {
    const row = modal.querySelector('[data-check="openai-saved"]');
    if (!row) return;
    row.classList.remove("is-ok", "is-error", "is-busy");
    row.classList.add(keySet ? "is-ok" : "is-error");
    row.querySelector(".status-detail").textContent = keySet ? "saved" : "not set";
  }

  async function runOpenAiCheck() {
    setRowBusy("openai-live");
    try {
      const r = await fetch("/api/profile/openai-status");
      if (!r.ok) {
        setRow("openai-live", false, "check failed (HTTP " + r.status + ")");
        return;
      }
      const data = await r.json();
      setRow("openai-live", data.ok, data.detail);
    } catch (e) {
      setRow("openai-live", false, "network error");
    }
  }

  // ────────── status checks ──────────

  function setRow(check, ok, detail) {
    const row = modal.querySelector(`[data-check="${check}"]`);
    if (!row) return;
    row.classList.remove("is-ok", "is-warn", "is-error", "is-busy");
    row.classList.add(ok ? "is-ok" : "is-error");
    row.querySelector(".status-detail").textContent = detail || "";
  }

  function setRowBusy(check) {
    const row = modal.querySelector(`[data-check="${check}"]`);
    if (!row) return;
    row.classList.remove("is-ok", "is-warn", "is-error");
    row.classList.add("is-busy");
    row.querySelector(".status-detail").textContent = "Checking…";
  }

  async function runStatusChecks() {
    ["reachable", "authenticated", "quota"].forEach(setRowBusy);
    try {
      const r = await fetch("/api/profile/api-status");
      if (!r.ok) {
        ["reachable", "authenticated", "quota"].forEach((c) =>
          setRow(c, false, "Status check failed (HTTP " + r.status + ")"));
        return;
      }
      const data = await r.json();
      setRow("reachable", data.reachable.ok, data.reachable.detail);
      setRow("authenticated", data.authenticated.ok, data.authenticated.detail);
      const quotaDetail = data.quota_remaining != null
        ? `${data.quota_remaining}${data.quota_unit ? " " + data.quota_unit : ""}`
        : data.quota.detail;
      setRow("quota", data.quota.ok, quotaDetail);
    } catch (e) {
      ["reachable", "authenticated", "quota"].forEach((c) =>
        setRow(c, false, "Network error"));
    }
  }

  // ────────── change password ──────────

  document.getElementById("pw-save").addEventListener("click", async () => {
    const cur = document.getElementById("pw-current").value;
    const nw = document.getElementById("pw-new").value;
    const status = document.getElementById("pw-status");
    if (nw.length < 8) {
      status.textContent = "New password must be at least 8 characters";
      status.className = "account-status is-error";
      return;
    }
    status.textContent = "Saving…";
    status.className = "account-status is-busy";
    try {
      const r = await fetch("/api/profile/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: cur, new_password: nw }),
      });
      if (!r.ok) {
        const err = await r.text();
        let msg = err;
        try { msg = JSON.parse(err).detail || err; } catch (_) {}
        status.textContent = msg.slice(0, 200);
        status.className = "account-status is-error";
        return;
      }
      document.getElementById("pw-current").value = "";
      document.getElementById("pw-new").value = "";
      status.textContent = "Password updated";
      status.className = "account-status is-ok";
      setTimeout(() => { status.textContent = ""; status.className = "account-status"; }, 2400);
    } catch (e) {
      status.textContent = "Network error";
      status.className = "account-status is-error";
    }
  });
})();

// DELETE /api/boards/:id then go to the board picker.
(function () {
  const btn = document.getElementById("delete-board-btn");
  if (!btn) return;

  const boardId = btn.getAttribute("data-board-id");
  if (!boardId) return;

  btn.addEventListener("click", async () => {
    if (btn.disabled) return;
    const ok = window.confirm(
      "Delete this board and all of its files on disk? This cannot be undone.",
    );
    if (!ok) return;

    const prevHtml = btn.innerHTML;
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    btn.innerHTML =
      '<span class="delete-board-label">Deleting…</span>';
    try {
      const r = await fetch(`/api/boards/${encodeURIComponent(boardId)}`, {
        method: "DELETE",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      const raw = await r.text();
      if (!r.ok) {
        alert(raw.slice(0, 400) || `Delete failed (${r.status})`);
        btn.disabled = false;
        btn.removeAttribute("aria-busy");
        btn.innerHTML = prevHtml;
        return;
      }
      window.location.assign("/");
    } catch (err) {
      alert("Network error: " + err);
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      btn.innerHTML = prevHtml;
    }
  });
})();

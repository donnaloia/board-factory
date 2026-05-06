// POST /api/boards/:id/clone then navigate to the new board URL.
(function () {
  const btn = document.getElementById("clone-board-btn");
  if (!btn) return;

  const boardId = btn.getAttribute("data-board-id");
  if (!boardId) return;

  btn.addEventListener("click", async () => {
    if (btn.disabled) return;
    const prev = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Cloning…";
    try {
      const r = await fetch(`/api/boards/${encodeURIComponent(boardId)}/clone`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        credentials: "same-origin",
        body: "{}",
      });
      const raw = await r.text();
      let data;
      try {
        data = JSON.parse(raw);
      } catch {
        data = {};
      }
      if (!r.ok) {
        alert(raw.slice(0, 400) || `Clone failed (${r.status})`);
        btn.disabled = false;
        btn.textContent = prev;
        return;
      }
      const url = data.url;
      if (url) {
        window.location.assign(url);
        return;
      }
      alert("Clone succeeded but no URL was returned.");
    } catch (err) {
      alert("Network error: " + err);
    }
    btn.disabled = false;
    btn.textContent = prev;
  });
})();

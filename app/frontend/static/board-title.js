// board-title.js — click the editorial board title to rename it.
//
// Click → swap the <h1> for an <input> styled identically (same font, size,
// color via the .display-input CSS rule). Enter saves, Esc cancels, blur
// commits. Saving POSTs to ``{boardBase}/api/rename`` and updates both the title
// and the footer (which echoes the project name).

(function () {
  const initial = document.getElementById("board-title");
  if (!initial) return;
  const boardId = initial.getAttribute("data-board-id");
  if (!boardId) return;
  const boardBase = (initial.getAttribute("data-board-base") || "").trim();
  if (!boardBase) return;

  bind(initial);

  function bind(titleEl) {
    let mouseDownTime = 0;
    titleEl.addEventListener("mousedown", () => { mouseDownTime = Date.now(); });
    titleEl.addEventListener("click", () => {
      // Treat long mousedowns as text selection, not a click-to-edit.
      if (Date.now() - mouseDownTime > 350) return;
      if (titleEl.classList.contains("is-editing")) return;
      enterEditMode(titleEl);
    });
  }

  function enterEditMode(titleEl) {
    const currentText = titleEl.textContent.trim();

    const input = document.createElement("input");
    input.type = "text";
    input.value = currentText;
    input.maxLength = 80;
    input.className = "display display-input";
    input.setAttribute("aria-label", "Board name");
    input.spellcheck = false;

    titleEl.classList.add("is-editing");
    titleEl.replaceWith(input);
    input.focus();
    input.select();

    let committed = false;

    const finish = (newTitle) => {
      if (committed) return;
      committed = true;
      const restored = document.createElement("h1");
      restored.id = "board-title";
      restored.className = "display";
      restored.title = "Click to rename";
      restored.setAttribute("data-board-id", boardId);
      restored.setAttribute("data-board-base", boardBase);
      restored.setAttribute("data-original", newTitle);
      restored.textContent = newTitle;
      input.replaceWith(restored);

      // Echo into the footer ("{{ project }} · http://...").
      const footer = document.querySelector(".app-footer");
      if (footer) {
        const txt = footer.textContent;
        const idx = txt.indexOf(" ·");
        if (idx > 0) footer.textContent = newTitle + txt.slice(idx);
      }

      // Echo into the document title.
      document.title = `${newTitle} · Board Factory`;

      bind(restored);
    };

    const commit = async () => {
      const next = input.value.trim();
      if (!next || next === currentText) { finish(currentText); return; }
      try {
        const fd = new FormData();
        fd.append("project_name", next);
        const r = await fetch(`${boardBase}/api/rename`, { method: "POST", body: fd });
        if (!r.ok) {
          alert("Could not rename: " + (await r.text()));
          finish(currentText);
          return;
        }
        const data = await r.json();
        finish(data.project || next);
      } catch (err) {
        alert("Network error: " + err);
        finish(currentText);
      }
    };

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      else if (e.key === "Escape") { e.preventDefault(); finish(currentText); }
    });
    input.addEventListener("blur", commit);
  }
})();

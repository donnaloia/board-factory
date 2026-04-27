/* Centerpiece mask-and-refine canvas tool.
 *
 * Draws the current approved centerpiece on a canvas and lets the user mark
 * regions to regenerate. Two tools:
 *   - Rectangle: click and drag to mark a rectangular region
 *   - Brush: click and drag (or shift+drag) to paint freeform
 *
 * Mask is sent to the server as a base64 PNG with white = regenerate, black = preserve.
 */

(function () {
  const canvas = document.getElementById("cp-canvas");
  const ctx = canvas.getContext("2d");
  const status = document.getElementById("cp-status");
  const toolRect = document.getElementById("tool-rect");
  const toolBrush = document.getElementById("tool-brush");
  const toolClear = document.getElementById("tool-clear");
  const refineBtn = document.getElementById("refine-btn");
  const promptHint = document.getElementById("prompt-hint");

  if (!canvas) return;

  const cfg = window.bfCenterpiece || {};
  const sourceUrl = cfg.sourceUrl;

  // Off-screen mask layer (matches canvas pixel dims).
  const mask = document.createElement("canvas");
  mask.width = canvas.width;
  mask.height = canvas.height;
  const maskCtx = mask.getContext("2d");

  let baseImage = null;
  let tool = "rect";
  let drawing = false;
  let startPt = null;
  let pendingRect = null;

  function setTool(t) {
    tool = t;
    toolRect.classList.toggle("active", t === "rect");
    toolBrush.classList.toggle("active", t === "brush");
    canvas.style.cursor = t === "brush" ? "cell" : "crosshair";
  }

  function compose() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (baseImage) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(baseImage, 0, 0, canvas.width, canvas.height);
    }
    // Tinted mask overlay, semitransparent.
    ctx.globalAlpha = 0.45;
    ctx.drawImage(mask, 0, 0);
    ctx.globalAlpha = 1.0;

    // Live drag rectangle preview.
    if (pendingRect) {
      ctx.strokeStyle = "rgba(234, 88, 12, 0.95)";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(pendingRect.x, pendingRect.y, pendingRect.w, pendingRect.h);
      ctx.setLineDash([]);
    }
  }

  function pt(e) {
    const r = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - r.left) / r.width) * canvas.width,
      y: ((e.clientY - r.top) / r.height) * canvas.height,
    };
  }

  function paintBrush(p) {
    maskCtx.fillStyle = "rgba(234, 88, 12, 1)";
    maskCtx.beginPath();
    maskCtx.arc(p.x, p.y, 18, 0, Math.PI * 2);
    maskCtx.fill();
  }

  function commitRect(r) {
    maskCtx.fillStyle = "rgba(234, 88, 12, 1)";
    maskCtx.fillRect(r.x, r.y, r.w, r.h);
  }

  canvas.addEventListener("mousedown", (e) => {
    drawing = true;
    startPt = pt(e);
    if (tool === "rect" || (tool === "brush" && e.shiftKey)) {
      pendingRect = { x: startPt.x, y: startPt.y, w: 0, h: 0 };
    } else {
      paintBrush(startPt);
    }
    compose();
  });

  canvas.addEventListener("mousemove", (e) => {
    if (!drawing) return;
    const p = pt(e);
    if (pendingRect) {
      pendingRect.w = p.x - startPt.x;
      pendingRect.h = p.y - startPt.y;
    } else {
      paintBrush(p);
    }
    compose();
  });

  function endDraw() {
    if (!drawing) return;
    if (pendingRect) {
      const r = {
        x: Math.min(pendingRect.x, pendingRect.x + pendingRect.w),
        y: Math.min(pendingRect.y, pendingRect.y + pendingRect.h),
        w: Math.abs(pendingRect.w),
        h: Math.abs(pendingRect.h),
      };
      if (r.w >= 4 && r.h >= 4) commitRect(r);
      pendingRect = null;
    }
    drawing = false;
    compose();
  }
  canvas.addEventListener("mouseup", endDraw);
  canvas.addEventListener("mouseleave", endDraw);

  toolRect.addEventListener("click", () => setTool("rect"));
  toolBrush.addEventListener("click", () => setTool("brush"));
  toolClear.addEventListener("click", () => {
    maskCtx.clearRect(0, 0, mask.width, mask.height);
    compose();
  });

  // Convert the mask layer to a black-and-white PNG (white = regenerate).
  function maskToBwPng() {
    const out = document.createElement("canvas");
    out.width = mask.width; out.height = mask.height;
    const octx = out.getContext("2d");
    octx.fillStyle = "black";
    octx.fillRect(0, 0, out.width, out.height);
    const data = maskCtx.getImageData(0, 0, mask.width, mask.height).data;
    const dest = octx.getImageData(0, 0, out.width, out.height);
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] > 0) {
        dest.data[i] = 255;
        dest.data[i + 1] = 255;
        dest.data[i + 2] = 255;
        dest.data[i + 3] = 255;
      }
    }
    octx.putImageData(dest, 0, 0);
    return out.toDataURL("image/png");
  }

  refineBtn.addEventListener("click", async () => {
    const data = maskCtx.getImageData(0, 0, mask.width, mask.height).data;
    let any = false;
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] > 0) { any = true; break; }
    }
    if (!any) {
      status.textContent = "Mark a region first.";
      return;
    }
    refineBtn.disabled = true;
    status.textContent = "Refining...";
    const fd = new FormData();
    fd.append("mask_b64", maskToBwPng());
    fd.append("prompt_hint", promptHint.value || "");
    try {
      const r = await fetch("/centerpiece/refine", { method: "POST", body: fd });
      const json = await r.json();
      if (!r.ok) {
        status.textContent = "Error: " + (json.error || r.status);
        return;
      }
      status.textContent = "Saved " + json.refinement + ". Reload to see history.";
      // Auto-reload after a beat so the new refinement appears in the side list.
      setTimeout(() => window.location.reload(), 600);
    } catch (e) {
      status.textContent = "Network error: " + e;
    } finally {
      refineBtn.disabled = false;
    }
  });

  // Load source.
  baseImage = new Image();
  baseImage.onload = () => compose();
  baseImage.onerror = () => {
    status.textContent = "Could not load centerpiece — pick a candidate first.";
  };
  baseImage.src = sourceUrl;

  setTool("rect");
})();

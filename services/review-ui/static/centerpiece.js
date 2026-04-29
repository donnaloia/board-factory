/* Centerpiece mask-and-refine canvas.
 *
 * Lets the user draw a rectangle (default) or paint freeform on the centerpiece
 * to mark regions for inpainting. The refine action submits the mask to the
 * /actions/refine endpoint as a Job; jobs.js handles UI updates.
 *
 * Tool toggles in the editorial UI are <button data-tool="rect|brush|clear">.
 * The form is <form id="cp-refine-form">; we populate the hidden mask_b64
 * input on submit.
 */

(function () {
  const canvas = document.getElementById("cp-canvas");
  const source = document.getElementById("cp-source");
  if (!canvas || !source) return;

  const ctx = canvas.getContext("2d");
  const form = document.getElementById("cp-refine-form");
  const maskInput = document.getElementById("cp-mask-input");
  const toolButtons = document.querySelectorAll(".tool-toggle[data-tool]");

  // Off-screen mask layer mirrors source pixel dimensions.
  const mask = document.createElement("canvas");
  const maskCtx = mask.getContext("2d");

  let baseLoaded = false;
  let tool = "rect";
  let drawing = false;
  let startPt = null;
  let pendingRect = null;

  function setTool(t) {
    if (t === "clear") {
      maskCtx.clearRect(0, 0, mask.width, mask.height);
      compose();
      return;
    }
    tool = t;
    toolButtons.forEach(b => b.classList.toggle("is-active", b.dataset.tool === t));
    canvas.style.cursor = t === "brush" ? "cell" : "crosshair";
  }

  toolButtons.forEach(b => b.addEventListener("click", () => setTool(b.dataset.tool)));

  function fitToSource() {
    canvas.width = source.naturalWidth;
    canvas.height = source.naturalHeight;
    mask.width = source.naturalWidth;
    mask.height = source.naturalHeight;

    // Display the canvas at a comfortable viewport-bound size while keeping
    // its drawing buffer at native pixel size for the mask to be exact.
    const maxW = Math.min(720, window.innerWidth - 320);
    const ratio = source.naturalHeight / source.naturalWidth;
    canvas.style.width = `${maxW}px`;
    canvas.style.height = `${Math.round(maxW * ratio)}px`;
    baseLoaded = true;
    compose();
  }

  if (source.complete && source.naturalWidth) {
    fitToSource();
  } else {
    source.addEventListener("load", fitToSource);
  }
  window.addEventListener("resize", () => { if (baseLoaded) fitToSource(); });

  function compose() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (baseLoaded) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    }
    // Mask overlay — brass tint at low alpha so the underlying art reads through.
    ctx.globalAlpha = 0.40;
    ctx.drawImage(mask, 0, 0);
    ctx.globalAlpha = 1.0;

    if (pendingRect) {
      ctx.strokeStyle = "rgba(224, 181, 110, 0.95)";
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
    maskCtx.fillStyle = "rgba(224, 181, 110, 1)";
    maskCtx.beginPath();
    maskCtx.arc(p.x, p.y, 18, 0, Math.PI * 2);
    maskCtx.fill();
  }

  function commitRect(r) {
    maskCtx.fillStyle = "rgba(224, 181, 110, 1)";
    maskCtx.fillRect(r.x, r.y, r.w, r.h);
  }

  canvas.addEventListener("mousedown", e => {
    drawing = true;
    startPt = pt(e);
    if (tool === "rect" || (tool === "brush" && e.shiftKey)) {
      pendingRect = { x: startPt.x, y: startPt.y, w: 0, h: 0 };
    } else {
      paintBrush(startPt);
    }
    compose();
  });

  canvas.addEventListener("mousemove", e => {
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

  // Convert mask to b/w PNG (white = regenerate, black = preserve).
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

  // Bridge between the canvas and the form: populate mask_b64 just before submit.
  if (form) {
    form.addEventListener("submit", () => {
      const data = maskCtx.getImageData(0, 0, mask.width, mask.height).data;
      let any = false;
      for (let i = 3; i < data.length; i += 4) {
        if (data[i] > 0) { any = true; break; }
      }
      if (!any) {
        // Allow submit without a mask only as a safety net — server will refuse
        // gracefully. For UX, we let the action through and surface server error.
      }
      maskInput.value = maskToBwPng();
    });
  }

  setTool("rect");
})();

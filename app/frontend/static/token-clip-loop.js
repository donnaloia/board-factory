/** Looping token clip previews — shared by index and detail pages. */
(function () {
  'use strict';

  const _clipIntervals = {};

  function startClipLoop(root, fps) {
    const id = root.id;
    if (id && _clipIntervals[id]) clearInterval(_clipIntervals[id]);

    const display = root.querySelector('.ts-clip-loop-img');
    const urls = Array.from(root.querySelectorAll('.ts-clip-loop-src'))
      .map((el) => el.getAttribute('src'))
      .filter(Boolean);
    if (!display || urls.length < 2) return;

    const ms = Math.max(33, Math.round(1000 / Math.max(1, fps)));
    let idx = 0;
    const tick = () => {
      idx = (idx + 1) % urls.length;
      display.src = urls[idx];
    };
    if (id) {
      _clipIntervals[id] = setInterval(tick, ms);
    } else {
      setInterval(tick, ms);
    }
  }

  function initClipLoopPreviews() {
    const reduceMotion =
      window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    document.querySelectorAll('.ts-filmstrip[data-ts-clip-loop]').forEach((root) => {
      if (root.dataset.tsClipLoopReady) return;
      root.dataset.tsClipLoopReady = '1';
      const display = root.querySelector('.ts-clip-loop-img');
      const urls = Array.from(root.querySelectorAll('.ts-clip-loop-src'))
        .map((el) => el.getAttribute('src'))
        .filter(Boolean);
      if (!display || urls.length === 0) return;

      const label = (root.dataset.clipLabel || 'Clip').trim();
      display.alt = `${label} preview`;
      display.src = urls[0];
      if (urls.length < 2 || reduceMotion) return;

      const fps = parseFloat(root.dataset.frameFps || '12');
      startClipLoop(root, fps);
    });

    document.querySelectorAll('.ts-speed-slider').forEach((slider) => {
      const filmstripId = slider.dataset.filmstrip;
      const readout = document.getElementById(
        slider.id.replace('ts-speed-', 'ts-speed-val-'),
      );
      slider.addEventListener('input', () => {
        const fps = parseInt(slider.value, 10);
        if (readout) readout.textContent = `${fps} fps`;
        const root = document.getElementById(filmstripId);
        if (root) startClipLoop(root, fps);
      });
    });
  }

  window.TokenClipLoop = { init: initClipLoopPreviews, start: startClipLoop };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initClipLoopPreviews);
  } else {
    initClipLoopPreviews();
  }
})();

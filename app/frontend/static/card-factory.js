/* Card Factory UI — deck detail interactions.
 * Handles: board link, frame generation + candidate picker + commit,
 * prompt derivation, card generation (all + per-slot), slot prompt editing,
 * job progress polling via the shared jobs tray.
 */
(function () {
  'use strict';

  const layout = document.querySelector('.cf-layout');
  if (!layout) return;

  const DECK_PREFIX = layout.dataset.deckPrefix;
  const DECK_ID = layout.dataset.deckId || '';

  /** Same stroke palette as board cell spinners (side-panel.js). */
  const CF_SPINNER_TRACK = 'rgba(118, 128, 145, 0.26)';
  const CF_SPINNER_ARC = 'rgba(112, 122, 142, 0.9)';

  let cfActiveCardJobId = null;
  let cfCardPollTimer = null;

  // ── helpers ──

  async function post(url, body) {
    const opts = { method: 'POST' };
    if (body !== undefined) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts);
  }

  async function patch(url, body) {
    return fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  function setStatus(el, msg, isError) {
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('is-error', !!isError);
  }

  function reloadPage() {
    window.location.reload();
  }

  function cfSpinnerTiming(slotIndex) {
    const s = String(slotIndex) + '\0cf';
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    const u = (h >>> 0) / 0xffffffff;
    const durSec = 0.92 + u * 0.36;
    const h2 = Math.imul(h ^ 0x9e3779b9, 1103515245) >>> 0;
    const beginSec = -((h2 % 1000) / 1000) * 0.85;
    return { durSec, beginSec };
  }

  /** Arc spinner SVG — same construction as board ``bf-cell-spinner`` (SMIL rotate). */
  function createCfTileSpinner(slotIndex) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 40 40');
    svg.setAttribute('class', 'cf-tile-spinner-svg');
    svg.setAttribute('aria-hidden', 'true');
    const cx = 20;
    const cy = 20;
    const r = 12;
    const sw = Math.max(2, r * 0.28);
    const circ = 2 * Math.PI * r;

    const track = document.createElementNS(ns, 'circle');
    track.setAttribute('cx', String(cx));
    track.setAttribute('cy', String(cy));
    track.setAttribute('r', String(r));
    track.setAttribute('fill', 'none');
    track.setAttribute('stroke', CF_SPINNER_TRACK);
    track.setAttribute('stroke-width', String(sw));
    svg.appendChild(track);

    const arc = document.createElementNS(ns, 'circle');
    arc.setAttribute('cx', String(cx));
    arc.setAttribute('cy', String(cy));
    arc.setAttribute('r', String(r));
    arc.setAttribute('fill', 'none');
    arc.setAttribute('stroke', CF_SPINNER_ARC);
    arc.setAttribute('stroke-width', String(sw));
    arc.setAttribute('stroke-dasharray', `${circ * 0.25} ${circ * 0.75}`);
    arc.setAttribute('stroke-linecap', 'round');
    const { durSec, beginSec } = cfSpinnerTiming(slotIndex);
    const anim = document.createElementNS(ns, 'animateTransform');
    anim.setAttribute('attributeName', 'transform');
    anim.setAttribute('type', 'rotate');
    anim.setAttribute('from', `0 ${cx} ${cy}`);
    anim.setAttribute('to', `360 ${cx} ${cy}`);
    anim.setAttribute('dur', `${durSec.toFixed(2)}s`);
    if (beginSec < 0) anim.setAttribute('begin', `${beginSec.toFixed(3)}s`);
    anim.setAttribute('repeatCount', 'indefinite');
    arc.appendChild(anim);
    svg.appendChild(arc);
    return svg;
  }

  function setSlotLoading(slotIndex, on) {
    const tile = document.getElementById(`cf-tile-${slotIndex}`);
    const wrap = tile && tile.querySelector('.cf-card-img-wrap');
    if (!wrap) return;
    let overlay = wrap.querySelector('.cf-card-loading-overlay');
    if (on) {
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'cf-card-loading-overlay';
        overlay.appendChild(createCfTileSpinner(slotIndex));
        wrap.appendChild(overlay);
      }
    } else if (overlay) {
      overlay.remove();
    }
  }

  function allCardSlotIndices() {
    return Array.from(document.querySelectorAll('.cf-card-tile')).map(
      el => parseInt(el.dataset.slot, 10),
    ).filter(n => !Number.isNaN(n));
  }

  function setRegenButtonsDisabled(disabled) {
    document.querySelectorAll('[data-regen-slot]').forEach(btn => {
      btn.disabled = disabled;
    });
  }

  async function refreshCardTilesFromApi() {
    try {
      const r = await fetch(`${DECK_PREFIX}/api/cards`, { cache: 'no-store' });
      if (!r.ok) return;
      const data = await r.json();
      const ts = Date.now();
      const slots = data.slots || [];
      for (const s of slots) {
        const idx = s.slot_index;
        const tile = document.getElementById(`cf-tile-${idx}`);
        if (!tile) continue;
        const wrap = tile.querySelector('.cf-card-img-wrap');
        if (!wrap) continue;
        const titleEl = tile.querySelector('.cf-card-tile-title');
        const alt = titleEl ? titleEl.textContent.trim() : `Card ${idx + 1}`;
        if (s.live_url) {
          let img = wrap.querySelector('.cf-card-img');
          if (!img) {
            wrap.querySelector('.cf-card-placeholder')?.remove();
            img = document.createElement('img');
            img.className = 'cf-card-img';
            wrap.insertBefore(img, wrap.firstChild);
          }
          img.alt = alt || `Card ${idx + 1}`;
          img.src = `${s.live_url}?t=${ts}`;
          setSlotLoading(idx, false);
        }
      }
    } catch (_) { /* ignore */ }
  }

  function clearCardJobTimers() {
    if (cfCardPollTimer != null) {
      clearInterval(cfCardPollTimer);
      cfCardPollTimer = null;
    }
  }

  function finishCardGenerationShell(statusEl, message, isError) {
    clearCardJobTimers();
    cfActiveCardJobId = null;
    allCardSlotIndices().forEach(i => setSlotLoading(i, false));
    const genAll = document.getElementById('cf-gen-all-btn');
    if (genAll) genAll.disabled = false;
    setRegenButtonsDisabled(false);
    setStatus(statusEl, message, isError);
  }

  function isOurCardJob(job) {
    return (
      job
      && job.operation === 'card_generate_cards'
      && DECK_ID
      && job.target === DECK_ID
    );
  }

  /** Card grid: spinners + live refresh via SSE (``bf:job-update``) with polling fallback. */
  function watchCardGenerationJob(jobId, slotIndices, statusEl) {
    if (!jobId) return;
    cfActiveCardJobId = jobId;
    setStatus(statusEl, 'Running…');
    slotIndices.forEach(i => setSlotLoading(i, true));

    const genAll = document.getElementById('cf-gen-all-btn');
    if (genAll) genAll.disabled = true;
    setRegenButtonsDisabled(true);

    clearCardJobTimers();
    refreshCardTilesFromApi();

    cfCardPollTimer = setInterval(async () => {
      if (cfActiveCardJobId !== jobId) return;
      try {
        const r = await fetch(`/jobs/${jobId}`);
        if (!r.ok) {
          await refreshCardTilesFromApi();
          return;
        }
        const d = await r.json();
        await refreshCardTilesFromApi();
        if (d.status === 'done') {
          finishCardGenerationShell(statusEl, 'Done.', false);
        } else if (d.status === 'failed' || d.status === 'killed') {
          const msg =
            d.status === 'killed'
              ? 'Cancelled.'
              : 'Error: ' + (d.error || 'unknown');
          finishCardGenerationShell(statusEl, msg, d.status === 'failed');
        }
      } catch (_) { /* ignore */ }
    }, 1400);
  }

  window.addEventListener('bf:job-update', async (e) => {
    const job = e.detail;
    if (!isOurCardJob(job)) return;
    await refreshCardTilesFromApi();
    if (job.id !== cfActiveCardJobId) return;
    if (job.status === 'done') {
      finishCardGenerationShell(
        document.getElementById('cf-gen-all-status'),
        'Done.',
        false,
      );
    } else if (job.status === 'failed') {
      finishCardGenerationShell(
        document.getElementById('cf-gen-all-status'),
        'Error: ' + (job.error || 'unknown'),
        true,
      );
    } else if (job.status === 'killed') {
      finishCardGenerationShell(
        document.getElementById('cf-gen-all-status'),
        'Cancelled.',
        false,
      );
    }
  });

  // Poll job until done, then reload. Uses the global job tray for live updates.
  function watchJob(jobId, statusEl) {
    if (!jobId) return;
    setStatus(statusEl, 'Running…');
    const poll = setInterval(async () => {
      try {
        const r = await fetch(`/jobs/${jobId}`);
        if (!r.ok) { clearInterval(poll); return; }
        const d = await r.json();
        if (d.status === 'done') {
          clearInterval(poll);
          setStatus(statusEl, 'Done.');
          setTimeout(reloadPage, 600);
        } else if (d.status === 'failed' || d.status === 'killed') {
          clearInterval(poll);
          setStatus(
            statusEl,
            d.status === 'failed'
              ? 'Error: ' + (d.error || 'unknown')
              : 'Cancelled.',
            d.status === 'failed',
          );
        }
      } catch (_) {}
    }, 1500);
  }

  // ── Deck title (card set name) ──

  const deckTitleInput = document.getElementById('cf-deck-title-input');
  const deckTitleBtn = document.getElementById('cf-save-deck-title-btn');
  const deckTitleStatus = document.getElementById('cf-deck-title-status');
  if (deckTitleInput && deckTitleBtn && DECK_PREFIX) {
    async function saveDeckTitle() {
      const raw = deckTitleInput.value;
      const trimmed = raw.trim();
      if (!trimmed) {
        setStatus(deckTitleStatus, 'Title cannot be empty.', true);
        return;
      }
      deckTitleBtn.disabled = true;
      setStatus(deckTitleStatus, 'Saving…');
      const r = await patch(`${DECK_PREFIX}/api/deck`, { project_name: raw });
      deckTitleBtn.disabled = false;
      if (!r.ok) {
        let msg = 'Could not save.';
        try {
          const d = await r.json();
          if (typeof d.detail === 'string') msg = d.detail;
        } catch (_) { /* ignore */ }
        setStatus(deckTitleStatus, msg, true);
        return;
      }
      const data = await r.json();
      deckTitleInput.value = data.project_name;
      setStatus(deckTitleStatus, 'Saved.');
      document.title = `${data.project_name} · Card Factory`;
      const crumb = document.getElementById('cf-deck-breadcrumb-title');
      if (crumb) crumb.textContent = data.project_name;
    }
    deckTitleBtn.addEventListener('click', saveDeckTitle);
    deckTitleInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        saveDeckTitle();
      }
    });
  }

  // ── Section 1: board link ──

  const linkBtn = document.getElementById('cf-link-board-btn');
  if (linkBtn) {
    linkBtn.addEventListener('click', async () => {
      const select = document.getElementById('cf-board-select');
      const boardId = select && select.value;
      if (!boardId) { alert('Select a board first.'); return; }
      const statusEl = document.getElementById('cf-link-board-status');
      linkBtn.disabled = true;
      setStatus(statusEl, 'Linking…');
      const r = await post(`${DECK_PREFIX}/api/link-board`, { board_id: boardId });
      if (!r.ok) {
        linkBtn.disabled = false;
        const t = await r.text();
        setStatus(statusEl, 'Error: ' + t, true);
        return;
      }
      setStatus(statusEl, 'Linked.');
      setTimeout(reloadPage, 500);
    });
  }

  // ── Section 2: frame generation + commit ──

  const genFramesBtn = document.getElementById('cf-gen-frames-btn');
  if (genFramesBtn) {
    genFramesBtn.addEventListener('click', async () => {
      genFramesBtn.disabled = true;
      const statusEl = document.getElementById('cf-gen-frames-status');
      setStatus(statusEl, 'Enqueueing…');
      const r = await post(`${DECK_PREFIX}/api/generate-frames`);
      if (!r.ok) {
        genFramesBtn.disabled = false;
        const t = await r.text();
        setStatus(statusEl, 'Error: ' + t, true);
        return;
      }
      const { job_id } = await r.json();
      watchJob(job_id, statusEl);
    });
  }

  const regenFramesBtn = document.getElementById('cf-regen-frames-btn');
  if (regenFramesBtn) {
    regenFramesBtn.addEventListener('click', () => {
      genFramesBtn && genFramesBtn.click();
    });
  }

  const commitFrameBtn = document.getElementById('cf-commit-frame-btn');
  if (commitFrameBtn) {
    commitFrameBtn.addEventListener('click', async () => {
      const checked = document.querySelector('input[name="cf-candidate"]:checked');
      if (!checked) { alert('Select a frame candidate first.'); return; }
      commitFrameBtn.disabled = true;
      const statusEl = document.getElementById('cf-commit-frame-status');
      setStatus(statusEl, 'Committing…');
      const r = await post(`${DECK_PREFIX}/api/commit-frame`, {
        candidate_id: parseInt(checked.value, 10),
      });
      if (!r.ok) {
        commitFrameBtn.disabled = false;
        const t = await r.text();
        setStatus(statusEl, 'Error: ' + t, true);
        return;
      }
      setStatus(statusEl, 'Committed.');
      setTimeout(reloadPage, 500);
    });
  }

  // Toggle "Change frame" button shows candidates panel
  const reframeBtn = document.getElementById('cf-reframe-btn');
  const candidatesPanel = document.getElementById('cf-frame-candidates');
  if (reframeBtn && candidatesPanel) {
    reframeBtn.addEventListener('click', () => {
      candidatesPanel.style.display = '';
    });
  }

  // Highlight selected candidate card on radio change
  document.querySelectorAll('input[name="cf-candidate"]').forEach(radio => {
    radio.addEventListener('change', () => {
      document.querySelectorAll('.cf-candidate-card').forEach(c => {
        c.classList.remove('is-selected');
      });
      radio.closest('.cf-candidate-card').classList.add('is-selected');
    });
  });

  // ── Section 3: prompt derivation ──

  const deriveBtn = document.getElementById('cf-derive-prompts-btn');
  if (deriveBtn) {
    deriveBtn.addEventListener('click', async () => {
      deriveBtn.disabled = true;
      const statusEl = document.getElementById('cf-derive-prompts-status');
      setStatus(statusEl, 'Enqueueing…');
      const r = await post(`${DECK_PREFIX}/api/derive-prompts`);
      if (!r.ok) {
        deriveBtn.disabled = false;
        const t = await r.text();
        setStatus(statusEl, 'Error: ' + t, true);
        return;
      }
      const { job_id } = await r.json();
      watchJob(job_id, statusEl);
    });
  }

  // Slot prompt save
  document.querySelectorAll('[data-save-slot]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const idx = parseInt(btn.dataset.saveSlot, 10);
      const title = document.getElementById(`cf-title-${idx}`)?.value ?? '';
      const prompt = document.getElementById(`cf-prompt-${idx}`)?.value ?? '';
      const statsRaw = document.getElementById(`cf-stats-${idx}`)?.value ?? '';
      const stat_lines = statsRaw.split('\n').map(s => s.trim()).filter(Boolean);
      const statusEl = document.getElementById(`cf-slot-save-status-${idx}`);
      btn.disabled = true;
      setStatus(statusEl, 'Saving…');
      const r = await patch(`${DECK_PREFIX}/api/cards/${idx}`, {
        title,
        illustration_prompt: prompt,
        stat_lines,
      });
      btn.disabled = false;
      if (!r.ok) {
        const t = await r.text();
        setStatus(statusEl, 'Error: ' + t, true);
        return;
      }
      // Update displayed title in summary
      const titleDisplay = document.getElementById(`cf-title-display-${idx}`);
      if (titleDisplay) titleDisplay.textContent = title || `Card ${idx + 1}`;
      setStatus(statusEl, 'Saved.');
    });
  });

  // ── Section 4: card generation ──

  const genAllBtn = document.getElementById('cf-gen-all-btn');
  if (genAllBtn) {
    genAllBtn.addEventListener('click', async () => {
      const statusEl = document.getElementById('cf-gen-all-status');
      setStatus(statusEl, 'Enqueueing…');
      const r = await post(`${DECK_PREFIX}/api/generate-cards`, {});
      if (!r.ok) {
        const t = await r.text();
        setStatus(statusEl, 'Error: ' + t, true);
        return;
      }
      const { job_id } = await r.json();
      watchCardGenerationJob(job_id, allCardSlotIndices(), statusEl);
    });
  }

  document.querySelectorAll('[data-regen-slot]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const idx = parseInt(btn.dataset.regenSlot, 10);
      const statusEl = document.getElementById('cf-gen-all-status');
      setStatus(statusEl, `Regenerating card ${idx + 1}…`);
      const r = await post(`${DECK_PREFIX}/api/generate-cards`, {
        slot_indices: [idx],
      });
      if (!r.ok) {
        const t = await r.text();
        setStatus(statusEl, 'Error: ' + t, true);
        return;
      }
      const { job_id } = await r.json();
      watchCardGenerationJob(job_id, [idx], statusEl);
    });
  });
})();

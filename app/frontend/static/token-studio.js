/* Token Studio UI — detail page only.
 * Handles: delete, design explore, two-step card (pick candidate → lock & animate),
 * commit canonical, generate clip, looping clip previews (token FPS), pack+publish,
 * job polling (``/jobs/{id}`` — matches tray SSE), auto-explore after create.
 *
 * Token creation lives on the index page (token_factory_index.html inline script).
 */
(function () {
  'use strict';

  const layout = document.querySelector('.ts-layout');
  if (!layout) return;

  const STORAGE_AUTO_EXPLORE = 'bf-ts-explore-token-id';

  /** Same stroke palette as board space cell spinners (``side-panel.js``). */
  const TS_SPINNER_TRACK = 'rgba(118, 128, 145, 0.26)';
  const TS_SPINNER_ARC = 'rgba(112, 122, 142, 0.9)';

  /** Deterministic spin timing per slot — mirrors Card Factory tile spinners. */
  function tsExploreSpinnerTiming(slotIndex) {
    const s = String(slotIndex) + '\0ts-explore';
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

  /** Arc spinner SVG — same construction as ``bf-cell-spinner`` / Card Factory tiles (SMIL rotate). */
  function createTsExploreSpinner(slotIndex) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 40 40');
    svg.setAttribute('class', 'ts-explore-spinner-svg');
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
    track.setAttribute('stroke', TS_SPINNER_TRACK);
    track.setAttribute('stroke-width', String(sw));
    svg.appendChild(track);

    const arc = document.createElementNS(ns, 'circle');
    arc.setAttribute('cx', String(cx));
    arc.setAttribute('cy', String(cy));
    arc.setAttribute('r', String(r));
    arc.setAttribute('fill', 'none');
    arc.setAttribute('stroke', TS_SPINNER_ARC);
    arc.setAttribute('stroke-width', String(sw));
    arc.setAttribute('stroke-dasharray', `${circ * 0.25} ${circ * 0.75}`);
    arc.setAttribute('stroke-linecap', 'round');
    const { durSec, beginSec } = tsExploreSpinnerTiming(slotIndex);
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

  function resetDraftExploreSlots(tokenId) {
    const root = document.getElementById(`ts-explore-slots-${tokenId}`);
    if (!root) return;
    root.querySelectorAll('.ts-draft-gen-slot').forEach((slotEl, idx) => {
      const host = slotEl.querySelector('.ts-draft-slot-spinner-host');
      const img = slotEl.querySelector('.ts-draft-slot-img');
      if (host) {
        host.classList.remove('is-hidden');
        host.innerHTML = '';
        host.appendChild(createTsExploreSpinner(idx));
      }
      if (img) {
        img.classList.add('is-hidden');
        img.removeAttribute('src');
      }
    });
  }

  function fillDraftExploreSlot(tokenId, index) {
    const root = document.getElementById(`ts-explore-slots-${tokenId}`);
    if (!root) return;
    const slot = root.querySelector(`[data-slot-index="${index}"]`);
    if (!slot) return;
    const host = slot.querySelector('.ts-draft-slot-spinner-host');
    const img = slot.querySelector('.ts-draft-slot-img');
    const base = tokenBaseFor(tokenId);
    if (!base || !img) return;
    if (host) {
      host.innerHTML = '';
      host.classList.add('is-hidden');
    }
    img.src = `${base}/candidates/candidate_${index}.png?t=${Date.now()}`;
    img.alt = `Candidate ${index + 1}`;
    img.classList.remove('is-hidden');
  }

  /** FNV-1a → unsigned — stable spinner phase per token/clip (matches explore pattern). */
  function tsSpinnerSlotFromKey(key) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < key.length; i++) {
      h ^= key.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }

  /** Cover the left preview tile with the board-style arc spinner while a clip job runs. */
  function setClipGeneratingOverlay(tokenId, clipName, show) {
    const root = document.getElementById(`ts-filmstrip-${tokenId}-${clipName}`);
    if (!root) return;
    const overlay = root.querySelector('.ts-clip-loading-overlay');
    if (!overlay) return;
    if (show) {
      overlay.classList.remove('is-hidden');
      overlay.setAttribute('aria-hidden', 'false');
      overlay.innerHTML = '';
      overlay.appendChild(
        createTsExploreSpinner(tsSpinnerSlotFromKey(`${tokenId}:${clipName}`)),
      );
    } else {
      overlay.classList.add('is-hidden');
      overlay.setAttribute('aria-hidden', 'true');
      overlay.innerHTML = '';
    }
  }

  function reenableClipGenerateBtn(tokenId, clipName) {
    const btn = document.querySelector(
      `.ts-generate-clip-btn[data-token-id="${tokenId}"][data-clip="${clipName}"]`,
    );
    if (btn) btn.disabled = false;
  }

  /** Each card carries its own per-token URL prefix: /users/<u>/token-factory/<path_slug>. */
  function tokenBaseFor(tokenId) {
    const card = document.getElementById(`ts-token-${tokenId}`);
    if (!card) return null;
    return card.dataset.tokenBase || null;
  }

  /** Avoid duplicate intervals if attach + auto-explore overlap. */
  const _jobPollSeen = new Set();

  function screenDetailKey(tokenId) {
    return `bf-ts-detail-screen-${tokenId}`;
  }

  // ── HTTP helpers ──

  async function post(url, body) {
    const opts = { method: 'POST' };
    if (body !== undefined) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts);
  }

  async function del(url) {
    return fetch(url, { method: 'DELETE' });
  }

  function setStatus(el, msg, isError) {
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('is-error', !!isError);
  }

  /**
   * Toggle between idle and loading states on either the draft card
   * (``ts-token-draft``) or the legacy full panel (``ts-cands-slot-{id}``).
   */
  function setCandidatesSlotMode(tokenId, mode) {
    const root = document.getElementById(`ts-cands-slot-${tokenId}`);
    if (!root) return;
    const loading = mode === 'loading';

    // Draft card variant (.ts-draft-idle / .ts-draft-loading)
    const draftIdle = root.querySelector('.ts-draft-idle');
    const draftSpin = root.querySelector('.ts-draft-loading');
    if (draftIdle && draftSpin) {
      draftIdle.classList.toggle('is-hidden', loading);
      draftSpin.classList.toggle('is-hidden', !loading);
      draftSpin.setAttribute('aria-hidden', loading ? 'false' : 'true');
      if (loading) resetDraftExploreSlots(tokenId);
      return;
    }

    // Fallback: full-panel variant (.ts-candidates-loading / .ts-candidates-idle)
    const spin = root.querySelector('.ts-candidates-loading');
    const idle = root.querySelector('.ts-candidates-idle');
    if (!spin || !idle) return;
    spin.classList.toggle('is-hidden', !loading);
    idle.classList.toggle('is-hidden', loading);
    spin.setAttribute('aria-hidden', loading ? 'false' : 'true');
    idle.setAttribute('aria-hidden', loading ? 'true' : 'false');
  }

  /**
   * Resume polling for an in-flight ``token.design_explore`` job after refresh.
   * Without this, the HTML placeholder would look “stuck” once the tray job ages out.
   */
  function attachRunningExploreJobs() {
    fetch('/jobs')
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(data => {
        const jobList = data.jobs || [];
        document.querySelectorAll('[data-ts-flow="pick-then-detail"]').forEach(card => {
          const tokenId = card.dataset.tokenId;
          const slug = card.dataset.slug;
          if (!tokenId || !slug) return;
          const slot = document.getElementById(`ts-cands-slot-${tokenId}`);
          if (!slot) return;

          const job = jobList.find(j =>
            j.operation === 'token.design_explore' &&
            j.target === slug &&
            (j.status === 'queued' || j.status === 'running')
          );
          if (!job) return;

          const statusEl = document.getElementById(`ts-explore-status-${tokenId}`);
          const exploreBtn = document.getElementById(`ts-explore-btn-${tokenId}`);
          setCandidatesSlotMode(tokenId, 'loading');
          if (exploreBtn) exploreBtn.disabled = true;
          const draftSlotsRoot = document.getElementById(`ts-explore-slots-${tokenId}`);
          watchJob(job.id, statusEl, () => window.location.reload(), {
            tokenId,
            exploreBtn,
            draftExploreSlots: !!draftSlotsRoot,
          });
        });
      })
      .catch(() => { /* tray SSE still works */ });
  }

  /** Resume clip-generation overlay + polling after refresh while the job is still running. */
  function attachRunningClipJobs() {
    fetch('/jobs')
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(data => {
        const jobList = data.jobs || [];
        document.querySelectorAll('.ts-generate-clip-btn').forEach(btn => {
          const tokenId = btn.dataset.tokenId;
          const clipName = btn.dataset.clip;
          const card = tokenId && document.getElementById(`ts-token-${tokenId}`);
          const slug = card && card.dataset.slug;
          if (!tokenId || !clipName || !slug) return;
          const target = `${slug}/${clipName}`;
          const job = jobList.find(j =>
            j.operation === 'token.generate_clip' &&
            j.target === target &&
            (j.status === 'queued' || j.status === 'running'),
          );
          if (!job) return;
          btn.disabled = true;
          setClipGeneratingOverlay(tokenId, clipName, true);
          const statusEl = document.getElementById(
            `ts-clip-status-${tokenId}-${clipName}`,
          );
          watchJob(job.id, statusEl, () => window.location.reload(), {
            clipGen: { tokenId, clipName },
          });
        });
      })
      .catch(() => { /* ignore */ });
  }

  // ── job polling (same IDs as ``jobs.js`` / ``GET /jobs/{id}``) ─────────────

  /**
   * @param {string | undefined} jobId
   * @param {HTMLElement | null} statusEl
   * @param {function object?: void} [onComplete]
   * @param {{ tokenId?: string, exploreBtn?: HTMLButtonElement, draftExploreSlots?: boolean, clipGen?: { tokenId: string, clipName: string } }} [options]
   */
  function watchJob(jobId, statusEl, onComplete, options) {
    const opts = options || {};
    const tokenId = opts.tokenId;
    const exploreBtn = opts.exploreBtn;
    const draftExploreSlots = !!(opts.draftExploreSlots && tokenId);
    const clipGen = opts.clipGen;
    const seenCandidateReady = new Set();

    if (!jobId) return;
    if (_jobPollSeen.has(jobId)) return;
    _jobPollSeen.add(jobId);

    setStatus(statusEl, 'Running…');

    const poll = setInterval(async () => {
      try {
        const r = await fetch(`/jobs/${jobId}`);
        if (!r.ok) {
          clearInterval(poll);
          _jobPollSeen.delete(jobId);
          if (r.status === 404) {
            setStatus(statusEl, 'Job not found (server restarted?). Refresh and retry.', true);
          }
          if (clipGen) {
            setClipGeneratingOverlay(clipGen.tokenId, clipGen.clipName, false);
            reenableClipGenerateBtn(clipGen.tokenId, clipGen.clipName);
          }
          if (tokenId != null) setCandidatesSlotMode(tokenId, 'idle');
          if (exploreBtn) exploreBtn.disabled = false;
          return;
        }
        const d = await r.json();
        if (draftExploreSlots && Array.isArray(d.events)) {
          for (const ev of d.events) {
            if (ev.step !== 'candidate_ready') continue;
            const det = ev.detail;
            const idx =
              det && typeof det.index === 'number' ? det.index : null;
            if (idx == null || seenCandidateReady.has(idx)) continue;
            seenCandidateReady.add(idx);
            fillDraftExploreSlot(tokenId, idx);
          }
        }
        if (d.status === 'done') {
          clearInterval(poll);
          _jobPollSeen.delete(jobId);
          setStatus(statusEl, 'Done.');
          if (onComplete) onComplete(d);
        } else if (d.status === 'failed' || d.status === 'killed') {
          clearInterval(poll);
          _jobPollSeen.delete(jobId);
          const msg =
            d.status === 'killed'
              ? 'Cancelled.'
              : (d.error || 'Error.');
          setStatus(statusEl, msg, true);
          if (clipGen) {
            setClipGeneratingOverlay(clipGen.tokenId, clipGen.clipName, false);
            reenableClipGenerateBtn(clipGen.tokenId, clipGen.clipName);
          }
          if (tokenId != null) setCandidatesSlotMode(tokenId, 'idle');
          if (exploreBtn) exploreBtn.disabled = false;
        }
      } catch (_) { /* network hiccup, retry */ }
    }, 1500);
  }

  function syncSelectedThumb(tokenId) {
    const checked = document.querySelector(`input[name="ts-cand-${tokenId}"]:checked`);
    const label = checked && checked.closest('label');
    const srcImg = label && label.querySelector('.ts-candidate-img');
    const thumb = document.getElementById(`ts-selected-thumb-${tokenId}`);
    if (!thumb || !srcImg) return;
    thumb.src = srcImg.src;
    thumb.alt = srcImg.alt || 'Selected candidate';
    thumb.classList.remove('is-empty');
  }

  function showPickScreen(card) {
    const pick = card.querySelector('.ts-screen-pick');
    const detail = card.querySelector('.ts-screen-detail');
    if (pick) pick.classList.remove('is-hidden');
    if (detail) detail.classList.add('is-hidden');
  }

  function showDetailScreen(card, tokenId) {
    syncSelectedThumb(tokenId);
    const pick = card.querySelector('.ts-screen-pick');
    const detail = card.querySelector('.ts-screen-detail');
    if (pick) pick.classList.add('is-hidden');
    if (detail) detail.classList.remove('is-hidden');
  }

  function initTwoStepCards() {
    document.querySelectorAll('[data-ts-flow="pick-then-detail"]').forEach(card => {
      const tokenId = card.dataset.tokenId;
      if (!tokenId) return;

      const sk = screenDetailKey(tokenId);
      if (sessionStorage.getItem(sk) === 'detail') {
        showDetailScreen(card, tokenId);
      } else {
        showPickScreen(card);
      }

      const cont = card.querySelector('.ts-continue-detail-btn');
      if (cont) {
        cont.addEventListener('click', () => {
          sessionStorage.setItem(sk, 'detail');
          showDetailScreen(card, tokenId);
        });
      }

      const back = card.querySelector('.ts-back-pick-btn');
      if (back) {
        back.addEventListener('click', () => {
          sessionStorage.removeItem(sk);
          showPickScreen(card);
        });
      }

      card.querySelectorAll(`input[name="ts-cand-${tokenId}"]`).forEach(r => {
        r.addEventListener('change', () => {
          if (sessionStorage.getItem(sk) === 'detail') syncSelectedThumb(tokenId);
        });
      });
    });
  }

  // ── Auto-run candidate generation for a freshly created token ─────────────

  function tryAutoExploreAfterCreate() {
    const tokenId = sessionStorage.getItem(STORAGE_AUTO_EXPLORE);
    if (!tokenId) return;
    sessionStorage.removeItem(STORAGE_AUTO_EXPLORE);
    const card = document.getElementById(`ts-token-${tokenId}`);
    if (!card) return;
    const statusEl = document.getElementById(`ts-explore-status-${tokenId}`);
    const exploreBtn = document.getElementById(`ts-explore-btn-${tokenId}`);
    const slot = document.getElementById(`ts-cands-slot-${tokenId}`);
    if (slot) setCandidatesSlotMode(tokenId, 'loading');
    if (exploreBtn) exploreBtn.disabled = true;

    const base = tokenBaseFor(tokenId);
    if (!base) {
      setStatus(statusEl, 'Token not on this page; refresh to retry.', true);
      if (slot) setCandidatesSlotMode(tokenId, 'idle');
      if (exploreBtn) exploreBtn.disabled = false;
      return;
    }
    post(`${base}/api/explore`).then(async r => {
      if (!r.ok) {
        let msg = 'Could not start candidate generation.';
        try {
          const d = await r.json();
          msg = d.detail || msg;
        } catch (_) { /* ignore */ }
        setStatus(statusEl, msg, true);
        if (slot) setCandidatesSlotMode(tokenId, 'idle');
        if (exploreBtn) exploreBtn.disabled = false;
        return;
      }
      const { job_id: jobId } = await r.json();
      const draftSlotsRoot = document.getElementById(`ts-explore-slots-${tokenId}`);
      watchJob(jobId, statusEl, () => window.location.reload(), {
        tokenId: slot ? tokenId : undefined,
        exploreBtn,
        draftExploreSlots: !!draftSlotsRoot,
      });
    }).catch(err => {
      setStatus(statusEl, String(err), true);
      if (slot) setCandidatesSlotMode(tokenId, 'idle');
      if (exploreBtn) exploreBtn.disabled = false;
    });
  }

  // ── delete token ──

  document.querySelectorAll('.ts-delete-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tokenId = btn.dataset.tokenId;
      if (!tokenId) return;
      if (!confirm('Delete this token and all its generated data?')) return;
      sessionStorage.removeItem(screenDetailKey(tokenId));
      const base = tokenBaseFor(tokenId);
      if (!base) { alert('Token not on this page.'); return; }
      const r = await del(base);
      if (r.ok) window.location.href = '/token-factory/';
      else alert('Could not delete token.');
    });
  });

  // ── design explore (regenerate candidates) ──

  document.querySelectorAll('[id^="ts-explore-btn-"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tokenId = btn.dataset.tokenId;
      const statusEl = document.getElementById(`ts-explore-status-${tokenId}`);
      const slot = document.getElementById(`ts-cands-slot-${tokenId}`);
      btn.disabled = true;
      if (slot) setCandidatesSlotMode(tokenId, 'loading');
      setStatus(statusEl, 'Generating…');
      try {
        const base = tokenBaseFor(tokenId);
        if (!base) {
          setStatus(statusEl, 'Token not on this page; refresh.', true);
          if (slot) setCandidatesSlotMode(tokenId, 'idle');
          btn.disabled = false;
          return;
        }
        const r = await post(`${base}/api/explore`);
        if (!r.ok) {
          const d = await r.json();
          setStatus(statusEl, d.detail || 'Error.', true);
          if (slot) setCandidatesSlotMode(tokenId, 'idle');
          btn.disabled = false;
          return;
        }
        const { job_id: jobId } = await r.json();
        const draftSlotsRoot = document.getElementById(`ts-explore-slots-${tokenId}`);
        watchJob(jobId, statusEl, () => window.location.reload(), {
          tokenId: slot ? tokenId : undefined,
          exploreBtn: btn,
          draftExploreSlots: !!draftSlotsRoot,
        });
      } catch (err) {
        setStatus(statusEl, String(err), true);
        if (slot) setCandidatesSlotMode(tokenId, 'idle');
        btn.disabled = false;
      }
    });
  });

  // ── commit canonical (lock design) ──

  document.querySelectorAll('.ts-commit-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tokenId = btn.dataset.tokenId;
      const statusEl = document.getElementById(`ts-commit-status-${tokenId}`);
      const styleInput = document.getElementById(`ts-style-${tokenId}`);
      const styleSentence = (styleInput ? styleInput.value.trim() : '');
      if (!styleSentence) { setStatus(statusEl, 'Character description required.', true); return; }

      const radios = document.querySelectorAll(`input[name="ts-cand-${tokenId}"]`);
      let candidateIndex = 0;
      radios.forEach(r => { if (r.checked) candidateIndex = parseInt(r.value, 10); });

      btn.disabled = true;
      setStatus(statusEl, 'Locking…');
      try {
        const base = tokenBaseFor(tokenId);
        if (!base) { setStatus(statusEl, 'Token not on this page; refresh.', true); btn.disabled = false; return; }
        const r = await post(
          `${base}/api/commit-canonical`,
          { candidate_index: candidateIndex, style_sentence: styleSentence }
        );
        if (!r.ok) {
          const d = await r.json();
          setStatus(statusEl, d.detail || 'Error.', true);
          btn.disabled = false;
        } else {
          sessionStorage.removeItem(screenDetailKey(tokenId));
          window.location.reload();
        }
      } catch (err) {
        setStatus(statusEl, String(err), true);
        btn.disabled = false;
      }
    });
  });

  // ── unlock design ──


  // ── generate clip ──

  document.querySelectorAll('.ts-generate-clip-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tokenId = btn.dataset.tokenId;
      const clipName = btn.dataset.clip;
      const statusEl = document.getElementById(`ts-clip-status-${tokenId}-${clipName}`);
      btn.disabled = true;
      setClipGeneratingOverlay(tokenId, clipName, true);
      setStatus(statusEl, 'Starting…');
      try {
        const base = tokenBaseFor(tokenId);
        if (!base) {
          setStatus(statusEl, 'Token not on this page; refresh.', true);
          setClipGeneratingOverlay(tokenId, clipName, false);
          btn.disabled = false;
          return;
        }
        const r = await post(`${base}/api/clips/${clipName}`);
        if (!r.ok) {
          const d = await r.json();
          setStatus(statusEl, d.detail || 'Error.', true);
          setClipGeneratingOverlay(tokenId, clipName, false);
          btn.disabled = false;
          return;
        }
        const { job_id: jobId } = await r.json();
        watchJob(jobId, statusEl, () => window.location.reload(), {
          clipGen: { tokenId, clipName },
        });
      } catch (err) {
        setStatus(statusEl, String(err), true);
        setClipGeneratingOverlay(tokenId, clipName, false);
        btn.disabled = false;
      }
    });
  });

  // ── pack & publish ──

  document.querySelectorAll('.ts-publish-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tokenId = btn.dataset.tokenId;
      const statusEl = document.getElementById(`ts-publish-status-${tokenId}`);
      btn.disabled = true;
      setStatus(statusEl, 'Packing…');
      try {
        const base = tokenBaseFor(tokenId);
        if (!base) { setStatus(statusEl, 'Token not on this page; refresh.', true); btn.disabled = false; return; }
        const r = await post(`${base}/api/publish`);
        if (!r.ok) {
          const d = await r.json();
          setStatus(statusEl, d.detail || 'Error.', true);
          btn.disabled = false;
          return;
        }
        const { job_id: jobId } = await r.json();
        watchJob(jobId, statusEl, () => window.location.reload());
      } catch (err) {
        setStatus(statusEl, String(err), true);
        btn.disabled = false;
      }
    });
  });

  if (window.TokenClipLoop) window.TokenClipLoop.init();
  initTwoStepCards();
  attachRunningExploreJobs();
  attachRunningClipJobs();
  tryAutoExploreAfterCreate();
})();

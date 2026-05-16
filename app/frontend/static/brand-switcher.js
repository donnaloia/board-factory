// Domain switcher in the header. Click the brand-mark to toggle a dropdown
// listing the three top-level factories. Label + active row follow the URL.

(function () {
  const BRAND_LABELS = {
    board: 'Board Factory',
    token: 'Token Factory',
    card: 'Card Factory',
  };

  function brandDomainFromPath(pathname) {
    const p = pathname || '';
    if (p.startsWith('/card-factory') || p.includes('/card-factory/')) {
      return 'card';
    }
    if (p.startsWith('/token-factory') || p.includes('/token-factory/')) {
      return 'token';
    }
    return 'board';
  }

  const root = document.querySelector('[data-brand-switcher]');
  if (!root) return;

  const trigger = root.querySelector('#brand-mark-trigger');
  const dropdown = root.querySelector('#brand-dropdown');
  if (!trigger || !dropdown) return;

  const path = window.location.pathname;
  const current = brandDomainFromPath(path);

  root.dataset.brandDomain = current;

  trigger.textContent = BRAND_LABELS[current];
  trigger.setAttribute(
    'aria-label',
    `${BRAND_LABELS[current]} — switch product`
  );

  root.querySelectorAll('.brand-dropdown-item').forEach((el) => {
    if (el.dataset.domain === current) el.classList.add('is-active');
  });

  function open() {
    root.classList.add('is-open');
    trigger.setAttribute('aria-expanded', 'true');
    dropdown.setAttribute('aria-hidden', 'false');
  }
  function close() {
    root.classList.remove('is-open');
    trigger.setAttribute('aria-expanded', 'false');
    dropdown.setAttribute('aria-hidden', 'true');
  }
  function toggle() {
    if (root.classList.contains('is-open')) close();
    else open();
  }

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    toggle();
  });

  document.addEventListener('click', (e) => {
    if (!root.contains(e.target)) close();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && root.classList.contains('is-open')) {
      close();
      trigger.focus();
    }
  });
})();

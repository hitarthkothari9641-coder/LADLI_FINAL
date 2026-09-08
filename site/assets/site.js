(() => {
  // --- Mobile & Tablet Navigation Drawer Controller ---
  function initMobileNav() {
    const menuToggle = document.querySelector('.menu-toggle');
    const nav = document.querySelector('.nav');
    if (!menuToggle || !nav) return;

    // Create backdrop overlay if it doesn't already exist
    let backdrop = document.querySelector('.nav-backdrop');
    if (!backdrop) {
      backdrop = document.createElement('div');
      backdrop.className = 'nav-backdrop';
      document.body.appendChild(backdrop);
    }

    function openMenu() {
      menuToggle.setAttribute('aria-expanded', 'true');
      menuToggle.classList.add('is-active');
      nav.classList.add('is-open');
      backdrop.classList.add('is-visible');
      document.body.classList.add('menu-open');
    }

    function closeMenu() {
      menuToggle.setAttribute('aria-expanded', 'false');
      menuToggle.classList.remove('is-active');
      nav.classList.remove('is-open');
      backdrop.classList.remove('is-visible');
      document.body.classList.remove('menu-open');
      document.querySelectorAll('.nav-item.is-open').forEach(item => item.classList.remove('is-open'));
    }

    menuToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = nav.classList.contains('is-open');
      if (isOpen) {
        closeMenu();
      } else {
        openMenu();
      }
    });

    backdrop.addEventListener('click', closeMenu);

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && nav.classList.contains('is-open')) {
        closeMenu();
      }
    });

    // Unified event delegation on nav
    nav.addEventListener('click', (e) => {
      e.stopPropagation();

      // Check if clicking the dropdown parent link or header area (e.g. Services)
      const navItem = e.target.closest('.nav-item');
      if (navItem && !e.target.closest('.mega')) {
        const isMobile = window.innerWidth <= 1024;
        if (isMobile) {
          e.preventDefault();
          e.stopPropagation();
          const wasOpen = navItem.classList.contains('is-open');
          document.querySelectorAll('.nav-item.is-open').forEach(other => {
            if (other !== navItem) other.classList.remove('is-open');
          });
          navItem.classList.toggle('is-open', !wasOpen);
          return;
        }
      }

      // If clicking any actual navigation link (e.g. Home, About Us, or a link inside .mega)
      const link = e.target.closest('a');
      if (link) {
        if (window.innerWidth <= 1024) {
          closeMenu();
        }
      }
    });

    // Close dropdowns on desktop when clicking outside
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.nav-item') && !e.target.closest('.menu-toggle')) {
        document.querySelectorAll('.nav-item.is-open').forEach(item => item.classList.remove('is-open'));
      }
    });

    // Close mobile nav automatically if window is resized above tablet breakpoint
    window.addEventListener('resize', () => {
      if (window.innerWidth > 1024 && nav.classList.contains('is-open')) {
        closeMenu();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMobileNav);
  } else {
    initMobileNav();
  }

  document.querySelectorAll('[data-year]').forEach(n => n.textContent = new Date().getFullYear());

  // --- Form Validation & Loading State ---
  function initForms() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
      form.addEventListener('submit', (e) => {
        let isValid = true;
        
        // Basic validation
        const requiredInputs = form.querySelectorAll('[required]');
        requiredInputs.forEach(input => {
          // Clear old error
          const oldError = input.parentNode.querySelector('.inline-error');
          if (oldError) oldError.remove();
          input.classList.remove('has-error');

          if (!input.value.trim()) {
            isValid = false;
            input.classList.add('has-error');
            const errorMsg = document.createElement('span');
            errorMsg.className = 'inline-error';
            errorMsg.textContent = 'This field is required.';
            errorMsg.style.color = '#d32f2f';
            errorMsg.style.fontSize = '12px';
            errorMsg.style.marginTop = '4px';
            errorMsg.style.display = 'block';
            input.parentNode.appendChild(errorMsg);
          }
        });

        if (!isValid) {
          e.preventDefault();
        } else {
          // Add loading state
          const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
          if (submitBtn) {
            submitBtn.classList.add('is-loading');
            submitBtn.disabled = true;
          }
        }
      });

      // Clear errors on input
      form.addEventListener('input', (e) => {
        if (e.target.classList.contains('has-error')) {
          e.target.classList.remove('has-error');
          const error = e.target.parentNode.querySelector('.inline-error');
          if (error) error.remove();
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initForms);
  } else {
    initForms();
  }

  // --- Visitor Management: render the running visitor count ----------------
  // Semantics: the badge shows the total number of UNIQUE VISITORS —
  // distinct browsers/devices — not sessions, tabs, or page views.
  // Identification is persistent: each browser gets one random id
  // (crypto.randomUUID()) stored in localStorage ("ladli_visitor_id"),
  // and the server additionally pins the very same id in an HttpOnly
  // cookie. On every page load the id is reported to the backend, which
  // increments the lifetime total only the FIRST time it ever sees that
  // id — refreshes, new tabs and return visits from the same browser are
  // never recounted. The server prefers its own cookie over anything the
  // page posts, so the counter cannot be inflated from client-side code.
  //
  // The server is the single source of truth for whether the badge may be
  // shown at all. The badge is therefore NEVER painted from local storage
  // before the server answers: when the admin switches Visitor Management
  // to "Off" (mode "hidden"), the icon + count must not appear on the
  // website — not even as a one-frame flash while a request is in flight
  // (serverless cold starts can take seconds). Storage is only consulted
  // as an OFFLINE fallback, and only ever replays the LAST known server
  // answer (a visible mode), never a bare number.
  (function initVisitorBadge() {
    const STORAGE_KEY = 'ladli_visitor_id';
    const CACHE_KEY = 'ladli_visitor_count_cache'; // JSON { count, mode } — last server answer
    const HIDDEN_KEY = 'ladli_visitor_count_hidden'; // legacy marker for the "Off" state

    const style = document.createElement('style');
    style.textContent = `
      .visitor-count-badge {
        position: fixed;
        bottom: 24px;
        left: 24px;
        z-index: 90;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border-radius: 999px;
        background: var(--royal, #1f6fe5);
        color: #ffffff;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: .01em;
        white-space: nowrap;
        box-shadow: 0 4px 20px rgba(31, 111, 229, 0.25);
        border: 1px solid rgba(255, 255, 255, 0.15);
        transition: opacity 0.3s ease, bottom 0.3s ease;
      }
      @media (max-width: 768px) {
        .visitor-count-badge {
          bottom: calc(74px + env(safe-area-inset-bottom, 0px));
          left: 12px;
          font-size: 11px;
          padding: 5px 10px;
        }
      }
      .visitor-count-badge .icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: none;
      }
      .visitor-count-badge .icon svg {
        width: 14px;
        height: 14px;
        display: block;
      }
    `;
    document.head.appendChild(style);

    let textSpan = null;
    let badge = null;

    function label(count) {
      return count.toLocaleString() + ' Total Visitors';
    }

    function removeBadge() {
      if (badge && badge.parentNode) badge.parentNode.removeChild(badge);
      badge = null;
      textSpan = null;
    }

    // Persist what the server just told us so the state survives page loads
    // and (as a fallback) brief outages. An "Off" answer clears any stored
    // number and sets HIDDEN_KEY so the badge can never be repainted from
    // storage afterwards.
    function rememberState(mode, count) {
      try {
        if (mode === 'hidden') {
          localStorage.removeItem(CACHE_KEY);
          localStorage.setItem(HIDDEN_KEY, '1');
        } else {
          localStorage.removeItem(HIDDEN_KEY);
          if (typeof count === 'number' && !Number.isNaN(count)) {
            localStorage.setItem(CACHE_KEY, JSON.stringify({ count: count, mode: mode }));
          }
        }
      } catch (e) { /* storage unavailable (private mode, quota, etc.) — non-critical */ }
    }

    // Apply the server's authoritative answer about the visitor counter.
    // Mode "hidden" (the admin's "Off" switch) removes the badge — icon and
    // text together — immediately and keeps it off. Any other mode draws
    // (or updates) the badge with the number the server returned.
    function applyStats(data) {
      if (!data) return;
      if (data.mode === 'hidden') {
        rememberState('hidden', null);
        removeBadge();
        return;
      }
      rememberState(data.mode, data.count);
      renderCount(data.count);
    }

    // Renders (or creates, on first call) the badge. Only ever called with a
    // number that a live server response — or a stored visible-mode answer —
    // has sanctioned, never speculatively before the first server reply.
    function renderCount(count) {
      if (typeof count !== 'number' || Number.isNaN(count)) return;
      const text = label(count);
      if (!badge) {
        badge = document.createElement('div');
        badge.className = 'visitor-count-badge';
        const icon = document.createElement('span');
        icon.className = 'icon';
        icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>';
        icon.setAttribute('aria-hidden', 'true');
        textSpan = document.createElement('span');
        textSpan.textContent = text;
        badge.appendChild(icon);
        badge.appendChild(textSpan);
        document.body.appendChild(badge);
      } else {
        textSpan.textContent = text;
      }
    }

    // Offline / server-unreachable fallback. This replays ONLY the last
    // answer the server actually gave: a stored "visible" answer repaints
    // its cached number; an "Off" answer (or no stored answer at all) leaves
    // the badge hidden. There is no path that paints the icon from a bare
    // cached count, so a counter switched Off can never flash back.
    function renderCachedIfVisible() {
      try {
        if (localStorage.getItem(HIDDEN_KEY) === '1') return;
        const raw = localStorage.getItem(CACHE_KEY);
        if (!raw) return;
        const cached = JSON.parse(raw);
        if (cached && (cached.mode === 'auto' || cached.mode === 'manual') && typeof cached.count === 'number') {
          renderCount(cached.count);
        }
      } catch (e) { /* missing or legacy cache — stay hidden until the server answers */ }
    }

    let visitorId = null;
    try {
      // localStorage (not sessionStorage) is deliberate: the id must be
      // PERSISTENT so the same browser is recognized across tabs, page
      // views, restarts and return visits, and is only ever counted once.
      visitorId = localStorage.getItem(STORAGE_KEY);
      if (!visitorId) {
        visitorId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
          : 'visitor-' + Date.now() + '-' + Math.random().toString(16).slice(2);
        localStorage.setItem(STORAGE_KEY, visitorId);
      }
    } catch (e) {
      // No localStorage available (private mode, blocked storage). Send an
      // empty id — the backend then identifies this browser purely via its
      // HttpOnly cookie (or mints a fresh id server-side on first contact).
      visitorId = '';
    }

    // Report this page load. The backend deduplicates: it only increments
    // the lifetime total the first time it ever sees this browser (by
    // HttpOnly cookie first, then the posted id), so refreshes, extra tabs
    // and repeat visits never inflate the count.
    function queryCountFallback() {
      fetch('/api/visitor-count', { cache: 'no-store', credentials: 'same-origin' })
        .then(res => (res.ok ? res.json() : null))
        .then(data => {
          if (data) applyStats(data);
          else renderCachedIfVisible();
        })
        .catch(renderCachedIfVisible);
    }

    fetch('/api/visitor-register', {
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ visitor_id: visitorId }),
    })
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (data && data.ok) {
          applyStats(data);
          return;
        }
        // Registration failed (rate-limited, transient error…) — try the
        // read-only endpoint so the badge still gets a live answer.
        queryCountFallback();
      })
      .catch(queryCountFallback);

    // Keep checking while the page stays open so that a counter the admin
    // switches Off disappears from ALREADY-OPEN pages too — not only on the
    // next page load. Also re-check the moment the tab regains focus (the
    // typical way an admin returns to the public site after flipping the
    // switch). Failing checks leave the current state untouched.
    function pollCount() {
      fetch('/api/visitor-count', { cache: 'no-store', credentials: 'same-origin' })
        .then(res => (res.ok ? res.json() : null))
        .then(data => { if (data) applyStats(data); })
        .catch(() => { /* transient — keep current state */ });
    }
    setInterval(pollCount, 10000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') pollCount();
    });
    window.addEventListener('focus', pollCount);
  })();
})();

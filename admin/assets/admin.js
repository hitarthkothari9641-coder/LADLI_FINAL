/* =========================================================
   LADLI Admin Portal — shared helpers
   ========================================================= */

const Admin = (() => {
  let csrfToken = null;

  async function getCsrfToken() {
    if (csrfToken) return csrfToken;
    try {
      const res = await fetch('/api/admin/csrf-token', { credentials: 'same-origin' });
      const data = await res.json();
      csrfToken = data.csrf_token;
      return csrfToken;
    } catch(e) {
      return null;
    }
  }

  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    
    // Add X-CSRF-Token for state-changing requests
    if (options.method && options.method.toUpperCase() !== 'GET' && options.method.toUpperCase() !== 'HEAD') {
      const token = await getCsrfToken();
      if (token) {
        headers['X-CSRF-Token'] = token;
      }
    }

    const res = await fetch(path, {
      headers,
      credentials: 'same-origin',
      ...options,
    });

    if (res.status === 401) {
      window.location.href = '/admin/login';
      throw new Error('Not authenticated');
    }
    
    let body = null;
    try { body = await res.json(); } catch (e) { /* no body */ }
    
    if (res.status === 403 && body && body.must_change_password) {
      if (!/\/admin\/settings/.test(window.location.pathname)) {
        window.location.href = '/admin/settings';
      }
      throw new Error('Password change required.');
    }

    if (!res.ok) {
      throw new Error((body && body.error) || 'Request failed');
    }
    return body;
  }

  async function requireAuth() {
    try {
      const res = await fetch('/api/admin/me', { credentials: 'same-origin' });
      const data = await res.json();
      if (!data.logged_in) {
        window.location.href = '/admin/login';
        return null;
      }
      if (data.must_change_password && !/\/admin\/settings/.test(window.location.pathname)) {
        window.location.href = '/admin/settings';
        return null;
      }
      if (!data.security_setup_completed && !/\/admin\/setup-security/.test(window.location.pathname)) {
        window.location.href = '/admin/setup-security';
        return null;
      }
      return data;
    } catch (e) {
      window.location.href = '/admin/login';
      return null;
    }
  }

  function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function timeAgo(iso) {
    if (!iso) return '';
    const then = new Date(iso + 'Z').getTime();
    const diff = Math.max(0, Date.now() - then);
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  }

  function wireLogout(el) {
    if (!el) return;
    el.addEventListener('click', async (e) => {
      e.preventDefault();
      try { await api('/api/admin/logout', { method: 'POST' }); } catch (err) { /* ignore */ }
      window.location.href = '/admin/login';
    });
  }

  function initSidebar() {
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    const backdrop = document.querySelector('.sidebar-backdrop');
    if (toggle && sidebar) {
        toggle.addEventListener('click', () => {
            sidebar.classList.toggle('is-open');
            if (backdrop) backdrop.classList.toggle('is-visible');
            document.body.classList.toggle('sidebar-open');
        });
        if (backdrop) {
            backdrop.addEventListener('click', () => {
                sidebar.classList.remove('is-open');
                backdrop.classList.remove('is-visible');
                document.body.classList.remove('sidebar-open');
            });
        }
    }
  }

  function wirePasswordToggles() {
    document.querySelectorAll('.password-field').forEach((wrapper) => {
      const input = wrapper.querySelector('input');
      const btn = wrapper.querySelector('.password-toggle');
      if (!input || !btn) return;
      btn.addEventListener('click', () => {
        const showing = input.type === 'text';
        input.type = showing ? 'password' : 'text';
        btn.classList.toggle('is-visible', !showing);
        btn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
        input.focus();
      });
    });
  }

  return { 
    api, 
    requireAuth, 
    escapeHtml, 
    timeAgo, 
    wireLogout, 
    initSidebar,
    wirePasswordToggles,
    getCsrfToken
  };
})();

/* Micro-interactions */
(function () {
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  function wireRipples() {
    document.addEventListener('pointerdown', function (e) {
      if (reduceMotion) return;
      var btn = e.target.closest && e.target.closest('.btn');
      if (!btn) return;

      var rect = btn.getBoundingClientRect();
      var ripple = document.createElement('span');
      var size = Math.max(rect.width, rect.height) * 1.4;

      ripple.setAttribute('aria-hidden', 'true');
      ripple.style.position = 'absolute';
      ripple.style.left = (e.clientX - rect.left - size / 2) + 'px';
      ripple.style.top = (e.clientY - rect.top - size / 2) + 'px';
      ripple.style.width = size + 'px';
      ripple.style.height = size + 'px';
      ripple.style.borderRadius = '50%';
      ripple.style.pointerEvents = 'none';
      ripple.style.background = 'radial-gradient(circle, rgba(255,255,255,0.55), rgba(255,255,255,0) 70%)';
      ripple.style.transform = 'scale(0)';
      ripple.style.opacity = '0.9';
      ripple.style.transition = 'transform 550ms cubic-bezier(0.23,1,0.32,1), opacity 550ms ease';

      var prevPosition = getComputedStyle(btn).position;
      if (prevPosition === 'static') btn.style.position = 'relative';
      btn.appendChild(ripple);

      requestAnimationFrame(function () {
        ripple.style.transform = 'scale(1)';
        ripple.style.opacity = '0';
      });

      setTimeout(function () {
        if (ripple.parentNode) ripple.parentNode.removeChild(ripple);
      }, 600);
    }, { passive: true });
  }

  function wireStatValuePulses() {
    var targets = document.querySelectorAll('.stat-value');
    if (!targets.length || !window.MutationObserver) return;

    targets.forEach(function (el) {
      var lastText = el.textContent;
      var observer = new MutationObserver(function () {
        if (el.textContent === lastText) return;
        lastText = el.textContent;
        if (reduceMotion) return;
        el.classList.remove('is-updated');
        void el.offsetWidth;
        el.classList.add('is-updated');
      });
      observer.observe(el, { characterData: true, childList: true, subtree: true });
    });
  }

  function wireCardTilt() {
    if (reduceMotion || !window.matchMedia || !window.matchMedia('(hover: hover)').matches) return;

    document.addEventListener('pointermove', function (e) {
      var card = e.target.closest && e.target.closest('.doc-card');
      if (!card) return;
      var rect = card.getBoundingClientRect();
      var px = (e.clientX - rect.left) / rect.width - 0.5;
      var py = (e.clientY - rect.top) / rect.height - 0.5;
      card.style.transform = 'translateY(-4px) rotateX(' + (py * -4).toFixed(2) + 'deg) rotateY(' + (px * 4).toFixed(2) + 'deg)';
    }, { passive: true });

    document.addEventListener('pointerleave', function (e) {
      var card = e.target.closest && e.target.closest('.doc-card');
      if (!card) return;
      card.style.transform = '';
    }, true);
  }

  ready(function () {
    wireRipples();
    wireStatValuePulses();
    wireCardTilt();
  });
})();

/**
 * HA Companion — Toast Notification System
 * 
 * Injected into the main window as a persistent overlay.
 * Shows rich popup toasts with priority, actions, and auto-dismiss.
 * 
 * Communicates via IPC:
 *   - haCompanion.showToast({ title, message, priority, icon, sound, duration, actions })
 *   - haCompanion.dismissToast(id)
 * 
 * Plays sounds via Web Audio API or delegates to main process for pw-play.
 */

(function () {
  if (window.__haToastLoaded) return;
  window.__haToastLoaded = true;

  // ── Icon map ──
  const PRIORITY_ICONS = {
    urgent: '🚨',
    high: '⚠️',
    default: '🔔',
    low: '💬',
    min: '📌',
  };

  // ── Inject CSS ──
  const style = document.createElement('link');
  style.rel = 'stylesheet';
  // We inline the CSS since we inject it
  const css = document.createElement('style');
  css.textContent = `{{TOAST_CSS}}`;
  document.head.appendChild(css);

  // ── Create container ──
  let container = document.getElementById('ha-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'ha-toast-container';
    document.body.appendChild(container);
  }

  // ── State ──
  const toasts = new Map(); // id -> { element, timer, data }
  let toastCounter = 0;
  const MAX_TOASTS = 3;

  // ── Default durations by priority ──
  const PRIORITY_DURATION = {
    urgent: 0,      // no auto-dismiss
    high: 10000,
    default: 6000,
    low: 5000,
    min: 4000,
  };

  // ── Create toast element ──
  function createToastElement(data) {
    const priority = data.priority || 'default';
    const icon = data.icon || PRIORITY_ICONS[priority] || PRIORITY_ICONS.default;
    const duration = data.duration != null ? data.duration : PRIORITY_DURATION[priority];
    const now = new Date();
    const timeStr = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0');

    const el = document.createElement('div');
    el.className = 'ha-toast';
    el.dataset.priority = priority;
    el.dataset.id = data.id;

    // Sanitize
    const safeTitle = (data.title || '').replace(/</g, '&lt;');
    const safeMsg = (data.message || '').replace(/</g, '&lt;');

    // Actions HTML
    let actionsHtml = '';
    if (data.actions && data.actions.length > 0) {
      actionsHtml = '<div class="ha-toast-actions">';
      for (const action of data.actions) {
        const safeAction = (action.title || action.action || '').replace(/"/g, '&quot;');
        const cls = action.primary ? ' primary' : '';
        actionsHtml += `<button class="ha-toast-action${cls}" data-action="${safeAction}">${safeAction}</button>`;
      }
      actionsHtml += '</div>';
    }

    // Progress bar
    const progressHtml = duration > 0 ? `<div class="ha-toast-progress" style="width:100%"></div>` : '';

    el.innerHTML = `
      <div class="ha-toast-icon">${icon}</div>
      <div class="ha-toast-content">
        <div class="ha-toast-title">${safeTitle}</div>
        ${safeMsg ? `<div class="ha-toast-message">${safeMsg}</div>` : ''}
        <div class="ha-toast-time">${timeStr}</div>
        ${actionsHtml}
      </div>
      <button class="ha-toast-close" title="Dismiss">×</button>
      ${progressHtml}
    `;

    return { element: el, duration };
  }

  // ── Show toast ──
  function showToast(data) {
    const id = data.id || ('toast-' + (++toastCounter));
    data.id = id;

    // Remove excess toasts
    while (container.children.length >= MAX_TOASTS) {
      dismissToast(container.children[0].dataset.id, true);
    }

    const { element, duration } = createToastElement({ ...data, id });

    // Event: close button
    element.querySelector('.ha-toast-close').addEventListener('click', (e) => {
      e.stopPropagation();
      dismissToast(id);
    });

    // Event: click on toast body
    element.addEventListener('click', () => {
      window.haCompanion?.onToastClick?.(id);
    });

    // Event: action buttons
    element.querySelectorAll('.ha-toast-action').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        window.haCompanion?.onToastAction?.(id, btn.dataset.action);
        dismissToast(id);
      });
    });

    container.appendChild(element);

    // Animate in (next frame)
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        element.classList.add('show');
      });
    });

    // Auto-dismiss
    let timer = null;
    if (duration > 0) {
      // Animate progress bar
      const progress = element.querySelector('.ha-toast-progress');
      if (progress) {
        progress.style.transitionDuration = duration + 'ms';
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            progress.style.width = '0%';
          });
        });
      }
      timer = setTimeout(() => dismissToast(id), duration);
    }

    toasts.set(id, { element, timer, data });

    // Play sound
    if (data.sound !== false) {
      window.haCompanion?.playNotificationSound?.(data.sound || 'default');
    }
  }

  // ── Dismiss toast ──
  function dismissToast(id, instant = false) {
    const entry = toasts.get(id);
    if (!entry) return;

    if (entry.timer) clearTimeout(entry.timer);

    if (instant) {
      entry.element.remove();
    } else {
      entry.element.classList.remove('show');
      entry.element.classList.add('dismiss');
      setTimeout(() => entry.element.remove(), 400);
    }

    toasts.delete(id);
  }

  // ── Dismiss all ──
  function dismissAll() {
    for (const id of toasts.keys()) {
      dismissToast(id);
    }
  }

  // ── Expose to window ──
  window.__haToast = {
    show: showToast,
    dismiss: dismissToast,
    dismissAll,
  };

  console.log('[HA Toast] Overlay ready');
})();

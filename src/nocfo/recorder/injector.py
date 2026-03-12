"""JavaScript injection for recording user interactions."""

import structlog
from playwright.sync_api import Page

logger = structlog.get_logger()

# JS for the main frame: sets up the recording indicator, event listeners,
# and a postMessage listener to receive events relayed from iframes.
RECORDER_JS_MAIN = """
(() => {
    if (window.__nocfo_recorder_active) return;
    window.__nocfo_recorder_active = true;

    // Recording indicator (main frame only)
    if (window === window.top) {
        const dot = document.createElement('div');
        dot.id = '__nocfo_record_indicator';
        dot.style.cssText = [
            'position:fixed', 'top:8px', 'right:8px',
            'width:12px', 'height:12px',
            'background:red', 'border-radius:50%',
            'z-index:999999',
            'box-shadow:0 0 4px rgba(255,0,0,0.5)',
            'animation:__nocfo_pulse 1.5s infinite',
        ].join(';');
        const style = document.createElement('style');
        style.textContent = '@keyframes __nocfo_pulse{0%,100%{opacity:1}50%{opacity:0.4}}';
        document.head.appendChild(style);
        document.body.appendChild(dot);

        // Listen for events relayed from iframes via postMessage
        window.addEventListener('message', (e) => {
            if (!e.data || !e.data.__nocfo_event) return;
            if (typeof window.__nocfo_record_event !== 'function') return;
            window.__nocfo_record_event(e.data.__nocfo_event);
        });
    }

    function getCssPath(el) {
        const parts = [];
        let current = el;
        while (current && current !== document.body && current !== document.documentElement) {
            let selector = current.tagName.toLowerCase();
            if (current.id) {
                selector += '#' + CSS.escape(current.id);
                parts.unshift(selector);
                break;
            }
            const parent = current.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(
                    c => c.tagName === current.tagName
                );
                if (siblings.length > 1) {
                    const idx = siblings.indexOf(current) + 1;
                    selector += ':nth-of-type(' + idx + ')';
                }
            }
            parts.unshift(selector);
            current = current.parentElement;
        }
        return parts.join(' > ');
    }

    function getNthChild(el) {
        const parent = el.parentElement;
        if (!parent) return null;
        const idx = Array.from(parent.children).indexOf(el) + 1;
        const tag = el.tagName.toLowerCase();
        return parent.tagName.toLowerCase() + ' > ' + tag + ':nth-child(' + idx + ')';
    }

    const _containerRe = /\\b(modal|dialog|drawer|popup|overlay)\\b/i;
    const _containerClsRe = /\\b(modal|dialog|drawer|popup|overlay)[^\\s]*/i;

    function _containerResult(sel, role) {
        return { selector: sel, role: role };
    }

    function findContainer(el) {
        let cur = el.parentElement;
        while (cur && cur !== document.body && cur !== document.documentElement) {
            const role = cur.getAttribute('role');
            const isModal = cur.getAttribute('aria-modal') === 'true';
            if (role === 'dialog' || role === 'alertdialog' || isModal) {
                const r = role || 'dialog';
                const tid = cur.getAttribute('data-testid');
                if (tid) return _containerResult('[data-testid="' + tid + '"]', r);
                if (cur.id) return _containerResult('#' + CSS.escape(cur.id), r);
                if (role) return _containerResult('[role="' + role + '"]', r);
                return null;
            }
            const cls = cur.className || '';
            if (typeof cls === 'string' && _containerRe.test(cls)) {
                const tid = cur.getAttribute('data-testid');
                if (tid) return _containerResult('[data-testid="' + tid + '"]', 'container');
                if (cur.id) return _containerResult('#' + CSS.escape(cur.id), 'container');
                const m = cls.match(_containerClsRe);
                if (m) return _containerResult('.' + CSS.escape(m[0]), 'container');
                return null;
            }
            cur = cur.parentElement;
        }
        return null;
    }

    function getScopedCssPath(el, containerEl) {
        const parts = [];
        let current = el;
        while (current && current !== containerEl && current !== document.body) {
            let selector = current.tagName.toLowerCase();
            if (current.id) {
                selector += '#' + CSS.escape(current.id);
                parts.unshift(selector);
                break;
            }
            const parent = current.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(
                    c => c.tagName === current.tagName
                );
                if (siblings.length > 1) {
                    const idx = siblings.indexOf(current) + 1;
                    selector += ':nth-of-type(' + idx + ')';
                }
            }
            parts.unshift(selector);
            current = current.parentElement;
        }
        return parts.join(' > ');
    }

    const _dateRe = /\\d{4}-\\d{2}-\\d{2}/;
    const _currencyRe = /\\d+\\s*(kr|SEK|USD|EUR|\\$|\u20ac|\u00a3)/i;

    function cleanText(el) {
        const raw = (el.innerText || '').trim();
        if (!raw) return null;
        const firstLine = raw.split('\\n')[0].trim();
        if (!firstLine || firstLine.length > 30) return null;
        if (_dateRe.test(firstLine)) return null;
        if (_currencyRe.test(firstLine)) return null;
        return firstLine;
    }

    function getSelectors(el) {
        const ariaLabel = el.getAttribute('aria-label');
        const container = findContainer(el);
        let scopedPath = null;
        if (container) {
            // Walk up to find the actual container element for scoped path
            let cEl = el.parentElement;
            while (cEl && cEl !== document.body) {
                const role = cEl.getAttribute('role');
                const cls = cEl.className || '';
                const isModal = cEl.getAttribute('aria-modal') === 'true';
                const clsMatch = typeof cls === 'string' && _containerRe.test(cls);
                const isContainer = (
                    role === 'dialog' || role === 'alertdialog' ||
                    isModal || clsMatch
                );
                if (isContainer) {
                    scopedPath = container.selector + ' ' + getScopedCssPath(el, cEl);
                    break;
                }
                cEl = cEl.parentElement;
            }
        }
        return {
            css_path: getCssPath(el),
            id: el.id || null,
            data_testid: el.getAttribute('data-testid') || null,
            aria: ariaLabel ? '[aria-label="' + ariaLabel.replace(/"/g, '\\\\"') + '"]' : null,
            text: cleanText(el),
            nth_child: getNthChild(el),
            name: el.getAttribute('name') || null,
            placeholder: el.getAttribute('placeholder') || null,
            container_selector: container ? container.selector : null,
            container_role: container ? container.role : null,
            scoped_css_path: scopedPath,
        };
    }

    // Send event: use exposed function in main frame, postMessage from iframes
    function sendEvent(payloadJson) {
        if (window === window.top && typeof window.__nocfo_record_event === 'function') {
            window.__nocfo_record_event(payloadJson);
        } else if (window !== window.top) {
            try {
                window.top.postMessage({ __nocfo_event: payloadJson }, '*');
            } catch(e) {}
        }
    }

    // Debounce input events
    let inputTimer = null;
    let lastInputTarget = null;
    let lastInputValue = '';

    function flushInput() {
        if (lastInputTarget && lastInputValue !== '') {
            const payload = {
                action: 'fill',
                selectors: getSelectors(lastInputTarget),
                value: lastInputValue,
                url: window.location.href,
                tag: lastInputTarget.tagName.toLowerCase(),
                inner_text: '',
                timestamp: new Date().toISOString(),
            };
            sendEvent(JSON.stringify(payload));
        }
        lastInputTarget = null;
        lastInputValue = '';
    }

    document.addEventListener('input', (e) => {
        clearTimeout(inputTimer);
        lastInputTarget = e.target;
        lastInputValue = e.target.value;
        inputTimer = setTimeout(flushInput, 300);
    }, { capture: true });

    document.addEventListener('click', (e) => {
        // Flush any pending input before recording the click
        if (lastInputTarget && lastInputTarget !== e.target) {
            clearTimeout(inputTimer);
            flushInput();
        }

        const el = e.target.closest(
            'a, button, input, select, label, [role="button"], [onclick]'
        ) || e.target;

        let action = 'click';
        if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio')) {
            action = 'check';
        }

        // Skip text inputs — the input event handler captures those
        const textTypes = ['text', 'email', 'password', 'search', 'tel', 'url', 'number'];
        if (el.tagName === 'INPUT' && textTypes.includes(el.type)) {
            return;
        }
        if (el.tagName === 'TEXTAREA') {
            return;
        }

        const payload = {
            action: action,
            selectors: getSelectors(el),
            value: el.value || null,
            url: window.location.href,
            tag: el.tagName.toLowerCase(),
            inner_text: (el.innerText || '').trim().substring(0, 120),
            timestamp: new Date().toISOString(),
        };
        sendEvent(JSON.stringify(payload));
    }, { capture: true });

    document.addEventListener('change', (e) => {
        const el = e.target;
        if (el.tagName === 'SELECT') {
            const payload = {
                action: 'select',
                selectors: getSelectors(el),
                value: el.value,
                url: window.location.href,
                tag: 'select',
                inner_text: el.options[el.selectedIndex]
                    ? el.options[el.selectedIndex].text
                    : '',
                timestamp: new Date().toISOString(),
            };
            sendEvent(JSON.stringify(payload));
        }
    }, { capture: true });
})();
"""


def inject_recorder(page: Page, callback) -> None:
    """Inject recording JS into the page and set up the event bridge.

    Injects into the main frame and all child frames. Iframe events are
    relayed to the main frame via postMessage.

    Args:
        page: Playwright sync Page instance.
        callback: Function called with event JSON string for each interaction.
    """
    page.expose_function("__nocfo_record_event", callback)
    page.evaluate(RECORDER_JS_MAIN)

    # Inject into existing iframes
    _inject_all_frames(page)

    logger.info("recorder_injected", url=page.url, frames=len(page.frames))


def reinject_js(page: Page) -> None:
    """Re-inject the JS after a full page navigation.

    The exposed function persists across navigations, but the JS context is lost.
    """
    try:
        page.evaluate(RECORDER_JS_MAIN)
        _inject_all_frames(page)
        logger.debug("recorder_reinjected", url=page.url)
    except Exception as e:
        logger.warning("reinject_failed", error=str(e))


def _inject_all_frames(page: Page) -> None:
    """Inject recorder JS into all child frames."""
    for frame in page.frames[1:]:  # Skip main frame (index 0)
        try:
            frame.evaluate(RECORDER_JS_MAIN)
        except Exception:
            pass  # Cross-origin frames may reject evaluation

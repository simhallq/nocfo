"""JavaScript injection for recording user interactions."""

import structlog
from playwright.sync_api import Page

logger = structlog.get_logger()

RECORDER_JS = """
(() => {
    if (window.__nocfo_recorder_active) return;
    window.__nocfo_recorder_active = true;

    // Recording indicator
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

    function getSelectors(el) {
        const ariaLabel = el.getAttribute('aria-label');
        return {
            css_path: getCssPath(el),
            id: el.id || null,
            data_testid: el.getAttribute('data-testid') || null,
            aria: ariaLabel ? '[aria-label="' + ariaLabel.replace(/"/g, '\\\\"') + '"]' : null,
            text: (el.innerText || '').trim().substring(0, 80) || null,
            nth_child: getNthChild(el),
            name: el.getAttribute('name') || null,
            placeholder: el.getAttribute('placeholder') || null,
        };
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
            window.__nocfo_record_event(JSON.stringify(payload));
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
        window.__nocfo_record_event(JSON.stringify(payload));
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
            window.__nocfo_record_event(JSON.stringify(payload));
        }
    }, { capture: true });
})();
"""


def inject_recorder(page: Page, callback) -> None:
    """Inject recording JS into the page and set up the event bridge.

    Args:
        page: Playwright sync Page instance.
        callback: Function called with event JSON string for each interaction.
    """
    page.expose_function("__nocfo_record_event", callback)
    page.evaluate(RECORDER_JS)
    logger.info("recorder_injected", url=page.url)


def reinject_js(page: Page) -> None:
    """Re-inject the JS after a full page navigation.

    The exposed function persists across navigations, but the JS context is lost.
    """
    try:
        page.evaluate(RECORDER_JS)
        logger.debug("recorder_reinjected", url=page.url)
    except Exception as e:
        logger.warning("reinject_failed", error=str(e))

/* v2.5.1 — Accessible searchable course picker; native select is the POST source. */
(() => {
  'use strict';
  document.querySelectorAll('[data-course-picker]').forEach(root => {
    const native = root.querySelector('select[name="offering"]');
    const ui = root.querySelector('[data-course-picker-ui]');
    if (!native || !ui) return;
    const trigger = ui.querySelector('[data-picker-trigger]');
    const popup = ui.querySelector('[data-picker-popup]');
    const search = ui.querySelector('[data-picker-search]');
    const list = ui.querySelector('[data-picker-results]');
    const count = ui.querySelector('[data-picker-count]');
    const empty = ui.querySelector('[data-picker-empty]');
    const title = ui.querySelector('[data-picker-display]');
    const summary = ui.querySelector('[data-picker-summary]');
    const items = Array.from(ui.querySelectorAll('[data-picker-option]'));
    const panel = root.closest('.course-slot-panel');
    const form = native.form;
    if (!trigger || !popup || !search || !list || !count || !empty || !title || !summary || !form) return;

    // If JS does not load, the regular <select> is still visible and required.
    native.required = false;
    native.hidden = true;
    ui.hidden = false;
    let highlightedIndex = -1;

    const visible = () => items.filter(item => !item.hidden);
    const setHighlighted = index => {
      const candidates = visible();
      items.forEach(item => item.classList.remove('is-highlighted'));
      highlightedIndex = candidates.length ? ((index % candidates.length) + candidates.length) % candidates.length : -1;
      const chosen = candidates[highlightedIndex];
      if (chosen) {
        chosen.classList.add('is-highlighted');
        search.setAttribute('aria-activedescendant', chosen.id);
        chosen.scrollIntoView({block:'nearest'});
      } else {
        search.removeAttribute('aria-activedescendant');
      }
    };
    const filter = () => {
      const tokens = search.value.trim().toLocaleLowerCase().split(/\s+/u).filter(Boolean);
      items.forEach(item => {
        const content = (item.dataset.search || item.textContent || '').toLocaleLowerCase();
        item.hidden = !tokens.every(token => content.includes(token));
      });
      const candidates = visible();
      count.textContent = `${candidates.length} of ${items.length} course sections`;
      empty.hidden = candidates.length > 0;
      setHighlighted(candidates.length ? 0 : -1);
    };
    const open = () => {
      popup.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      panel?.classList.add('course-slot-panel--open');
      search.value = '';
      filter();
      search.focus();
    };
    const close = (restoreFocus = false) => {
      popup.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      panel?.classList.remove('course-slot-panel--open');
      if (restoreFocus) trigger.focus();
    };
    const choose = item => {
      native.value = item.dataset.id;
      title.textContent = item.querySelector('.course-picker-title')?.textContent.trim() || 'Selected course';
      summary.textContent = item.querySelector('.course-picker-details')?.textContent.replace(/\s+/g, ' ').trim() || '';
      items.forEach(candidate => candidate.setAttribute('aria-selected', String(candidate === item)));
      trigger.classList.remove('is-invalid');
      close(true);
      native.dispatchEvent(new Event('change', {bubbles:true}));
    };

    trigger.addEventListener('click', () => popup.hidden ? open() : close());
    search.addEventListener('input', filter);
    search.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown') { event.preventDefault(); setHighlighted(highlightedIndex + 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); setHighlighted(highlightedIndex - 1); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const item = visible()[highlightedIndex];
        if (item) choose(item);
      } else if (event.key === 'Escape') { event.preventDefault(); close(true); }
    });
    items.forEach(item => item.addEventListener('click', () => choose(item)));
    document.addEventListener('pointerdown', event => {
      if (!root.contains(event.target) && !popup.hidden) close();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !popup.hidden) { event.preventDefault(); close(true); }
    });
    form.addEventListener('submit', event => {
      if (native.value) return;
      event.preventDefault();
      trigger.classList.add('is-invalid');
      open();
      count.textContent = 'Please select a course section before assigning a lecture.';
    });
    const current = items.find(item => item.dataset.id === native.value);
    if (current) choose(current);
  });
})();


/* v2.5.3 — Reusable, client-side filtering for course cards; no backend changes. */
(() => {
  'use strict';
  document.querySelectorAll('[data-course-list]').forEach(root => {
    const tools = root.querySelector('[data-course-list-tools]');
    const search = root.querySelector('[data-course-list-search]');
    const count = root.querySelector('[data-course-list-count]');
    const empty = root.querySelector('[data-course-list-empty]');
    const entries = Array.from(root.querySelectorAll('[data-course-list-item]'));
    if (!tools || !search || !count || !empty) return;
    tools.hidden = false;
    const filter = () => {
      const tokens = search.value.toLocaleLowerCase().trim().split(/\s+/u).filter(Boolean);
      let shown = 0;
      entries.forEach(entry => {
        const haystack = (entry.dataset.search || entry.textContent || '').toLocaleLowerCase();
        const match = tokens.every(token => haystack.includes(token));
        entry.hidden = !match;
        if (match) shown++;
      });
      count.textContent = `${shown} of ${entries.length} ${entries.length === 1 ? 'item' : 'items'}`;
      empty.hidden = shown > 0 || !entries.length;
    };
    search.addEventListener('input', filter);
    filter();
  });
})();

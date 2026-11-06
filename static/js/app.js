(() => {
  const menu = document.getElementById('openMenu');
  const sidebar = document.getElementById('sidebar');
  if (menu && sidebar) {
    menu.addEventListener('click', () => sidebar.classList.toggle('open'));
    document.addEventListener('click', e => {
      if (!sidebar.contains(e.target) && !menu.contains(e.target)) sidebar.classList.remove('open');
    });
  }
  const copyPassword = document.getElementById('copyTeacherPassword');
  if (copyPassword) copyPassword.addEventListener('click', async () => {
    const password = document.getElementById('newTeacherPassword')?.textContent?.trim();
    if (!password) return;
    try { await navigator.clipboard.writeText(password); copyPassword.textContent = 'Copied'; }
    catch { copyPassword.textContent = 'Select and copy the password above'; }
  });
  const form = document.getElementById('attendanceForm');
  if (!form) return;
  const inputs = [...form.querySelectorAll('.student-present')];
  const master = document.getElementById('masterToggle');
  const masterLabel = document.getElementById('masterLabel');
  const presentEl = document.getElementById('presentCount');
  const absentEl = document.getElementById('absentCount');
  const reviewButton = document.getElementById('reviewAttendance');
  const reviewPanel = document.getElementById('reviewPanel');
  const reviewPresent = document.getElementById('reviewPresent');
  const reviewAbsent = document.getElementById('reviewAbsent');
  function refresh() {
    const present = inputs.filter(x => x.checked).length;
    const total = inputs.length;
    const absent = total - present;
    if (presentEl) presentEl.textContent = String(present);
    if (absentEl) absentEl.textContent = String(absent);
    if (reviewPresent) reviewPresent.textContent = String(present);
    if (reviewAbsent) reviewAbsent.textContent = String(absent);
    if (master) {
      master.classList.toggle('all-present', present === total);
      master.classList.toggle('all-absent', present === 0);
      master.classList.toggle('mixed', present > 0 && present < total);
      master.setAttribute('aria-pressed', String(present === total));
      master.setAttribute('aria-label', present === total ? 'Mark all absent' : 'Mark all present');
    }
    if (masterLabel) masterLabel.textContent = present === total ? 'All present' : present === 0 ? 'All absent' : 'Mixed';
  }
  inputs.forEach(input => input.addEventListener('change', () => {
    if (reviewPanel) reviewPanel.hidden = true;
    if (reviewButton) reviewButton.hidden = false;
    refresh();
  }));
  if (master) master.addEventListener('click', () => {
    if (master.disabled) return;
    const allPresent = inputs.every(x => x.checked);
    inputs.forEach(x => { if (!x.disabled) x.checked = !allPresent; });
    if (reviewPanel) reviewPanel.hidden = true;
    if (reviewButton) reviewButton.hidden = false;
    refresh();
  });
  if (reviewButton && reviewPanel) reviewButton.addEventListener('click', () => {
    refresh(); reviewPanel.hidden = false; reviewButton.hidden = true;
    reviewPanel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  });
  let submitting = false;
  form.addEventListener('submit', e => {
    if (submitting) { e.preventDefault(); return; }
    submitting = true;
    const submit = form.querySelector('button[type="submit"]');
    if (submit) { submit.textContent = 'Saving attendance…'; submit.setAttribute('aria-disabled', 'true'); }
  });
  refresh();
})();

// v2.5: copy temporary password only on the one-time administrator screen.
(() => {
  document.querySelectorAll('[data-confirm]').forEach(button => {
    button.addEventListener('click', event => {
      if (!window.confirm(button.dataset.confirm)) event.preventDefault();
    });
  });
  const copy = document.getElementById('copyTemporaryPassword');
  if (!copy) return;
  copy.addEventListener('click', async () => {
    const el = document.getElementById(copy.dataset.copySource);
    if (!el) return;
    try {
      await navigator.clipboard.writeText(el.textContent.trim());
      copy.textContent = 'Copied';
    } catch (error) {
      copy.textContent = 'Select the password above and copy it';
    }
  });
})();

// v2.6.2 — turn every normal application data table into labelled cards on mobile.
// Labels are derived from the existing desktop headers, so new list screens inherit
// mobile responsiveness without duplicating card markup in every Django template.
(() => {
  function initResponsiveDataTables() {
    document.querySelectorAll('.data-table:not([data-mobile-table="keep"])').forEach(table => {
      if (table.dataset.mobileCardsReady === '1') return;
      table.dataset.mobileCardsReady = '1';

      const headers = [...table.querySelectorAll('thead th')].map((th, index, all) => {
        const text = (th.textContent || '').replace(/\s+/g, ' ').trim();
        if (text) return text;
        return index === all.length - 1 ? 'Actions' : '';
      });

      table.querySelectorAll('tbody tr').forEach(row => {
        const cells = [...row.children].filter(el => el.tagName === 'TD');
        if (!cells.length) return;

        // Colspan rows are empty/info messages and should stay as one full-width card.
        if (cells.length === 1 && Number(cells[0].getAttribute('colspan') || 1) > 1) {
          row.classList.add('mobile-table-empty-row');
          cells[0].dataset.mobileLabel = '';
          return;
        }

        cells.forEach((cell, index) => {
          if (!cell.hasAttribute('data-mobile-label')) {
            cell.dataset.mobileLabel = headers[index] || (index === cells.length - 1 ? 'Actions' : '');
          }

          // Keep every value (including strong + small, badges, forms, etc.) together
          // as one grid item beside its generated mobile label. Without this wrapper,
          // multiple child elements can spill into a second implicit grid row.
          if (!cell.querySelector(':scope > .mobile-card-value')) {
            const value = document.createElement('div');
            value.className = 'mobile-card-value';
            while (cell.firstChild) value.appendChild(cell.firstChild);
            cell.appendChild(value);
          }
        });
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initResponsiveDataTables);
  } else {
    initResponsiveDataTables();
  }
})();

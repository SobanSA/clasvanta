(function () {
  'use strict';

  function normalise(value) {
    return (value || '').toString().toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function initRosterSearch() {
    var input = document.querySelector('[data-roster-search]');
    if (!input) return;
    var rows = Array.prototype.slice.call(document.querySelectorAll('[data-roster-row]'));
    var empty = document.querySelector('[data-roster-empty]');
    var counters = document.querySelectorAll('[data-roster-visible-count]');

    function filter() {
      var q = normalise(input.value);
      var visible = 0;
      rows.forEach(function (row) {
        var hay = normalise(row.getAttribute('data-search') || row.textContent);
        var show = !q || hay.indexOf(q) !== -1;
        row.hidden = !show;
        if (show) visible += 1;
      });
      if (empty) empty.hidden = visible !== 0 || rows.length === 0;
      Array.prototype.forEach.call(counters, function (node) { node.textContent = String(visible); });
    }
    input.addEventListener('input', filter);
  }

  function initStudentLookup() {
    var root = document.querySelector('[data-student-lookup]');
    if (!root) return;
    var input = root.querySelector('[data-student-lookup-search]');
    var results = root.querySelector('[data-student-lookup-results]');
    var options = Array.prototype.slice.call(root.querySelectorAll('[data-student-option]'));
    var empty = root.querySelector('[data-student-lookup-empty]');
    if (!input || !results) return;

    // Search-first behaviour: do not keep the entire student roster open.
    // The result list appears only after the user actually starts typing and
    // collapses again when the search is cleared, Escape is pressed, or focus
    // leaves the lookup. This keeps a selected student's attendance immediately visible.
    function closeResults() {
      results.hidden = true;
      root.classList.remove('is-open');
      input.setAttribute('aria-expanded', 'false');
    }

    function openResults() {
      results.hidden = false;
      root.classList.add('is-open');
      input.setAttribute('aria-expanded', 'true');
    }

    function filter() {
      var q = normalise(input.value);
      if (!q) {
        options.forEach(function (option) { option.hidden = false; });
        if (empty) empty.hidden = true;
        closeResults();
        return;
      }

      var visible = 0;
      options.forEach(function (option) {
        var show = normalise(option.getAttribute('data-search')).indexOf(q) !== -1;
        option.hidden = !show;
        if (show) visible += 1;
      });
      if (empty) empty.hidden = visible !== 0;
      openResults();
    }

    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', 'studentLookupResults');
    results.id = results.id || 'studentLookupResults';
    closeResults();

    input.addEventListener('input', filter);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        closeResults();
        input.blur();
      }
    });
    root.addEventListener('focusout', function () {
      window.setTimeout(function () {
        if (!root.contains(document.activeElement)) closeResults();
      }, 0);
    });
  }

  function initSubjectPicker(select) {
    if (!select || select.dataset.enhancedSubject === '1') return;
    select.dataset.enhancedSubject = '1';
    var wasRequired = select.required;
    select.required = false;
    select.classList.add('subject-search-native');

    var options = Array.prototype.slice.call(select.options).filter(function (o) { return o.value; });
    var widget = document.createElement('div');
    widget.className = 'subject-search-widget';

    var trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'subject-search-trigger';
    trigger.setAttribute('aria-expanded', 'false');
    trigger.innerHTML = '<span class="subject-search-trigger-copy"><strong>Select subject</strong><span>Search by full subject name or code</span></span><span class="subject-search-chevron" aria-hidden="true">⌄</span>';

    var popup = document.createElement('div');
    popup.className = 'subject-search-popup';
    popup.hidden = true;
    popup.innerHTML = '<div class="subject-search-box"><input type="search" autocomplete="off" placeholder="Search subject name or code…"></div><div class="subject-search-results"></div><div class="subject-search-empty" hidden>No subjects match this search.</div>';
    var search = popup.querySelector('input');
    var results = popup.querySelector('.subject-search-results');
    var empty = popup.querySelector('.subject-search-empty');

    function selectedOption() {
      return options.filter(function (o) { return o.value === select.value; })[0] || null;
    }

    function renderTrigger() {
      var selected = selectedOption();
      var strong = trigger.querySelector('strong');
      var small = trigger.querySelector('.subject-search-trigger-copy span');
      if (selected) {
        strong.textContent = selected.getAttribute('data-name') || selected.textContent;
        small.textContent = selected.getAttribute('data-code') || '';
      } else {
        strong.textContent = 'Select subject';
        small.textContent = 'Search by full subject name or code';
      }
    }

    var buttons = options.map(function (option) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'subject-search-option';
      btn.dataset.value = option.value;
      btn.dataset.search = normalise((option.getAttribute('data-name') || '') + ' ' + (option.getAttribute('data-code') || '') + ' ' + option.textContent);
      var title = document.createElement('strong');
      title.textContent = option.getAttribute('data-name') || option.textContent;
      var meta = document.createElement('span');
      meta.textContent = option.getAttribute('data-code') || '';
      btn.appendChild(title); btn.appendChild(meta);
      btn.addEventListener('click', function () {
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        renderTrigger();
        close();
      });
      results.appendChild(btn);
      return btn;
    });

    function filter() {
      var q = normalise(search.value);
      var visible = 0;
      buttons.forEach(function (btn) {
        var show = !q || btn.dataset.search.indexOf(q) !== -1;
        btn.hidden = !show;
        if (show) visible += 1;
      });
      empty.hidden = visible !== 0;
    }
    function open() {
      popup.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      search.value = '';
      filter();
      window.setTimeout(function () { search.focus(); }, 0);
    }
    function close() {
      popup.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    }
    trigger.addEventListener('click', function () { popup.hidden ? open() : close(); });
    search.addEventListener('input', filter);
    if (wasRequired && select.form) {
      select.form.addEventListener('submit', function (event) {
        if (!select.value) {
          event.preventDefault();
          trigger.classList.add('is-invalid');
          open();
        } else {
          trigger.classList.remove('is-invalid');
        }
      });
      select.addEventListener('change', function () { trigger.classList.remove('is-invalid'); });
    }
    document.addEventListener('click', function (event) {
      if (!widget.contains(event.target)) close();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !popup.hidden) { close(); trigger.focus(); }
    });

    select.parentNode.insertBefore(widget, select.nextSibling);
    widget.appendChild(trigger);
    widget.appendChild(popup);
    renderTrigger();
  }

  function initSubjectPickers() {
    Array.prototype.forEach.call(document.querySelectorAll('select[data-searchable-subject]'), initSubjectPicker);
  }

  function initTeacherPicker(select) {
    if (!select || select.dataset.enhancedTeacher === '1') return;
    select.dataset.enhancedTeacher = '1';
    var wasRequired = select.required;
    select.required = false;
    select.classList.add('subject-search-native');

    var options = Array.prototype.slice.call(select.options).filter(function (o) { return o.value; });
    var widget = document.createElement('div');
    widget.className = 'subject-search-widget teacher-search-widget';

    var trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'subject-search-trigger teacher-search-trigger';
    trigger.setAttribute('aria-expanded', 'false');
    trigger.innerHTML = '<span class="subject-search-trigger-copy"><strong>Select teacher</strong><span>Search by teacher name or ID</span></span><span class="subject-search-chevron" aria-hidden="true">⌄</span>';

    var popup = document.createElement('div');
    popup.className = 'subject-search-popup teacher-search-popup';
    popup.hidden = true;
    popup.innerHTML = '<div class="subject-search-box"><input type="search" autocomplete="off" placeholder="Search teacher name or ID…"></div><div class="subject-search-results"></div><div class="subject-search-empty" hidden>No teachers match this search.</div>';
    var search = popup.querySelector('input');
    var results = popup.querySelector('.subject-search-results');
    var empty = popup.querySelector('.subject-search-empty');

    function selectedOption() {
      return options.filter(function (o) { return o.value === select.value; })[0] || null;
    }

    function renderTrigger() {
      var selected = selectedOption();
      var strong = trigger.querySelector('strong');
      var small = trigger.querySelector('.subject-search-trigger-copy span');
      if (selected) {
        strong.textContent = selected.getAttribute('data-name') || selected.textContent;
        var teacherId = selected.getAttribute('data-code') || '';
        small.textContent = teacherId ? 'Teacher ID: ' + teacherId : '';
      } else {
        strong.textContent = 'Select teacher';
        small.textContent = 'Search by teacher name or ID';
      }
    }

    var buttons = options.map(function (option) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'subject-search-option teacher-search-option';
      btn.dataset.value = option.value;
      btn.dataset.search = normalise((option.getAttribute('data-name') || '') + ' ' + (option.getAttribute('data-code') || '') + ' ' + option.textContent);
      var title = document.createElement('strong');
      title.textContent = option.getAttribute('data-name') || option.textContent;
      var meta = document.createElement('span');
      var teacherId = option.getAttribute('data-code') || '';
      meta.textContent = teacherId ? 'Teacher ID: ' + teacherId : '';
      btn.appendChild(title); btn.appendChild(meta);
      btn.addEventListener('click', function () {
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        renderTrigger();
        close();
      });
      results.appendChild(btn);
      return btn;
    });

    function filter() {
      var q = normalise(search.value);
      var visible = 0;
      buttons.forEach(function (btn) {
        var show = !q || btn.dataset.search.indexOf(q) !== -1;
        btn.hidden = !show;
        if (show) visible += 1;
      });
      empty.hidden = visible !== 0;
    }
    function open() {
      popup.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      search.value = '';
      filter();
      window.setTimeout(function () { search.focus(); }, 0);
    }
    function close() {
      popup.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    }
    trigger.addEventListener('click', function () { popup.hidden ? open() : close(); });
    search.addEventListener('input', filter);
    if (wasRequired && select.form) {
      select.form.addEventListener('submit', function (event) {
        if (!select.value) {
          event.preventDefault();
          trigger.classList.add('is-invalid');
          open();
        } else {
          trigger.classList.remove('is-invalid');
        }
      });
      select.addEventListener('change', function () { trigger.classList.remove('is-invalid'); });
    }
    document.addEventListener('click', function (event) {
      if (!widget.contains(event.target)) close();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !popup.hidden) { close(); trigger.focus(); }
    });

    select.parentNode.insertBefore(widget, select.nextSibling);
    widget.appendChild(trigger);
    widget.appendChild(popup);
    renderTrigger();
  }

  function initTeacherPickers() {
    Array.prototype.forEach.call(document.querySelectorAll('select[data-searchable-teacher]'), initTeacherPicker);
  }

  document.addEventListener('DOMContentLoaded', function () {
    initRosterSearch();
    initStudentLookup();
    initSubjectPickers();
    initTeacherPickers();
  });
})();

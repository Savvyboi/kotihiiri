// Small progressive enhancements shared by every page. Everything works without it.
(() => {
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  // A link to #something inside a closed <details> opens it (speeches, folded sections).
  const openHash = () => {
    const el = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (!el) return;
    for (let d = el.closest('details'); d; d = d.parentElement && d.parentElement.closest('details')) d.open = true;
    if (el.tagName === 'DETAILS') el.open = true;
    el.scrollIntoView();
  };
  addEventListener('hashchange', openHash);

  // "Open all / Close all" over the folded sections of one block.
  for (const btn of $$('[data-toggle-all]')) {
    const scope = btn.closest('section') || document;
    const folds = () => $$('details.fold', scope);
    const sync = () => btn.setAttribute('aria-pressed', String(folds().every((d) => d.open)));
    btn.hidden = false;
    sync();
    btn.addEventListener('click', () => {
      const open = btn.getAttribute('aria-pressed') !== 'true';
      folds().forEach((d) => { d.open = open; });
      sync();
    });
    scope.addEventListener('toggle', sync, true);
  }

  // Meeting agenda: search the items, or show only the ones that were voted on.
  for (const tools of $$('[data-agenda-tools]')) {
    const list = tools.parentElement.querySelector('[data-agenda]');
    if (!list) continue;
    const items = $$('.agenda-item', list);
    if (items.length < 6) continue;
    const q = tools.querySelector('[data-agenda-q]');
    const votes = tools.querySelector('[data-agenda-votes]');
    const status = tools.querySelector('[data-agenda-status]');
    const text = items.map((li) => li.textContent.toLocaleLowerCase('fi'));
    const run = () => {
      const words = q.value.toLocaleLowerCase('fi').split(/\s+/).filter(Boolean);
      let n = 0;
      items.forEach((li, i) => {
        const show = (!votes || !votes.checked || li.dataset.votes) && words.every((w) => text[i].includes(w));
        li.hidden = !show;
        if (show) n++;
      });
      const filtered = words.length || (votes && votes.checked);
      status.textContent = !filtered ? '' : n
        ? status.dataset.tpl.replace('{n}', n).replace('{total}', items.length)
        : status.dataset.none;
    };
    tools.hidden = false;
    q.addEventListener('input', run);
    if (votes) votes.addEventListener('change', run);
  }

  // Tables marked data-sortable: header buttons sort the rows (numbers and dates, then text).
  const collator = new Intl.Collator(document.documentElement.lang || 'fi', { numeric: true, sensitivity: 'base' });
  const key = (cell) => {
    if (!cell) return '';
    const raw = (cell.dataset.sort ?? cell.textContent).trim();
    const date = raw.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})/);
    if (date) return Number(date[3] + date[2].padStart(2, '0') + date[1].padStart(2, '0'));
    const num = raw.replace(/[\s %€]/g, '').replace(',', '.').replace(/^[−–]/, '-');
    return num !== '' && !Number.isNaN(Number(num)) ? Number(num) : raw;
  };
  for (const table of $$('table[data-sortable]')) {
    const head = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    const body = table.tBodies[0];
    if (!head || !body || body.rows.length < 3) continue;
    const label = table.dataset.sortable || 'Sort';
    [...head.cells].forEach((th, col) => {
      if (th.hasAttribute('data-nosort') || th.colSpan > 1 || !th.textContent.trim()) return;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sort';
      btn.title = label;
      while (th.firstChild) btn.append(th.firstChild);
      th.append(btn);
      btn.addEventListener('click', () => {
        const now = th.getAttribute('aria-sort');
        const dir = now === 'descending' ? 'ascending' : now === 'ascending' ? 'descending'
          : th.classList.contains('num') ? 'descending' : 'ascending';
        [...head.cells].forEach((c) => c.removeAttribute('aria-sort'));
        th.setAttribute('aria-sort', dir);
        const sign = dir === 'ascending' ? 1 : -1;
        const rows = [...body.rows].map((r, i) => ({ r, i, k: key(r.cells[col]) }));
        rows.sort((a, b) => {
          const x = a.k, y = b.k;
          const c = typeof x === 'number' && typeof y === 'number' ? x - y
            : typeof x === 'number' ? -1 : typeof y === 'number' ? 1 : collator.compare(x, y);
          return c * sign || a.i - b.i;
        });
        body.append(...rows.map((x) => x.r));
      });
    });
  }

  // Tables marked data-filterable="placeholder": a search box above that hides unmatched rows.
  for (const table of $$('table[data-filterable]')) {
    const body = table.tBodies[0];
    if (!body || body.rows.length < 8) continue;
    const input = document.createElement('input');
    input.type = 'search';
    input.className = 'table-filter';
    input.placeholder = input.ariaLabel = table.dataset.filterable;
    input.setAttribute('aria-label', table.dataset.filterable);
    (table.closest('.table-scroll') || table).before(input);
    const rows = [...body.rows];
    const text = rows.map((r) => r.textContent.toLocaleLowerCase('fi'));
    input.addEventListener('input', () => {
      const words = input.value.toLocaleLowerCase('fi').split(/\s+/).filter(Boolean);
      rows.forEach((r, i) => { r.hidden = !words.every((w) => text[i].includes(w)); });
    });
  }

  openHash();
})();

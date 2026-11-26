// Sortable tables: every table of a page (the Markdown tables, `.md-typeset table:not([class])`) sorts by a click on a
// header, or Enter or Space on a focused header: ascending, then descending, then back to the order of the page.
//
// The sorted header gets aria-sort, which the theme turns into its sort icon (Material's tablesort styles). A cell sorts
// by the data-sort attribute of the cell or of an element inside it (the coverage bars of docs_scenarios.coverage_bar),
// else by its text: as numbers when every non-empty cell of the column is one ("81%", "1.5", "-3"), else in natural
// order ("KB-9" before "KB-10", "v1.8.0" before "v1.10.0"). Empty cells ("", "-", "—") stay last in both directions,
// and so does a last row whose first cell reads "Total" (the summaries of the coverage matrix). Tables of fewer than
// two rows, or whose rows do not have one cell per header (colspan), are left as they are.
(function () {
  "use strict";

  const EMPTY = new Set(["", "-", "–", "—"]);
  const TOTAL = /^total$/i;
  const NUMBER = /^[-+]?\d+(?:[.,]\d+)?\s*%?$/;
  const NEXT = { ascending: "descending", descending: null };
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

  function sortKey(cell) {
    if (!cell) return "";
    const holder = cell.hasAttribute("data-sort") ? cell : cell.querySelector("[data-sort]");
    return (holder ? holder.getAttribute("data-sort") : cell.textContent).trim();
  }

  function toNumber(text) {
    return parseFloat(text.replace(",", "."));
  }

  function setup(table) {
    if (table.dataset.e2eSortable) return;
    table.dataset.e2eSortable = "true";
    const head = table.tHead;
    if (!head || !head.rows.length || table.tBodies.length !== 1) return;
    const headers = Array.from(head.rows[head.rows.length - 1].cells);
    const body = table.tBodies[0];
    const all = Array.from(body.rows);
    if (all.some((row) => row.cells.length !== headers.length)) return;
    const last = all[all.length - 1];
    const pinned = last && TOTAL.test(last.cells[0].textContent.trim()) ? [last] : [];
    const original = all.slice(0, all.length - pinned.length);
    if (original.length < 2) return;

    function sort(header, index) {
      const state = header.getAttribute("aria-sort");
      const next = state in NEXT ? NEXT[state] : "ascending";
      headers.forEach((other) => other.removeAttribute("aria-sort"));
      const rows = original.slice();
      if (next) {
        header.setAttribute("aria-sort", next);
        const keys = new Map(rows.map((row) => [row, sortKey(row.cells[index])]));
        const values = Array.from(keys.values()).filter((value) => !EMPTY.has(value));
        const numeric = values.length > 0 && values.every((value) => NUMBER.test(value));
        const direction = next === "ascending" ? 1 : -1;
        rows.sort((a, b) => {
          const [x, y] = [keys.get(a), keys.get(b)];
          if (EMPTY.has(x) || EMPTY.has(y)) return EMPTY.has(x) - EMPTY.has(y);
          return direction * (numeric ? toNumber(x) - toNumber(y) : collator.compare(x, y));
        });
      }
      const fragment = document.createDocumentFragment();
      rows.concat(pinned).forEach((row) => fragment.appendChild(row));
      body.appendChild(fragment);
    }

    headers.forEach((header, index) => {
      header.setAttribute("role", "columnheader");
      header.tabIndex = 0;
      header.addEventListener("click", (event) => {
        if (!event.target.closest("a, button, input, select, summary")) sort(header, index);
      });
      header.addEventListener("keydown", (event) => {
        if (event.target === header && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          sort(header, index);
        }
      });
    });
  }

  function init() {
    document.querySelectorAll(".md-typeset table:not([class])").forEach(setup);
  }

  // navigation.instant replaces the content without reloading the page: document$ emits every page, the first one too
  if (window.document$) window.document$.subscribe(init);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

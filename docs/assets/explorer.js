// Filter and sort controls of the scenario explorer's tables (docs_scenarios.py generates the pages).
//
// A table preceded by <div class="e2e-filter" data-columns="Tier,Domain"> gets a search box (every word must appear in
// the row), one list per named column (a cell holds comma-separated values) and sortable headers. The state lives in
// the query string (?q=repo+secrets&Tier=cli&Tags=regression), so a filtered view can be linked and shared.
(function () {
  "use strict";

  function cellValues(cell) {
    return cell ? cell.textContent.split(",").map((value) => value.trim()).filter(Boolean) : [];
  }

  function nextTable(marker) {
    for (let node = marker.nextElementSibling; node; node = node.nextElementSibling) {
      if (node.classList.contains("e2e-filter")) return null;
      const table = node.matches("table") ? node : node.querySelector("table");
      if (table) return table;
    }
    return null;
  }

  function element(tag, className, attributes) {
    const node = document.createElement(tag);
    node.className = className;
    Object.entries(attributes || {}).forEach(([name, value]) => node.setAttribute(name, value));
    return node;
  }

  function setup(marker) {
    const table = nextTable(marker);
    if (!table || !table.tHead || !table.tBodies.length) return;
    const headers = Array.from(table.tHead.rows[0].cells).map((cell) => cell.textContent.trim());
    const body = table.tBodies[0];
    const rows = Array.from(body.rows);
    const params = new URLSearchParams(window.location.search);

    const controls = element("div", "e2e-filter__controls");
    const search = element("input", "e2e-filter__search", {
      type: "search",
      placeholder: "Filter: id, title, tag, KB-…, version…",
      "aria-label": "Filter the table",
    });
    search.value = params.get("q") || "";
    controls.appendChild(search);

    const selects = (marker.dataset.columns || "")
      .split(",")
      .map((name) => name.trim())
      .filter((name) => headers.includes(name))
      .map((name) => {
        const index = headers.indexOf(name);
        const values = new Set();
        rows.forEach((row) => cellValues(row.cells[index]).forEach((value) => values.add(value)));
        const select = element("select", "e2e-filter__select", { "aria-label": name });
        select.appendChild(new Option(`${name}: all`, ""));
        Array.from(values)
          .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
          .forEach((value) => select.appendChild(new Option(value, value)));
        const wanted = params.get(name);
        if (wanted && values.has(wanted)) select.value = wanted;
        controls.appendChild(select);
        return { name, index, select };
      });

    const count = element("span", "e2e-filter__count", { "aria-live": "polite" });
    controls.appendChild(count);
    marker.appendChild(controls);

    function apply() {
      const terms = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      let shown = 0;
      rows.forEach((row) => {
        const text = row.textContent.toLowerCase();
        const visible =
          terms.every((term) => text.includes(term)) &&
          selects.every(({ index, select }) => !select.value || cellValues(row.cells[index]).includes(select.value));
        row.hidden = !visible;
        if (visible) shown += 1;
      });
      count.textContent = `${shown} / ${rows.length}`;
      const query = new URLSearchParams(window.location.search);
      query.delete("q");
      if (search.value.trim()) query.set("q", search.value.trim());
      selects.forEach(({ name, select }) => (select.value ? query.set(name, select.value) : query.delete(name)));
      const suffix = query.toString();
      window.history.replaceState(null, "", window.location.pathname + (suffix ? `?${suffix}` : "") + window.location.hash);
    }

    search.addEventListener("input", apply);
    selects.forEach(({ select }) => select.addEventListener("change", apply));

    Array.from(table.tHead.rows[0].cells).forEach((header, index) => {
      header.classList.add("e2e-sortable");
      header.setAttribute("title", "Sort");
      let ascending = true;
      header.addEventListener("click", () => {
        const key = (row) => (row.cells[index] ? row.cells[index].textContent.trim() : "");
        const sorted = Array.from(body.rows).sort(
          (a, b) => key(a).localeCompare(key(b), undefined, { numeric: true }) * (ascending ? 1 : -1),
        );
        sorted.forEach((row) => body.appendChild(row));
        ascending = !ascending;
      });
    });

    apply();
  }

  function init() {
    document.querySelectorAll(".e2e-filter").forEach(setup);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

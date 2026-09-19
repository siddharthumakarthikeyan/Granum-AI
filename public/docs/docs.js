/* Documentation behaviour: search, the mobile sidebar, and the "on this page" highlight.
 *
 * The search index (search.json) is fetched once, the first time someone opens search, so
 * a page that is only read costs nothing extra. */

(function () {
  "use strict";

  // ---------- mobile sidebar ----------

  var toggle = document.querySelector("[data-sidebar-toggle]");
  var sidebar = document.getElementById("doc-sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // ---------- on this page ----------

  var links = Array.prototype.slice.call(document.querySelectorAll(".doc-toc a"));
  if (links.length && "IntersectionObserver" in window) {
    var byId = {};
    links.forEach(function (link) { byId[link.getAttribute("href").slice(1)] = link; });
    var seen = [];
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var id = entry.target.id;
        var at = seen.indexOf(id);
        if (entry.isIntersecting && at === -1) seen.push(id);
        if (!entry.isIntersecting && at !== -1) seen.splice(at, 1);
      });
      var order = Object.keys(byId);
      var current = order.filter(function (id) { return seen.indexOf(id) !== -1; })[0];
      links.forEach(function (link) { link.classList.remove("on"); });
      if (current && byId[current]) byId[current].classList.add("on");
    }, { rootMargin: "-80px 0px -70% 0px" });
    Object.keys(byId).forEach(function (id) {
      var heading = document.getElementById(id);
      if (heading) observer.observe(heading);
    });
  }

  // ---------- search ----------

  var panel = document.querySelector("[data-search-panel]");
  var input = document.querySelector("[data-search-input]");
  var results = document.querySelector("[data-search-results]");
  if (!panel || !input || !results) return;

  var index = null;
  var loading = null;
  var active = 0;

  function load() {
    if (index) return Promise.resolve(index);
    if (!loading) {
      loading = fetch("/docs/search.json")
        .then(function (response) { return response.json(); })
        .then(function (data) { index = data; return index; })
        .catch(function () { index = []; return index; });
    }
    return loading;
  }

  function open() {
    load().then(render);
    panel.hidden = false;
    document.body.style.overflow = "hidden";
    input.value = "";
    input.focus();
    render();
  }

  function close() {
    panel.hidden = true;
    document.body.style.overflow = "";
  }

  function score(page, terms) {
    var title = page.title.toLowerCase();
    var headings = page.headings.join(" ").toLowerCase();
    var summary = (page.summary || "").toLowerCase();
    var text = page.text.toLowerCase();
    var total = 0;
    for (var i = 0; i < terms.length; i++) {
      var term = terms[i];
      var hit = 0;
      if (title.indexOf(term) !== -1) hit += title.indexOf(term) === 0 ? 14 : 10;
      if (headings.indexOf(term) !== -1) hit += 5;
      if (summary.indexOf(term) !== -1) hit += 4;
      if (text.indexOf(term) !== -1) hit += 2;
      if (!hit) return 0; // every word must appear somewhere
      total += hit;
    }
    return total;
  }

  function excerpt(page, terms) {
    var text = page.text;
    var at = -1;
    for (var i = 0; i < terms.length && at === -1; i++) at = text.toLowerCase().indexOf(terms[i]);
    if (at === -1) return page.summary || text.slice(0, 120);
    var from = Math.max(0, at - 45);
    return (from ? "…" : "") + text.slice(from, from + 150).trim() + "…";
  }

  function render() {
    var query = input.value.trim().toLowerCase();
    var terms = query.split(/\s+/).filter(Boolean);
    results.innerHTML = "";
    active = 0;
    if (!index) return;
    var rows = index;
    if (terms.length) {
      rows = index
        .map(function (page) { return { page: page, score: score(page, terms) }; })
        .filter(function (row) { return row.score > 0; })
        .sort(function (a, b) { return b.score - a.score; })
        .slice(0, 12)
        .map(function (row) { return row.page; });
    } else {
      rows = index.slice(0, 8);
    }
    if (!rows.length) {
      results.innerHTML = '<li class="doc-search-empty">Nothing matches. Try a word from the app, such as “verify”, “dataset version” or “findings”.</li>';
      return;
    }
    rows.forEach(function (page, i) {
      var item = document.createElement("li");
      if (i === 0) item.className = "on";
      var link = document.createElement("a");
      link.href = page.url;
      link.innerHTML =
        "<em>" + page.section + "</em><strong>" + page.title + "</strong><span>" +
        (terms.length ? excerpt(page, terms) : page.summary) + "</span>";
      item.appendChild(link);
      results.appendChild(item);
    });
  }

  function move(step) {
    var items = results.querySelectorAll("li");
    if (!items.length) return;
    items[active] && items[active].classList.remove("on");
    active = (active + step + items.length) % items.length;
    items[active].classList.add("on");
    items[active].scrollIntoView({ block: "nearest" });
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-search]"), function (button) {
    button.addEventListener("click", open);
  });

  input.addEventListener("input", render);
  input.addEventListener("keydown", function (event) {
    if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
    else if (event.key === "Enter") {
      var link = results.querySelectorAll("li")[active];
      var anchor = link && link.querySelector("a");
      if (anchor) window.location.href = anchor.href;
    }
  });

  panel.addEventListener("click", function (event) {
    if (event.target === panel) close();
  });

  document.addEventListener("keydown", function (event) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (event.key === "Escape" && !panel.hidden) close();
    else if ((event.key === "/" || (event.key === "k" && (event.metaKey || event.ctrlKey))) && panel.hidden && !typing) {
      event.preventDefault();
      open();
    }
  });
})();

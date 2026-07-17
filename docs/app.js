"use strict";
/* Renders the whole page from ./data.json. Nothing here hardcodes an engine
 * name: every view iterates data.engines, so adding a backend to the JSON adds
 * it to every chart, table, column and color automatically. */

// Colors are assigned by engine index, so a new engine gets the next unused hue.
const PALETTE = ["#6ea8fe", "#34d399", "#f59e0b", "#f472b6",
                 "#22d3ee", "#a78bfa", "#fb7185", "#a3e635"];

// ---- small DOM + format helpers ----------------------------------------
function el(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
const fmt3 = (v) => v.toFixed(3);
const fmt2 = (v) => v.toFixed(2);
const signed3 = (v) => (v >= 0 ? "+" : "") + v.toFixed(3);
function fmtBytes(n) {
  if (n === null || n === undefined) return "n/a";
  let v = n;
  for (const u of ["B", "KB", "MB", "GB"]) {
    if (v < 1024) return `${Math.round(v)}${u}`;
    v /= 1024;
  }
  return `${Math.round(v)}TB`;
}
// pkg:ripgrep -> {kind:"pkg", name:"ripgrep"}; opt:a.b -> {kind:"opt", name:"a.b"}
function splitId(id) {
  const i = id.indexOf(":");
  return i < 0 ? { kind: "", name: id } : { kind: id.slice(0, i), name: id.slice(i + 1) };
}

let DATA = null;
let COLOR = new Map(); // engine -> hex

// ---- boot ---------------------------------------------------------------
fetch("./data.json")
  .then((r) => {
    if (!r.ok) throw new Error(`data.json: HTTP ${r.status}`);
    return r.json();
  })
  .then((data) => {
    DATA = data;
    data.engines.forEach((e, i) => COLOR.set(e, PALETTE[i % PALETTE.length]));
    render();
  })
  .catch((err) => {
    document.getElementById("lede").textContent =
      "Failed to load data.json — serve this folder over HTTP (see README). " + err.message;
  });

function render() {
  renderHeader();
  renderRelevance();
  renderLatency();
  renderIndexing();
  renderCategories();
  renderSignificance();
  renderExplorer();
  wireScrollspy();
}

function engColor(e) { return COLOR.get(e) || "#888"; }
function engDot(e) { return el("span", { class: "eng-dot", style: `background:${engColor(e)}` }); }

// ---- header -------------------------------------------------------------
function renderHeader() {
  const m = DATA.meta;
  const when = new Date(m.generated_at);
  const stamp = isNaN(when) ? m.generated_at
    : when.toISOString().replace("T", " ").slice(0, 16) + " UTC";
  document.getElementById("lede").innerHTML =
    `${DATA.engines.length} search backends over <strong>${m.doc_count.toLocaleString()}</strong> ` +
    `NixOS package &amp; option documents, ${DATA.queries.length} labeled queries. ` +
    `Generated ${stamp}.`;

  const legend = document.getElementById("legend");
  legend.replaceChildren(...DATA.engines.map((e) => {
    const ver = DATA.meta.versions[e];
    return el("span", { class: "item" },
      el("span", { class: "swatch", style: `background:${engColor(e)}` }),
      el("span", {}, e),
      ver ? el("span", { class: "ver" }, ver) : null);
  }));

  const f = document.getElementById("footer-meta");
  f.innerHTML = `Rendered entirely from <code>docs/data.json</code>. ` +
    `Regenerate with <code>python scripts/build_site.py</code> after an eval run.`;
}

// ---- grouped bars -------------------------------------------------------
// groups: [{label, bars:[{engine, value}]}]; scaled to `max`; fmt(value)->text
function groupedBars(container, groups, max, fmt) {
  container.replaceChildren(...groups.map((g) =>
    el("div", { class: "bar-group" },
      el("div", { class: "bg-label" }, g.label),
      ...g.bars.map((b) =>
        el("div", { class: "bar-row" },
          el("span", { class: "bar-name" }, engDot(b.engine), b.engine),
          el("div", { class: "bar-track" },
            el("div", { class: "bar-fill", style:
              `width:${max > 0 ? (b.value / max) * 100 : 0}%;background:${engColor(b.engine)}` })),
          el("span", { class: "bar-val" }, fmt(b.value)))))));
}

// header row of engine names with color dots
function engHeader(first) {
  return el("tr", {}, el("th", {}, first),
    ...DATA.engines.map((e) => el("th", {}, engDot(e), e)));
}

// ---- relevance ----------------------------------------------------------
function renderRelevance() {
  const metrics = ["success@10", "mrr", "recall@10"];
  const groups = metrics.map((mt) => ({
    label: mt,
    bars: DATA.engines.map((e) => ({ engine: e, value: DATA.summaries[e][mt] })),
  }));
  groupedBars(document.getElementById("chart-relevance"), groups, 1, fmt3);

  const table = document.getElementById("table-relevance");
  table.replaceChildren(
    el("thead", {}, engHeader("metric")),
    el("tbody", {}, ...metrics.map((mt) =>
      el("tr", {}, el("td", { class: "metric" }, mt),
        ...DATA.engines.map((e) => el("td", { class: "num" }, fmt3(DATA.summaries[e][mt])))))));
}

// ---- latency ------------------------------------------------------------
function renderLatency() {
  const stats = ["p50", "p95", "p99", "mean", "max"];
  const all = DATA.engines.flatMap((e) => stats.map((s) => DATA.summaries[e].latency[s]));
  const max = Math.max(...all);
  const groups = stats.map((s) => ({
    label: s,
    bars: DATA.engines.map((e) => ({ engine: e, value: DATA.summaries[e].latency[s] })),
  }));
  groupedBars(document.getElementById("chart-latency"), groups, max, fmt2);

  const table = document.getElementById("table-latency");
  table.replaceChildren(
    el("thead", {}, engHeader("stat")),
    el("tbody", {}, ...stats.map((s) =>
      el("tr", {}, el("td", { class: "stat" }, s),
        ...DATA.engines.map((e) => el("td", { class: "num" }, fmt2(DATA.summaries[e].latency[s])))))));
}

// ---- indexing -----------------------------------------------------------
function renderIndexing() {
  const idx = (e) => DATA.summaries[e].index;
  const rows = [
    ["docs", (e) => idx(e).doc_count.toLocaleString()],
    ["index time (s)", (e) => fmt2(idx(e).seconds)],
    ["footprint", (e) => {
      const b = fmtBytes(idx(e).index_bytes);
      const k = idx(e).footprint_kind;
      return k && b !== "n/a" ? `${b} (${k})` : b;
    }],
  ];
  const table = document.getElementById("table-indexing");
  table.replaceChildren(
    el("thead", {}, engHeader("metric")),
    el("tbody", {}, ...rows.map(([label, cell]) =>
      el("tr", {}, el("td", { class: "metric" }, label),
        ...DATA.engines.map((e) => el("td", { class: "num" }, cell(e)))))));

  document.getElementById("footprint-note").textContent =
    "Footprint is each engine's native measure and is not directly comparable across " +
    "engines: on-disk index store vs. in-RAM process RSS measure different quantities.";
}

// ---- categories heatmap -------------------------------------------------
let CAT_METRIC = "success@10";
function renderCategories() {
  const toggle = document.getElementById("cat-toggle");
  const mk = (mt, label) => el("button", {
    class: mt === CAT_METRIC ? "active" : "",
    onclick: () => { CAT_METRIC = mt; renderCategories(); },
  }, label);
  toggle.replaceChildren(mk("success@10", "Success@10"), mk("mrr", "MRR"));
  drawHeatmap();
}
function drawHeatmap() {
  // Union categories across engines (engine-agnostic, like report.py).
  const cats = [...new Set(DATA.engines.flatMap((e) =>
    Object.keys(DATA.summaries[e].by_category)))].sort();

  const cell = (v) => {
    if (v === null || v === undefined) {
      return el("td", { class: "heat-cell", style: "background:var(--surface-2);color:var(--muted)" }, "-");
    }
    const bg = `rgba(52,211,153,${(0.10 + 0.9 * v).toFixed(3)})`;
    const fg = v > 0.55 ? "#07120d" : "#e6e9ef";
    return el("td", { class: "heat-cell", style: `background:${bg};color:${fg}` }, fmt3(v));
  };

  const table = el("table", {},
    el("thead", {}, engHeader("category")),
    el("tbody", {}, ...cats.map((c) =>
      el("tr", {}, el("td", {}, c),
        ...DATA.engines.map((e) => {
          const bc = DATA.summaries[e].by_category[c];
          return cell(bc ? bc[CAT_METRIC] : null);
        })))));
  document.getElementById("heatmap").replaceChildren(table);
}

// ---- significance -------------------------------------------------------
function renderSignificance() {
  const host = document.getElementById("sig-panels");
  if (!DATA.significance.length) {
    host.replaceChildren(el("p", { class: "note" },
      "Significance needs at least two engines to compare."));
    return;
  }
  host.replaceChildren(...DATA.significance.map(sigPanel));
}
function sigPanel(pair) {
  const rows = pair.rows;
  // Symmetric axis centered on 0; pad so endpoints aren't flush to the edge.
  const reach = Math.max(1e-6, ...rows.flatMap((r) => [Math.abs(r.lo), Math.abs(r.hi), Math.abs(r.mean_diff)]));
  const axis = reach * 1.08;
  const pct = (x) => ((x + axis) / (2 * axis)) * 100;

  const panel = el("div", { class: "sig-panel" },
    el("h3", {}, el("span", {}, engDot(pair.a), pair.a),
      ` \u2212 `, engDot(pair.b), pair.b,
      el("span", { class: "fav" }, "  positive favors " + pair.a)));

  for (const r of rows) {
    const lo = pct(r.lo), hi = pct(r.hi), dot = pct(r.mean_diff);
    panel.append(el("div", { class: "sig-row" + (r.significant ? " is-sig" : "") },
      el("span", { class: "sig-label" }, r.group),
      el("div", { class: "sig-track" },
        el("div", { class: "sig-zero", style: `left:${pct(0)}%` }),
        el("div", { class: "sig-ci", style: `left:${Math.min(lo, hi)}%;width:${Math.abs(hi - lo)}%` }),
        el("div", { class: "sig-dot", style: `left:${dot}%` })),
      el("span", { class: "sig-num" },
        `${signed3(r.mean_diff)} `,
        el("span", {}, `[${signed3(r.lo)}, ${signed3(r.hi)}]`),
        r.significant ? el("span", { class: "star" }, " \u2217") : null)));
  }
  return panel;
}

// ---- query explorer -----------------------------------------------------
const EX = { text: "", cats: new Set(), selected: null };
function renderExplorer() {
  const chips = document.getElementById("cat-chips");
  const cats = [...new Set(DATA.queries.map((q) => q.category))].sort();
  chips.replaceChildren(...cats.map((c) =>
    el("span", {
      class: "chip" + (EX.cats.has(c) ? " on" : ""),
      onclick: () => { EX.cats.has(c) ? EX.cats.delete(c) : EX.cats.add(c); renderExplorer(); },
    }, c)));

  const input = document.getElementById("q-filter");
  if (input.value !== EX.text) input.value = EX.text;
  input.oninput = (e) => { EX.text = e.target.value; renderList(); };

  renderList();
  renderDetail();
}
function filteredQueries() {
  const t = EX.text.trim().toLowerCase();
  return DATA.queries.filter((q) => {
    if (EX.cats.size && !EX.cats.has(q.category)) return false;
    if (!t) return true;
    return q.q.toLowerCase().includes(t) || q.id.toLowerCase().includes(t);
  });
}
function renderList() {
  const qs = filteredQueries();
  document.getElementById("q-count").textContent =
    `${qs.length} of ${DATA.queries.length} queries`;
  const list = document.getElementById("q-list");
  list.replaceChildren(...qs.map((q) =>
    el("li", {
      class: q.id === EX.selected ? "sel" : "",
      onclick: () => { EX.selected = q.id; renderList(); renderDetail(); },
    },
      el("span", { class: "qid" }, q.id),
      el("span", { class: "qtext" }, q.q),
      el("span", { class: "cat-badge" }, q.category))));
}
function renderDetail() {
  const host = document.getElementById("q-detail");
  const q = DATA.queries.find((x) => x.id === EX.selected);
  if (!q) {
    host.replaceChildren(el("p", { class: "empty" },
      "Select a query to see how each engine ranked it."));
    return;
  }
  const relSet = new Set(q.relevant);

  const head = el("div", { class: "q-head" },
    el("div", { class: "q-str" }, q.q),
    el("div", { class: "q-meta" },
      el("span", {}, "id ", q.id),
      el("span", {}, "category ", q.category),
      el("span", {}, `${q.relevant.length} relevant label${q.relevant.length === 1 ? "" : "s"}`)),
    el("div", { class: "rel-labels" }, ...q.relevant.map((id) => {
      const { name } = splitId(id);
      return el("span", { class: "rel-chip", title: id }, name);
    })));

  const cols = el("div", { class: "cols", style: `--ncols:${DATA.engines.length}` },
    ...DATA.engines.map((e) => engineColumn(e, q, relSet)));

  host.replaceChildren(head, cols);
}
function engineColumn(e, q, relSet) {
  const cell = q.engines[e];
  const col = el("div", { class: "col", style: `--eng:${engColor(e)}` });
  const head = el("div", { class: "col-head" },
    el("div", { class: "cname" }, engDot(e), e));
  if (cell) {
    head.append(el("div", { class: "cmetrics" },
      el("span", {}, "mrr ", fmt3(cell.mrr)),
      el("span", {}, "r@10 ", fmt3(cell["recall@10"])),
      el("span", {}, "s@10 ", fmt3(cell["success@10"])),
      el("span", {}, fmt2(cell.latency_ms), " ms")));
  }
  col.append(head);

  const ranked = cell ? cell.ranked : [];
  if (!ranked.length) {
    col.append(el("div", { class: "ranked" }, el("div", { class: "none" }, "no results")));
    return col;
  }
  col.append(el("ol", { class: "ranked" }, ...ranked.map((id, i) => {
    const { kind, name } = splitId(id);
    const hit = relSet.has(id);
    return el("li", { class: hit ? "hit" : "" },
      el("span", { class: "rank" }, i + 1),
      kind ? el("span", { class: "kind" }, kind) : null,
      el("span", { class: "dname", title: id }, name),
      hit ? el("span", { class: "hitmark" }, "\u2713") : null);
  })));
  return col;
}

// ---- scrollspy ----------------------------------------------------------
function wireScrollspy() {
  const links = new Map([...document.querySelectorAll(".topnav a")].map(
    (a) => [a.getAttribute("href").slice(1), a]));
  const obs = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (en.isIntersecting) {
        links.forEach((a) => a.classList.remove("active"));
        links.get(en.target.id)?.classList.add("active");
      }
    }
  }, { rootMargin: "-45% 0px -50% 0px" });
  document.querySelectorAll("main section").forEach((s) => obs.observe(s));
}

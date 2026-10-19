(function () {
  // ---- Theme toggle -------------------------------------------------------
  var btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.addEventListener("click", function () {
      var root = document.documentElement;
      var dark = root.classList.toggle("dark");
      try { localStorage.setItem("mw-theme", dark ? "dark" : "light"); } catch (e) {}
    });
  }

  // ---- Sparklines ---------------------------------------------------------
  // <svg data-sparkline='[...]' data-up="true"> - de-emphasis line, accent end-dot.
  document.querySelectorAll("svg[data-sparkline]").forEach(function (svg) {
    var pts;
    try { pts = JSON.parse(svg.getAttribute("data-sparkline")); } catch (e) { return; }
    if (!pts || pts.length < 2) return;
    var w = 240, h = 56, pad = 4;
    var min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
    var span = max - min || 1;
    var step = (w - pad * 2) / (pts.length - 1);
    var d = pts.map(function (v, i) {
      var x = pad + i * step, y = h - pad - ((v - min) / span) * (h - pad * 2);
      return (i === 0 ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
    var up = svg.getAttribute("data-up") === "true";
    var accent = up ? "#00D09C" : "#EB5B5B";
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    var last = pts[pts.length - 1];
    var lx = pad + (pts.length - 1) * step, ly = h - pad - ((last - min) / span) * (h - pad * 2);
    svg.innerHTML =
      '<path d="' + d + '" fill="none" stroke="#B8BAC4" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' +
      '<circle cx="' + lx.toFixed(1) + '" cy="' + ly.toFixed(1) + '" r="4" fill="' + accent + '" stroke="white" stroke-width="2"/>';
  });

  // ---- Confirm destructive actions ---------------------------------------
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      if (!window.confirm(f.getAttribute("data-confirm"))) ev.preventDefault();
    });
  });
})();

// ---- Ticker type-ahead -----------------------------------------------------
// Any <input data-suggest> gets a dropdown fed by /api/suggest. data-submit="1" submits
// the form on selection; otherwise the chosen symbol is written into the input.
(function () {
  var inputs = document.querySelectorAll("input[data-suggest]");
  if (!inputs.length) return;
  inputs.forEach(function (input) {
    var wrap = input.parentElement;
    if (getComputedStyle(wrap).position === "static") wrap.style.position = "relative";
    var box = document.createElement("div");
    box.className = "suggest";
    box.hidden = true;
    wrap.appendChild(box);
    var items = [], active = -1, timer = null, lastQ = "", ctrl = null;

    function close() { box.hidden = true; box.innerHTML = ""; items = []; active = -1; }
    function choose(i) {
      var it = items[i]; if (!it) return;
      input.value = it.symbol;
      close();
      if (input.getAttribute("data-submit") === "1" && input.form) input.form.submit();
    }
    function render() {
      if (!items.length) { close(); return; }
      box.innerHTML = items.map(function (it, i) {
        return '<button type="button" class="suggest-item' + (i === active ? ' is-active' : '') + '" data-i="' + i + '">' +
          '<span class="suggest-name">' + esc(it.name) + '</span>' +
          '<span class="suggest-sym num">' + esc(it.base_symbol) + ' <small>' + esc(it.exchange) + '</small></span></button>';
      }).join("");
      box.hidden = false;
    }
    function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]; }); }
    function fetchSuggest(q) {
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      fetch("/api/suggest?q=" + encodeURIComponent(q), { signal: ctrl.signal })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (data) { if (q !== lastQ) return; items = data; active = -1; render(); })
        .catch(function () {});
    }
    input.addEventListener("input", function () {
      var q = input.value.trim(); lastQ = q;
      clearTimeout(timer);
      if (q.length < 1) { close(); return; }
      timer = setTimeout(function () { fetchSuggest(q); }, 120);
    });
    input.addEventListener("keydown", function (ev) {
      if (box.hidden) return;
      if (ev.key === "ArrowDown") { ev.preventDefault(); active = (active + 1) % items.length; render(); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); active = (active - 1 + items.length) % items.length; render(); }
      else if (ev.key === "Enter" && active >= 0) { ev.preventDefault(); choose(active); }
      else if (ev.key === "Escape") { close(); }
    });
    box.addEventListener("mousedown", function (ev) {
      var btn = ev.target.closest(".suggest-item"); if (!btn) return;
      ev.preventDefault(); choose(parseInt(btn.getAttribute("data-i"), 10));
    });
    input.addEventListener("blur", function () { setTimeout(close, 150); });
    input.setAttribute("autocomplete", "off");
  });
})();

// ---- Copy buttons ------------------------------------------------------------
document.querySelectorAll("[data-copy]").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var el = document.querySelector(btn.getAttribute("data-copy"));
    if (!el || !navigator.clipboard) return;
    navigator.clipboard.writeText(el.textContent.trim()).then(function () {
      var t = btn.textContent; btn.textContent = "Copied"; setTimeout(function () { btn.textContent = t; }, 1500);
    });
  });
});

// ---- Simple tabs (IPO page) ---------------------------------------------------
(function () {
  var btns = document.querySelectorAll(".tab-btn");
  if (!btns.length) return;
  function show(name) {
    document.querySelectorAll(".tab-panel").forEach(function (p) { p.hidden = p.id !== "tab-" + name; });
    btns.forEach(function (b) {
      var on = b.getAttribute("data-tab") === name;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    try { history.replaceState(null, "", "#" + name); } catch (e) {}
  }
  btns.forEach(function (b) { b.addEventListener("click", function () { show(b.getAttribute("data-tab")); }); });
  var initial = (location.hash || "").replace("#", "");
  show(document.getElementById("tab-" + initial) ? initial : btns[0].getAttribute("data-tab"));
})();

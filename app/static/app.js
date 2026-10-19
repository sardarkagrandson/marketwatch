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

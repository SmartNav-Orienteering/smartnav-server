/* SmartNav track map: map image overlay, control circles, tracks and replay. */
(function () {
  function init(cfg) {
    var el = document.getElementById('map');
    if (!el || typeof L === 'undefined') return;
    var map = L.map(el, { zoomSnap: 0.25 });
    var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 20, maxNativeZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    });
    var bounds = L.latLngBounds([]);
    var overlay = null;
    if (cfg.image && cfg.bounds) {
      var b = [[cfg.bounds.south, cfg.bounds.west], [cfg.bounds.north, cfg.bounds.east]];
      overlay = L.imageOverlay(cfg.image, b, { opacity: 1 }).addTo(map);
      bounds.extend(b);
    } else {
      osm.addTo(map);
    }
    var layers = {};
    if (overlay) { layers['Club map'] = overlay; }
    var courseLayer = L.layerGroup().addTo(map);
    var magenta = '#b0007a';
    function circle(p, label, cls) {
      var ll = [p.lat, p.lon];
      bounds.extend(ll);
      L.circle(ll, { radius: cfg.radius, color: magenta, weight: 2, fill: false }).addTo(courseLayer);
      if (label) {
        L.marker(ll, { icon: L.divIcon({ className: 'control-label', html: label, iconSize: [60, 16], iconAnchor: [-8, 22] }) }).addTo(courseLayer);
      }
    }
    if (cfg.start) {
      var s = [cfg.start.lat, cfg.start.lon];
      bounds.extend(s);
      L.polygon(triangle(s, cfg.radius * 1.4), { color: magenta, weight: 2, fill: false }).addTo(courseLayer);
    }
    var finSame = cfg.finish && cfg.start && cfg.finish.lat === cfg.start.lat && cfg.finish.lon === cfg.start.lon;
    if (cfg.finish) {
      var f = [cfg.finish.lat, cfg.finish.lon];
      bounds.extend(f);
      L.circle(f, { radius: cfg.radius * (finSame ? 1.6 : 1), color: magenta, weight: 2, fill: false }).addTo(courseLayer);
      L.circle(f, { radius: cfg.radius * (finSame ? 1.25 : 0.65), color: magenta, weight: 2, fill: false }).addTo(courseLayer);
    }
    (cfg.controls || []).forEach(function (c) {
      var label = c.code + (c.points != null ? ' (' + c.points + ')' : '');
      circle(c, label);
    });
    if (cfg.ordered && cfg.start && cfg.controls.length) {
      var line = [[cfg.start.lat, cfg.start.lon]].concat(cfg.controls.map(function (c) { return [c.lat, c.lon]; }));
      if (cfg.finish) line.push([cfg.finish.lat, cfg.finish.lon]);
      L.polyline(line, { color: magenta, weight: 1.5, opacity: 0.6, dashArray: '4 6' }).addTo(courseLayer);
    }
    layers['Course'] = courseLayer;
    var base = overlay ? { 'Club map': overlay, 'OpenStreetMap': osm } : { 'OpenStreetMap': osm };
    L.control.layers(base, { 'Course': courseLayer }, { collapsed: true }).addTo(map);
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.08)); else map.setView([-33.87, 151.21], 13);

    var tracks = cfg.tracks || [];
    var loaded = [];
    var maxT = 0;
    Promise.all(tracks.map(function (t) {
      return fetch(t.url).then(function (r) { return r.json(); }).then(function (doc) {
        var pts = doc.points.map(function (p) { return [p[1], p[2]]; });
        var line = L.polyline(pts, { color: t.colour, weight: 3, opacity: 0.85 }).addTo(map);
        line.bindTooltip(t.name, { sticky: true });
        var marker = L.circleMarker(pts[0] || [0, 0], { radius: 6, color: '#fff', weight: 2, fillColor: t.colour, fillOpacity: 1 }).addTo(map);
        marker.bindTooltip(t.name);
        var last = doc.points.length ? doc.points[doc.points.length - 1][0] : 0;
        if (last > maxT) maxT = last;
        loaded.push({ doc: doc, marker: marker, line: line });
        return line;
      });
    })).then(function (lines) {
      if (lines.length && !cfg.keepCourseView) {
        var tb = L.latLngBounds([]);
        lines.forEach(function (l) { tb.extend(l.getBounds()); });
        if (bounds.isValid()) tb.extend(bounds);
        if (tb.isValid()) map.fitBounds(tb.pad(0.05));
      }
      setupReplay();
    });

    function setupReplay() {
      var slider = document.getElementById('replay-t');
      var label = document.getElementById('replay-label');
      var play = document.getElementById('replay-play');
      if (!slider || !loaded.length) return;
      slider.max = Math.ceil(maxT);
      slider.value = slider.max;
      var timer = null;
      function fmt(s) { s = Math.round(s); var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); }
      function at(t) {
        loaded.forEach(function (o) {
          var p = o.doc.points, i = 0;
          if (!p.length) return;
          while (i < p.length - 1 && p[i + 1][0] <= t) i++;
          o.marker.setLatLng([p[i][1], p[i][2]]);
        });
        label.textContent = fmt(t);
      }
      slider.addEventListener('input', function () { at(+slider.value); });
      play.addEventListener('click', function () {
        if (timer) { clearInterval(timer); timer = null; play.textContent = 'Play'; return; }
        if (+slider.value >= +slider.max) slider.value = 0;
        play.textContent = 'Pause';
        var step = Math.max(1, maxT / 600);
        timer = setInterval(function () {
          var v = Math.min(+slider.max, +slider.value + step);
          slider.value = v; at(v);
          if (v >= +slider.max) { clearInterval(timer); timer = null; play.textContent = 'Play'; }
        }, 50);
      });
      at(+slider.value);
    }
  }
  function triangle(c, r) {
    var lat = c[0], lon = c[1], k = Math.cos(lat * Math.PI / 180), d = r / 111320;
    return [[lat + d, lon], [lat - d / 2, lon + d * 0.866 / k], [lat - d / 2, lon - d * 0.866 / k]];
  }
  window.SmartNavMap = { init: init };
})();

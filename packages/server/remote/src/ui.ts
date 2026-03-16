/**
 * SkyFi MCP Worker — Dashboard SPA (embedded HTML)
 *
 * Single-page application served at /ui with Leaflet map visualization,
 * thumbnail gallery, and order tracking. Uses CDN-hosted Leaflet.
 * No wrangler.toml changes needed — compiles as a regular TS string.
 */

export const UI_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SkyFi Dashboard</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
          integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""><\/script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }
    #auth-panel { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; gap: 16px; }
    #auth-panel h1 { font-size: 24px; color: #60a5fa; }
    #auth-panel input { padding: 10px 16px; width: 360px; border: 1px solid #334155; border-radius: 8px; background: #1e293b; color: #e2e8f0; font-size: 14px; }
    #auth-panel button { padding: 10px 24px; border: none; border-radius: 8px; background: #3b82f6; color: white; font-size: 14px; cursor: pointer; }
    #auth-panel button:hover { background: #2563eb; }
    #auth-error { color: #f87171; font-size: 13px; min-height: 20px; }
    #app { display: none; height: 100vh; }
    #app.active { display: grid; grid-template-rows: 48px 1fr; grid-template-columns: 300px 1fr; }
    header { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; background: #1e293b; border-bottom: 1px solid #334155; }
    header h1 { font-size: 16px; color: #60a5fa; }
    header .user-info { display: flex; align-items: center; gap: 12px; font-size: 13px; color: #94a3b8; }
    header button { padding: 4px 12px; border: 1px solid #475569; border-radius: 6px; background: transparent; color: #94a3b8; cursor: pointer; font-size: 12px; }
    header button:hover { background: #334155; }
    #sidebar { background: #1e293b; border-right: 1px solid #334155; overflow-y: auto; display: flex; flex-direction: column; }
    .sidebar-tabs { display: flex; border-bottom: 1px solid #334155; }
    .sidebar-tabs button { flex: 1; padding: 10px; border: none; background: transparent; color: #94a3b8; cursor: pointer; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .sidebar-tabs button.active { color: #60a5fa; border-bottom: 2px solid #60a5fa; }
    .tab-panel { display: none; padding: 12px; flex: 1; overflow-y: auto; }
    .tab-panel.active { display: block; }
    .form-group { margin-bottom: 12px; }
    .form-group label { display: block; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #94a3b8; margin-bottom: 4px; }
    .form-group input, .form-group select { width: 100%; padding: 8px; border: 1px solid #334155; border-radius: 6px; background: #0f172a; color: #e2e8f0; font-size: 13px; }
    .btn { width: 100%; padding: 10px; border: none; border-radius: 6px; background: #3b82f6; color: white; font-size: 13px; font-weight: 600; cursor: pointer; }
    .btn:hover { background: #2563eb; }
    .btn:disabled { background: #475569; cursor: not-allowed; }
    #main-area { display: grid; grid-template-rows: 1fr 280px; }
    #map { width: 100%; height: 100%; }
    #results-panel { background: #1e293b; border-top: 1px solid #334155; overflow-y: auto; padding: 12px; }
    .results-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
    .results-header h3 { font-size: 13px; color: #94a3b8; }
    .gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }
    .gallery-card { background: #0f172a; border: 1px solid #334155; border-radius: 8px; overflow: hidden; cursor: pointer; transition: border-color 0.2s; }
    .gallery-card:hover, .gallery-card.selected { border-color: #60a5fa; }
    .gallery-card img { width: 100%; height: 100px; object-fit: cover; background: #1e293b; }
    .gallery-card .placeholder { width: 100%; height: 100px; display: flex; align-items: center; justify-content: center; background: #1e293b; color: #475569; }
    .gallery-card .info { padding: 8px; font-size: 11px; }
    .gallery-card .info .provider { color: #60a5fa; font-weight: 600; }
    .gallery-card .info .meta { color: #94a3b8; margin-top: 2px; }
    .order-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .order-table th { text-align: left; padding: 8px; color: #94a3b8; border-bottom: 1px solid #334155; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-size: 10px; }
    .order-table td { padding: 8px; border-bottom: 1px solid #1e293b; }
    .status-badge { padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 600; text-transform: uppercase; }
    .status-pending { background: #854d0e33; color: #fbbf24; }
    .status-confirmed, .status-processing { background: #1e3a5f33; color: #60a5fa; }
    .status-delivered { background: #14532d33; color: #4ade80; }
    .status-failed, .status-cancelled { background: #7f1d1d33; color: #f87171; }
    .monitor-card { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px; margin-bottom: 8px; }
    .monitor-card .monitor-status { font-size: 11px; color: #4ade80; font-weight: 600; text-transform: uppercase; }
    .monitor-card .monitor-id { font-size: 12px; color: #94a3b8; margin-top: 4px; }
    .monitor-card .monitor-actions { margin-top: 8px; }
    .monitor-card button { padding: 4px 10px; border: 1px solid #475569; border-radius: 4px; background: transparent; color: #94a3b8; cursor: pointer; font-size: 11px; }
    .monitor-card button:hover { background: #334155; }
    .loading { text-align: center; color: #94a3b8; padding: 20px; font-size: 13px; }
    .empty { text-align: center; color: #475569; padding: 20px; font-size: 13px; }
  </style>
</head>
<body>

<!-- Auth Panel -->
<div id="auth-panel">
  <h1>SkyFi Dashboard</h1>
  <p style="color:#94a3b8;font-size:13px">Enter your SkyFi API key to get started</p>
  <input type="password" id="api-key-input" placeholder="sk-..." autocomplete="off">
  <button onclick="authenticate()">Connect</button>
  <div id="auth-error"></div>
</div>

<!-- Main App -->
<div id="app">
  <header>
    <h1>SkyFi Dashboard</h1>
    <div class="user-info">
      <span id="user-label">Connected</span>
      <button onclick="logout()">Sign Out</button>
    </div>
  </header>

  <div id="sidebar">
    <div class="sidebar-tabs">
      <button class="active" onclick="switchTab('search')">Search</button>
      <button onclick="switchTab('orders')">Orders</button>
      <button onclick="switchTab('monitors')">Monitors</button>
    </div>

    <!-- Search Tab -->
    <div id="tab-search" class="tab-panel active">
      <div class="form-group">
        <label>Location</label>
        <input type="text" id="search-location" placeholder="Address or lat,lon">
      </div>
      <div class="form-group">
        <label>Date From</label>
        <input type="date" id="search-date-from">
      </div>
      <div class="form-group">
        <label>Date To</label>
        <input type="date" id="search-date-to">
      </div>
      <div class="form-group">
        <label>Sensor Type</label>
        <select id="search-sensor">
          <option value="">Any</option>
          <option value="optical">Optical</option>
          <option value="sar">SAR</option>
          <option value="multispectral">Multispectral</option>
          <option value="hyperspectral">Hyperspectral</option>
        </select>
      </div>
      <div class="form-group">
        <label>Max Cloud Cover (%)</label>
        <input type="number" id="search-cloud" min="0" max="100" placeholder="e.g. 20">
      </div>
      <button class="btn" id="search-btn" onclick="doSearch()">Search Archive</button>
    </div>

    <!-- Orders Tab -->
    <div id="tab-orders" class="tab-panel">
      <div class="form-group">
        <label>Filter by Status</label>
        <select id="orders-status">
          <option value="">All</option>
          <option value="pending">Pending</option>
          <option value="confirmed">Confirmed</option>
          <option value="processing">Processing</option>
          <option value="delivered">Delivered</option>
          <option value="cancelled">Cancelled</option>
          <option value="failed">Failed</option>
        </select>
      </div>
      <button class="btn" onclick="loadOrders()">Load Orders</button>
    </div>

    <!-- Monitors Tab -->
    <div id="tab-monitors" class="tab-panel">
      <button class="btn" onclick="loadMonitors()">Load Monitors</button>
    </div>
  </div>

  <div id="main-area">
    <div id="map"></div>
    <div id="results-panel">
      <div class="results-header">
        <h3 id="results-title">Results</h3>
        <span id="results-count" style="font-size:12px;color:#94a3b8"></span>
      </div>
      <div id="results-content" class="empty">Search for satellite imagery to see results</div>
    </div>
  </div>
</div>

<script>
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let jwt = localStorage.getItem('skyfi_jwt');
  let jwtExp = parseInt(localStorage.getItem('skyfi_jwt_exp') || '0', 10);
  let map;
  let footprintLayer;
  let monitorLayer;
  let currentResults = [];
  let ordersRefreshTimer = null;

  const BASE = location.origin;

  // ---------------------------------------------------------------------------
  // Auth
  // ---------------------------------------------------------------------------
  async function authenticate() {
    const key = document.getElementById('api-key-input').value.trim();
    const errEl = document.getElementById('auth-error');
    errEl.textContent = '';
    if (!key) { errEl.textContent = 'Please enter an API key'; return; }

    try {
      const res = await fetch(BASE + '/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key }),
      });
      const data = await res.json();
      if (!res.ok) {
        errEl.textContent = data.message || 'Authentication failed';
        return;
      }
      jwt = data.access_token;
      jwtExp = Math.floor(Date.now() / 1000) + data.expires_in;
      localStorage.setItem('skyfi_jwt', jwt);
      localStorage.setItem('skyfi_jwt_exp', String(jwtExp));
      showApp();
    } catch (e) {
      errEl.textContent = 'Network error — check your connection';
    }
  }

  function logout() {
    jwt = null;
    jwtExp = 0;
    localStorage.removeItem('skyfi_jwt');
    localStorage.removeItem('skyfi_jwt_exp');
    if (ordersRefreshTimer) clearInterval(ordersRefreshTimer);
    document.getElementById('app').classList.remove('active');
    document.getElementById('auth-panel').style.display = 'flex';
  }

  function checkAuth() {
    if (!jwt || Date.now() / 1000 > jwtExp - 60) {
      logout();
      return false;
    }
    return true;
  }

  async function apiFetch(path, opts = {}) {
    if (!checkAuth()) throw new Error('Not authenticated');
    const res = await fetch(BASE + path, {
      ...opts,
      headers: {
        'Authorization': 'Bearer ' + jwt,
        'Content-Type': 'application/json',
        ...(opts.headers || {}),
      },
    });
    if (res.status === 401) { logout(); throw new Error('Session expired'); }
    return res;
  }

  // ---------------------------------------------------------------------------
  // App init
  // ---------------------------------------------------------------------------
  function showApp() {
    document.getElementById('auth-panel').style.display = 'none';
    document.getElementById('app').classList.add('active');
    if (!map) initMap();
    else map.invalidateSize();
  }

  function initMap() {
    map = L.map('map').setView([20, 0], 3);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
    }).addTo(map);
    footprintLayer = L.featureGroup().addTo(map);
    monitorLayer = L.featureGroup().addTo(map);
  }

  // Auto-login if JWT is still valid
  if (jwt && Date.now() / 1000 < jwtExp - 60) {
    showApp();
  }

  // ---------------------------------------------------------------------------
  // Tab switching
  // ---------------------------------------------------------------------------
  function switchTab(name) {
    document.querySelectorAll('.sidebar-tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelector('.sidebar-tabs button[onclick*="' + name + '"]').classList.add('active');
    document.getElementById('tab-' + name).classList.add('active');

    if (name === 'orders') loadOrders();
    if (name === 'monitors') loadMonitors();
  }

  // ---------------------------------------------------------------------------
  // Search
  // ---------------------------------------------------------------------------
  async function doSearch() {
    const btn = document.getElementById('search-btn');
    btn.disabled = true;
    btn.textContent = 'Searching...';

    const loc = document.getElementById('search-location').value.trim();
    if (!loc) { btn.disabled = false; btn.textContent = 'Search Archive'; return; }

    const params = new URLSearchParams({ location: loc });
    const dateFrom = document.getElementById('search-date-from').value;
    const dateTo = document.getElementById('search-date-to').value;
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const sensor = document.getElementById('search-sensor').value;
    if (sensor) params.set('sensor', sensor);
    const cloud = document.getElementById('search-cloud').value;
    if (cloud) params.set('cloud_max', cloud);

    try {
      const res = await apiFetch('/api/search?' + params.toString());
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || 'Search failed');
      currentResults = data.results || [];
      renderSearchResults(currentResults);
      renderFootprints(currentResults);
    } catch (e) {
      document.getElementById('results-content').innerHTML = '<div class="empty">' + escapeHtml(e.message) + '</div>';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Search Archive';
    }
  }

  function renderSearchResults(results) {
    const title = document.getElementById('results-title');
    const count = document.getElementById('results-count');
    const content = document.getElementById('results-content');
    title.textContent = 'Search Results';
    count.textContent = results.length + ' images';

    if (results.length === 0) {
      content.innerHTML = '<div class="empty">No results found</div>';
      return;
    }

    let html = '<div class="gallery">';
    results.forEach((r, i) => {
      const date = r.capture_date ? new Date(r.capture_date).toLocaleDateString() : 'N/A';
      const cloud = r.cloud_cover != null ? r.cloud_cover.toFixed(0) + '%' : 'N/A';
      html += '<div class="gallery-card" onclick="selectResult(' + i + ')" id="card-' + i + '">';
      if (r.thumbnail_url) {
        html += '<img src="' + escapeHtml(r.thumbnail_url) + '" alt="' + escapeHtml(r.archive_id) + '" loading="lazy">';
      } else {
        html += '<div class="placeholder"><svg width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M12 3C7.03 3 3 7.03 3 12s4.03 9 9 9 9-4.03 9-9-4.03-9-9-9z"/><path d="M12 8v4l2 2"/></svg></div>';
      }
      html += '<div class="info"><div class="provider">' + escapeHtml(r.provider) + '</div>';
      html += '<div class="meta">' + date + ' &middot; ' + cloud + ' cloud &middot; ' + r.resolution + 'm</div></div></div>';
    });
    html += '</div>';
    content.innerHTML = html;
  }

  function renderFootprints(results) {
    footprintLayer.clearLayers();
    results.forEach((r, i) => {
      if (r.geometry && r.geometry.coordinates && r.geometry.coordinates.length > 0) {
        const coords = r.geometry.coordinates[0].map(c => [c[1], c[0]]);
        const poly = L.polygon(coords, {
          color: '#60a5fa', weight: 2, fillOpacity: 0.15, fillColor: '#3b82f6',
        });
        poly.bindTooltip(r.provider + ' — ' + (r.capture_date ? new Date(r.capture_date).toLocaleDateString() : '') + ' — ' + r.resolution + 'm');
        poly.on('click', () => selectResult(i));
        poly.addTo(footprintLayer);
      }
    });
    if (footprintLayer.getLayers().length > 0) {
      map.fitBounds(footprintLayer.getBounds().pad(0.1));
    }
  }

  function selectResult(index) {
    document.querySelectorAll('.gallery-card').forEach(c => c.classList.remove('selected'));
    const card = document.getElementById('card-' + index);
    if (card) card.classList.add('selected');

    const layers = footprintLayer.getLayers();
    if (layers[index]) {
      layers[index].setStyle({ color: '#fbbf24', weight: 3, fillOpacity: 0.3 });
      map.fitBounds(layers[index].getBounds().pad(0.2));
      // Reset others
      layers.forEach((l, i) => {
        if (i !== index) l.setStyle({ color: '#60a5fa', weight: 2, fillOpacity: 0.15 });
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Orders
  // ---------------------------------------------------------------------------
  async function loadOrders() {
    const content = document.getElementById('results-content');
    const title = document.getElementById('results-title');
    const count = document.getElementById('results-count');
    title.textContent = 'Orders';
    count.textContent = '';
    content.innerHTML = '<div class="loading">Loading orders...</div>';

    const status = document.getElementById('orders-status').value;
    const params = new URLSearchParams();
    if (status) params.set('status', status);

    try {
      const res = await apiFetch('/api/orders?' + params.toString());
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || 'Failed to load orders');
      const orders = data.orders || [];
      count.textContent = orders.length + ' orders';
      renderOrders(orders);
    } catch (e) {
      content.innerHTML = '<div class="empty">' + escapeHtml(e.message) + '</div>';
    }
  }

  function renderOrders(orders) {
    const content = document.getElementById('results-content');
    if (orders.length === 0) {
      content.innerHTML = '<div class="empty">No orders found</div>';
      return;
    }

    let html = '<table class="order-table"><thead><tr><th>Order ID</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead><tbody>';
    orders.forEach(o => {
      const status = (o.status || 'unknown').toLowerCase();
      const statusClass = 'status-' + status;
      const created = o.created_at ? new Date(o.created_at).toLocaleDateString() : 'N/A';
      html += '<tr>';
      html += '<td style="font-family:monospace;font-size:11px">' + escapeHtml(o.order_id || '') + '</td>';
      html += '<td><span class="status-badge ' + statusClass + '">' + escapeHtml(status) + '</span></td>';
      html += '<td>' + created + '</td>';
      html += '<td>';
      if (status === 'delivered') {
        html += '<button onclick="viewOrderImages(\\'' + escapeHtml(o.order_id) + '\\')">View Images</button>';
      }
      html += '</td>';
      html += '</tr>';
    });
    html += '</tbody></table>';
    content.innerHTML = html;

    // Auto-refresh
    if (ordersRefreshTimer) clearInterval(ordersRefreshTimer);
    ordersRefreshTimer = setInterval(loadOrders, 30000);
  }

  async function viewOrderImages(orderId) {
    try {
      const res = await apiFetch('/api/orders/' + encodeURIComponent(orderId) + '/images');
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || 'Failed to load images');
      const images = data.images || [];
      const content = document.getElementById('results-content');
      if (images.length === 0) {
        content.innerHTML = '<div class="empty">No images available yet</div>';
        return;
      }
      let html = '<div class="gallery">';
      images.forEach(img => {
        html += '<div class="gallery-card"><a href="' + escapeHtml(img.url || '') + '" target="_blank">';
        html += '<div class="placeholder"><svg width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M12 10v6m-3-3h6"/><rect x="3" y="3" width="18" height="18" rx="2"/></svg></div>';
        html += '<div class="info"><div class="provider">' + escapeHtml(img.format || 'Image') + '</div>';
        html += '<div class="meta">' + (img.size_mb ? img.size_mb.toFixed(1) + ' MB' : '') + '</div></div>';
        html += '</a></div>';
      });
      html += '</div>';
      content.innerHTML = html;
    } catch (e) {
      document.getElementById('results-content').innerHTML = '<div class="empty">' + escapeHtml(e.message) + '</div>';
    }
  }

  // ---------------------------------------------------------------------------
  // Monitors
  // ---------------------------------------------------------------------------
  async function loadMonitors() {
    const content = document.getElementById('results-content');
    const title = document.getElementById('results-title');
    const count = document.getElementById('results-count');
    title.textContent = 'Monitors';
    count.textContent = '';
    content.innerHTML = '<div class="loading">Loading monitors...</div>';

    try {
      const res = await apiFetch('/api/monitors');
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || 'Failed to load monitors');
      const monitors = data.monitors || [];
      count.textContent = monitors.length + ' monitors';
      renderMonitors(monitors);
    } catch (e) {
      content.innerHTML = '<div class="empty">' + escapeHtml(e.message) + '</div>';
    }
  }

  function renderMonitors(monitors) {
    const content = document.getElementById('results-content');
    monitorLayer.clearLayers();

    if (monitors.length === 0) {
      content.innerHTML = '<div class="empty">No active monitors</div>';
      return;
    }

    let html = '';
    monitors.forEach(m => {
      html += '<div class="monitor-card">';
      html += '<div class="monitor-status">' + escapeHtml(m.status || 'active') + '</div>';
      html += '<div class="monitor-id">ID: ' + escapeHtml(m.monitor_id || '') + '</div>';
      if (m.webhook_url) html += '<div class="monitor-id" style="margin-top:2px">Webhook: ' + escapeHtml(m.webhook_url) + '</div>';
      html += '<div class="monitor-actions">';
      html += '<button onclick="deleteMonitor(\\'' + escapeHtml(m.monitor_id) + '\\')">Delete</button>';
      html += '</div></div>';

      // Show AOI on map
      if (m.geometry && m.geometry.coordinates && m.geometry.coordinates.length > 0) {
        const coords = m.geometry.coordinates[0].map(c => [c[1], c[0]]);
        L.polygon(coords, {
          color: '#a78bfa', weight: 2, dashArray: '6,4', fillOpacity: 0.1, fillColor: '#7c3aed',
        }).addTo(monitorLayer);
      }
    });
    content.innerHTML = html;

    if (monitorLayer.getLayers().length > 0) {
      map.fitBounds(monitorLayer.getBounds().pad(0.1));
    }
  }

  async function deleteMonitor(monitorId) {
    if (!confirm('Delete monitor ' + monitorId + '?')) return;
    try {
      await apiFetch('/api/monitors/' + encodeURIComponent(monitorId), { method: 'DELETE' });
      loadMonitors();
    } catch (e) {
      alert('Failed to delete: ' + e.message);
    }
  }

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------
  function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
<\/script>
</body>
</html>`;

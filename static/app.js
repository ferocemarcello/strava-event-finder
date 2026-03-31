let allEvents = [];
let selectedLat = null;
let selectedLon = null;
let debounceTimer = null;
let map = null;
let marker = null;

async function init() {
  const res = await fetch("/api/me");
  const data = await res.json();

  const authArea = document.getElementById("auth-area");
  if (data.authenticated) {
    authArea.innerHTML = `<span class="athlete-name">&#128100; ${escapeHtml(data.athlete_name)}</span>
      <a href="/auth/logout" class="btn-logout">Log out</a>`;
    show("search-section");
    initMap();
  } else {
    show("hero");
  }

  const params = new URLSearchParams(window.location.search);
  if (params.get("error")) {
    showError("Strava login failed. Please try again.");
  }
}

// --- Map ---
function initMap() {
  map = L.map("location-map").setView([48, 14], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  map.on("click", async (e) => {
    const { lat, lng } = e.latlng;
    setMarker(lat, lng);
    setStatus("Reverse geocoding…");
    const name = await reverseGeocode(lat, lng);
    document.getElementById("location-input").value = name || `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    setStatus("");
  });
}

function setMarker(lat, lon) {
  selectedLat = lat;
  selectedLon = lon;
  if (marker) {
    marker.setLatLng([lat, lon]);
  } else {
    marker = L.marker([lat, lon]).addTo(map);
  }
  map.panTo([lat, lon]);
}

async function reverseGeocode(lat, lon) {
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
      { headers: { "User-Agent": "StravaEventFinder/1.0" } }
    );
    if (!res.ok) return null;
    const data = await res.json();
    return data.display_name || null;
  } catch (_) {
    return null;
  }
}

// --- Geolocation button ---
document.getElementById("geolocate-btn").addEventListener("click", () => {
  if (!navigator.geolocation) {
    setStatus("Geolocation is not supported by your browser.");
    return;
  }
  setStatus("Detecting your location…");
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const { latitude: lat, longitude: lon } = pos.coords;
      setMarker(lat, lon);
      if (map) map.setView([lat, lon], 11);
      const name = await reverseGeocode(lat, lon);
      document.getElementById("location-input").value = name || `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
      hideSuggestions();
      setStatus("");
    },
    () => setStatus("Could not get your location. Please enter a city name or click the map.")
  );
});

// --- Autocomplete ---
const locationInput = document.getElementById("location-input");

locationInput.addEventListener("input", () => {
  selectedLat = null;
  selectedLon = null;
  const q = locationInput.value.trim();
  clearTimeout(debounceTimer);
  if (q.length < 2) { hideSuggestions(); return; }
  debounceTimer = setTimeout(() => fetchSuggestions(q), 300);
});

locationInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") hideSuggestions();
  if (e.key === "Enter") { hideSuggestions(); search(); }
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".autocomplete-wrap")) hideSuggestions();
});

async function fetchSuggestions(q) {
  try {
    const res = await fetch(`https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=5`);
    if (!res.ok) { setStatus(`Suggestion error: ${res.status}`); return; }
    const data = await res.json();
    const suggestions = (data.features || []).map((f) => {
      const p = f.properties || {};
      const [lon, lat] = f.geometry.coordinates;
      const parts = [p.name, p.city || p.district, p.state, p.country].filter(Boolean);
      const deduped = [parts[0], ...parts.slice(1).filter((b, i) => b !== parts[i])];
      return { display_name: deduped.join(", "), lat, lon };
    });
    showSuggestions(suggestions);
  } catch (e) {
    setStatus(`Suggestion error: ${e.message}`);
  }
}

function showSuggestions(suggestions) {
  const list = document.getElementById("location-suggestions");
  list.innerHTML = "";
  if (!suggestions.length) { hideSuggestions(); return; }
  suggestions.forEach((s) => {
    const li = document.createElement("li");
    li.textContent = s.display_name;
    li.addEventListener("mousedown", (e) => {
      e.preventDefault();
      locationInput.value = s.display_name;
      setMarker(s.lat, s.lon);
      if (map) map.setView([s.lat, s.lon], 11);
      hideSuggestions();
      setStatus("");
    });
    list.appendChild(li);
  });
  list.classList.remove("hidden");
}

function hideSuggestions() {
  document.getElementById("location-suggestions").classList.add("hidden");
}

// --- Search ---
document.getElementById("search-btn").addEventListener("click", search);

document.getElementById("radius-slider").addEventListener("input", (e) => {
  document.getElementById("radius-label").textContent = `${e.target.value} km`;
});

["filter-sport", "filter-length", "filter-date-from", "filter-date-to", "sort-by"].forEach((id) => {
  document.getElementById(id).addEventListener("change", () => applyAndRender());
});

async function search() {
  clearError();
  const radius = parseFloat(document.getElementById("radius-slider").value);

  if (selectedLat === null || selectedLon === null) {
    showError("Please select a location — type a city, click the map, or use 'Use my location'.");
    return;
  }

  setStatus("");
  show("loading");
  hide("results-section");
  hide("error-msg");

  try {
    const res = await fetch(`/api/events?lat=${selectedLat}&lon=${selectedLon}&radius_km=${radius}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to fetch events");
    }
    allEvents = await res.json();
    hide("loading");
    populateSportFilter(allEvents);
    applyAndRender();
  } catch (e) {
    hide("loading");
    showError(e.message);
  }
}

const COMMON_SPORT_TYPES = ["Ride", "Run", "Swim", "Walk", "Hike", "VirtualRide", "VirtualRun", "Workout"];

function populateSportFilter(events) {
  const select = document.getElementById("filter-sport");
  const fromResults = [...new Set(events.map((e) => e.activity_type).filter(Boolean))];
  const allTypes = [...new Set([...COMMON_SPORT_TYPES, ...fromResults])].sort();
  select.innerHTML = '<option value="">All</option>';
  allTypes.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    select.appendChild(opt);
  });
}

function applyAndRender() {
  const sport = document.getElementById("filter-sport").value;
  const length = document.getElementById("filter-length").value;
  const dateFrom = document.getElementById("filter-date-from").value;
  const dateTo = document.getElementById("filter-date-to").value;
  const sortBy = document.getElementById("sort-by").value;

  let filtered = allEvents.filter((ev) => {
    if (sport && ev.activity_type !== sport) return false;
    if (length) {
      const [minKm, maxKm] = length.split("-").map(Number);
      const evKm = (ev.distance_meters || 0) / 1000;
      if (evKm < minKm || evKm >= maxKm) return false;
    }
    if (dateFrom && ev.start_date && ev.start_date.slice(0, 10) < dateFrom) return false;
    if (dateTo && ev.start_date && ev.start_date.slice(0, 10) > dateTo) return false;
    return true;
  });

  filtered.sort((a, b) => {
    if (sortBy === "distance") return a.club_distance_km - b.club_distance_km;
    if (sortBy === "length") return (a.distance_meters || 0) - (b.distance_meters || 0);
    return (a.start_date || "").localeCompare(b.start_date || "");
  });

  const radius = parseFloat(document.getElementById("radius-slider").value);
  renderEvents(filtered, radius);
}

function renderEvents(events, radius) {
  const grid = document.getElementById("events-grid");
  const noResults = document.getElementById("no-results");
  const title = document.getElementById("results-title");

  grid.innerHTML = "";
  show("results-section");

  if (events.length === 0) {
    title.textContent = "No Events Found";
    show("no-results");
    return;
  }

  hide("no-results");
  title.textContent = `${events.length} Upcoming Event${events.length !== 1 ? "s" : ""} within ${radius} km`;

  events.forEach((ev) => {
    const card = document.createElement("div");
    card.className = "event-card";

    const dateStr = ev.start_date ? formatDate(ev.start_date) : "Date TBD";
    const location = ev.address || ev.club_city || "";
    const lengthStr = ev.distance_meters ? `${(ev.distance_meters / 1000).toFixed(1)} km` : null;

    card.innerHTML = `
      <div class="event-header">
        <h3 class="event-title">${escapeHtml(ev.title || "Unnamed Event")}</h3>
        <span class="event-distance">${ev.club_distance_km !== null ? ev.club_distance_km + ' km away' : 'nearby'}</span>
      </div>
      <p class="event-club">&#127937; ${escapeHtml(ev.club_name || "")}</p>
      ${ev.activity_type ? `<p class="event-sport">&#127955; ${escapeHtml(ev.activity_type)}</p>` : ""}
      <p class="event-date">&#128197; ${dateStr}</p>
      ${lengthStr ? `<p class="event-length">&#128207; ${lengthStr}</p>` : ""}
      ${location ? `<p class="event-location">&#128205; ${escapeHtml(location)}</p>` : ""}
      ${ev.description ? `<p class="event-desc">${escapeHtml(ev.description)}</p>` : ""}
      <a href="${escapeHtml(ev.url)}" target="_blank" rel="noopener" class="btn-view">View on Strava &#8599;</a>
    `;
    grid.appendChild(card);
  });
}

function formatDate(iso) {
  if (!iso) return "Date TBD";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function show(id) { document.getElementById(id).classList.remove("hidden"); }
function hide(id) { document.getElementById(id).classList.add("hidden"); }
function setStatus(msg) { document.getElementById("location-status").textContent = msg; }
function clearError() { hide("error-msg"); document.getElementById("error-msg").textContent = ""; }
function showError(msg) {
  const el = document.getElementById("error-msg");
  el.textContent = msg;
  show("error-msg");
}

init();

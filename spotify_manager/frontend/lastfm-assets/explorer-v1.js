import * as charts from "./charts-v1.js";
import {
  element,
  entityButton,
  exportCSV,
  number,
  percent,
  rankingTable,
  recordedTime,
  recordsTable,
  renderTable,
  returnRate,
} from "./tables-v1.js";

const $ = (id) => document.getElementById(id);
const parameters = new URLSearchParams(location.search);
const tabs = ["overview", "taste", "discovery", "rediscovery"];
const weekdays = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
const state = {
  password: localStorage.getItem("sm_pw") || "",
  authenticated: false,
  epoch: 0,
  metadata: null,
  snapshot: null,
  from: parameters.get("from"),
  to: parameters.get("to"),
  timezone: parameters.get("tz") || "Europe/Berlin",
  artist: parameters.get("artist"),
  artistName: parameters.get("artist_name") || "",
  weekday: parameters.has("weekday") ? Number(parameters.get("weekday")) : null,
  hour: parameters.has("hour") ? Number(parameters.get("hour")) : null,
  tab: tabs.includes(parameters.get("tab"))
    ? parameters.get("tab")
    : "overview",
  preset: parameters.get("preset") || (parameters.has("from") ? null : "year"),
  rankingPage: 1,
  recordsPage: 1,
  selected: parameters.has("entity")
    ? { kind: parameters.get("kind"), key: parameters.get("entity") }
    : null,
  data: {},
  controller: null,
  detailController: null,
  pollTimer: null,
  detailData: null,
  revision: 0,
  initialized: false,
  timezoneNotice: "",
};
try {
  new Intl.DateTimeFormat("en", { timeZone: state.timezone });
} catch {
  state.timezone = "Europe/Berlin";
  state.timezoneNotice =
    "The linked timezone was unrecognized; showing Europe/Berlin.";
}

function context() {
  return {
    snapshot: state.snapshot,
    from: state.from,
    to: state.to,
    timezone: state.timezone,
    artist: state.artist,
    weekday: state.weekday,
    hour: state.hour,
  };
}

function banner(message, warning = false) {
  $("status").textContent = message;
  $("status").classList.toggle("warning", warning);
}

function showLogin(message = "") {
  state.epoch++;
  state.authenticated = false;
  state.password = "";
  state.snapshot = null;
  state.metadata = null;
  state.data = {};
  state.detailData = null;
  state.controller?.abort();
  state.detailController?.abort();
  clearTimeout(state.pollTimer);
  localStorage.removeItem("sm_pw");
  charts.clearCharts();
  if ($("detail").open) $("detail").close();
  $("workspace").hidden = true;
  $("login").hidden = false;
  $("lock").hidden = true;
  $("login-error").textContent = message;
  $("archive-years").textContent = "Private listening archive";
  $("archive-through").textContent =
    "Unlock to explore your published history.";
  banner("Your archive is locked.");
}

async function request(path, query, signal) {
  const suffix = query ? `?${new URLSearchParams(query)}` : "";
  const response = await fetch(path + suffix, {
    headers: { "X-App-Password": state.password },
    signal,
    cache: "no-store",
  });
  if (response.status === 401) {
    showLogin("Enter your app password to continue.");
    throw Object.assign(new Error("Authentication required."), { status: 401 });
  }
  const body = await response.json();
  if (!response.ok) {
    const message =
      typeof body.detail === "string"
        ? body.detail
        : "Check the selected dates, timezone, and filter values.";
    throw Object.assign(new Error(message), { status: response.status });
  }
  return body;
}

async function authenticate() {
  $("login-error").textContent = "";
  const epoch = state.epoch;
  try {
    await request("/auth/check");
    if (epoch !== state.epoch) return;
    state.authenticated = true;
    if (state.password) localStorage.setItem("sm_pw", state.password);
    $("password").value = "";
    $("login").hidden = true;
    $("lock").hidden = false;
    await checkStatus();
  } catch (error) {
    if (error.status !== 401) {
      banner(
        "Could not connect to Spotify Manager. Check the connection and retry.",
        true,
      );
      $("retry").hidden = false;
    }
  }
}

function localDay(timestamp, timezone) {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(timestamp));
  const values = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return `${values.year}-${values.month}-${values.day}`;
}

function shiftDay(day, distance) {
  const value = new Date(`${day}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + distance);
  return value.toISOString().slice(0, 10);
}

function lastYearStart(day) {
  const [year, month, date] = day.split("-").map(Number);
  const maximum = new Date(Date.UTC(year - 1, month, 0)).getUTCDate();
  const previous = new Date(
    Date.UTC(year - 1, month - 1, Math.min(date, maximum)),
  );
  return shiftDay(previous.toISOString().slice(0, 10), 1);
}

function applyPreset(preset) {
  if (state.metadata?.last_ms == null) return;
  state.to = localDay(state.metadata.last_ms, state.timezone);
  state.from =
    preset === "all"
      ? localDay(state.metadata.first_ms, state.timezone)
      : preset === "year"
        ? lastYearStart(state.to)
        : shiftDay(state.to, 1 - Number(preset));
  state.preset = preset;
  state.rankingPage = 1;
}

function configure() {
  if (!state.from || !state.to) {
    if (state.metadata.last_ms == null) {
      state.to = localDay(Date.now(), state.timezone);
      state.from = lastYearStart(state.to);
    } else applyPreset(state.preset || "year");
  }
  $("from").value = state.from;
  $("to").value = state.to;
  $("timezone").value = state.timezone;
  $("artist-search").value = state.artistName;
  $("archive-years").textContent =
    state.metadata.first_ms == null
      ? "No recorded plays"
      : `${localDay(state.metadata.first_ms, state.timezone).slice(0, 4)} — ${localDay(state.metadata.last_ms, state.timezone).slice(0, 4)}`;
  $("archive-through").textContent =
    state.metadata.last_ms == null
      ? "The publication is empty."
      : `History through ${localDay(state.metadata.last_ms, state.timezone)}`;
  $("publication").textContent =
    `PUBLISHED ${recordedTime(Date.parse(state.metadata.published_at), state.timezone)}`;
  $("source-footnote").textContent =
    `${number(state.metadata.scrobbles)} published scrobbles · Source ${state.snapshot}`;
  $("selection-caption").textContent =
    `${state.from} → ${state.to} · ${state.timezone}. Presets end at the latest stored scrobble. Boundary days may be partial. ${state.timezoneNotice}`;
  document
    .querySelectorAll("[data-preset]")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.preset === state.preset),
      ),
    );
  renderChips();
  showTab();
}

function freshness(status) {
  if (status.state === "stale") {
    banner(status.message, true);
    return;
  }
  if (state.metadata.last_ms == null) {
    banner(
      "This publication contains no scrobbles. Sync Last.fm history to add recorded plays.",
    );
    return;
  }
  const age = Math.floor((Date.now() - state.metadata.last_ms) / 86400000);
  const through = recordedTime(state.metadata.last_ms, state.timezone);
  banner(
    age > 2
      ? `History ends ${through} · ${age} days ago. Sync history to include newer plays.`
      : `History through ${through}. All views use one complete published snapshot.`,
    age > 2,
  );
}

async function checkStatus(force = false) {
  const epoch = state.epoch;
  clearTimeout(state.pollTimer);
  try {
    const status = await request(
      "/lastfm/analytics/status",
      force ? { refresh: "true" } : null,
    );
    if (epoch !== state.epoch || !state.authenticated) return;
    $("retry").hidden = false;
    $("sync-link").hidden = !["missing", "stale", "error"].includes(
      status.state,
    );
    if (status.metadata) {
      const changed = state.snapshot !== status.metadata.snapshot;
      state.metadata = status.metadata;
      state.snapshot = status.metadata.snapshot;
      $("workspace").hidden = false;
      if (changed && state.initialized && state.preset)
        applyPreset(state.preset);
      if (changed || !state.initialized) configure();
      freshness(status);
      if (changed || !state.initialized) {
        state.initialized = true;
        await loadSelection();
      }
    } else {
      banner(status.message, ["error", "missing"].includes(status.state));
      if (status.state === "error") $("sync-link").hidden = false;
    }
    if (status.checking || status.state === "building")
      state.pollTimer = setTimeout(() => checkStatus(), 2000);
  } catch (error) {
    if (error.status !== 401) {
      banner(
        "The stored history service is unavailable. Your last loaded view remains visible; retry to reconnect.",
        true,
      );
      $("retry").hidden = false;
    }
  }
}

function query(extra = {}) {
  const values = {
    from: state.from,
    to: state.to,
    tz: state.timezone,
    snapshot: state.snapshot,
  };
  if (state.artist) values.artist = state.artist;
  if (state.weekday !== null) values.weekday = state.weekday;
  if (state.hour !== null) values.hour = state.hour;
  return { ...values, ...extra };
}

async function analytics(
  endpoint,
  extra = {},
  signal = state.controller?.signal,
) {
  const body = await request(
    `/lastfm/analytics/${endpoint}`,
    query(extra),
    signal,
  );
  if (body.snapshot !== state.snapshot)
    throw new Error("The source changed. Reload the selection.");
  return body.data;
}

function persist() {
  const url = new URL(location.href);
  url.search = "";
  const values = {
    from: state.from,
    to: state.to,
    tz: state.timezone,
    tab: state.tab,
  };
  if (state.preset) values.preset = state.preset;
  if (state.artist) {
    values.artist = state.artist;
    values.artist_name = state.artistName;
  }
  if (state.weekday !== null) values.weekday = state.weekday;
  if (state.hour !== null) values.hour = state.hour;
  if (state.selected) {
    values.kind = state.selected.kind;
    values.entity = state.selected.key;
  }
  for (const [key, value] of Object.entries(values))
    url.searchParams.set(key, value);
  history.replaceState(null, "", url);
}

function showTab() {
  for (const tab of tabs) $("tab-" + tab).hidden = state.tab !== tab;
  document.querySelectorAll("[data-tab]").forEach((button) => {
    if (button.dataset.tab === state.tab)
      button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function renderChips() {
  const container = $("filter-chips");
  container.replaceChildren();
  if (state.artist) {
    const button = element(
      "button",
      `Artist: ${state.artistName || state.artist.slice(0, 8)} ×`,
      "chip",
    );
    button.type = "button";
    button.addEventListener("click", () => {
      state.artist = null;
      state.artistName = "";
      state.rankingPage = 1;
      loadSelection();
    });
    container.append(button);
  }
  if (state.weekday !== null || state.hour !== null) {
    const label = `${state.weekday !== null ? weekdays[state.weekday] : "Every day"}${state.hour !== null ? ` · ${String(state.hour).padStart(2, "0")}:00` : ""}`;
    const button = element("button", `${label} ×`, "chip");
    button.type = "button";
    button.addEventListener("click", () => {
      state.weekday = null;
      state.hour = null;
      loadSelection();
    });
    container.append(button);
  }
}

function loading(value) {
  $("workspace").setAttribute("aria-busy", String(value));
  for (const tab of tabs) $("tab-" + tab).inert = value;
  document
    .querySelectorAll("[data-csv],[data-chart-export]")
    .forEach((button) => (button.disabled = value));
}

function clearResults() {
  charts.clearCharts();
  document
    .querySelectorAll(".table-scroll")
    .forEach((node) => node.replaceChildren());
  for (const metric of ["plays", "artists", "tracks", "albums", "days"])
    $("metric-" + metric).textContent = "—";
}

async function loadSelection(recoverVersion = true) {
  if (!state.snapshot) return;
  state.controller?.abort();
  state.detailController?.abort();
  const revision = ++state.revision;
  state.controller = new AbortController();
  state.data = {};
  $("view-error").hidden = true;
  if (["discovery", "rediscovery"].includes(state.tab)) {
    state.weekday = null;
    state.hour = null;
  }
  configure();
  persist();
  loading(true);
  try {
    const tasks = [analytics("overview")];
    if (state.tab === "overview")
      tasks.push(analytics("activity"), analytics("rankings", rankingQuery()));
    if (state.tab === "taste")
      tasks.push(
        analytics("evolution", { grain: $("grain").value }),
        analytics("comparison"),
      );
    if (state.tab === "discovery") tasks.push(analytics("discovery"));
    if (state.tab === "rediscovery")
      tasks.push(analytics("rediscovery", rediscoveryQuery()));
    const results = await Promise.all(tasks);
    if (revision !== state.revision) return;
    renderOverview(results[0]);
    renderView(results.slice(1));
    if (state.selected && !$("detail").open)
      await openEntity(state.selected.kind, state.selected.key);
  } catch (error) {
    if (
      error.name === "AbortError" ||
      revision !== state.revision ||
      error.status === 401
    )
      return;
    if (error.status === 409 && recoverVersion) {
      const status = await request("/lastfm/analytics/status");
      if (status.metadata) {
        state.snapshot = status.metadata.snapshot;
        state.metadata = status.metadata;
        return loadSelection(false);
      }
    }
    clearResults();
    $("view-error").textContent =
      error.message || "The selection could not be loaded. Retry shortly.";
    $("view-error").hidden = false;
  } finally {
    if (revision === state.revision) loading(false);
  }
}

function renderOverview(data) {
  state.data.overview = data;
  const values = {
    plays: data.counts.scrobbles,
    artists: data.counts.artists,
    tracks: data.counts.tracks,
    albums: data.counts.albums,
    days: data.counts.active_days,
  };
  for (const [name, value] of Object.entries(values))
    $("metric-" + name).textContent = number(value);
  $("metric-average").textContent =
    `${data.per_calendar_day.toFixed(1)} / calendar day`;
  $("metric-active-average").textContent =
    `${data.per_active_day.toFixed(1)} / active day`;
  $("metric-missing").textContent =
    `${number(data.counts.missing_album)} plays lack an album`;
}

function renderView(results) {
  const ctx = context();
  if (state.tab === "overview") {
    state.data.activity = results[0];
    state.data.rankings = results[1];
    calendarYears();
    renderCalendar();
    renderRhythm();
    charts.rankings(results[1], $("rank-kind").value, ctx);
    rankingTable("rankings-table", results[1], $("rank-kind").value);
    pageControls("rank", results[1]);
  }
  if (state.tab === "taste") {
    state.data.evolution = results[0];
    state.data.comparison = results[1];
    charts.evolution(results[0], $("evolution-mode").value, ctx);
    charts.breadth(results[0], ctx);
    charts.comparison(results[1], ctx);
    renderTasteTables();
  }
  if (state.tab === "discovery") {
    state.data.discovery = results[0];
    charts.discoveries(results[0], ctx);
    renderDiscovery();
  }
  if (state.tab === "rediscovery") {
    state.data.rediscovery = results[0];
    charts.rediscovery(results[0], $("rediscovery-kind").value, ctx);
    renderRediscovery();
  }
}

function calendarYears() {
  const old = $("calendar-year").value;
  const years = [
    ...new Set(state.data.activity.days.map((item) => item.day.slice(0, 4))),
  ].reverse();
  $("calendar-year").replaceChildren(
    ...years.map((year) => new Option(year, year)),
  );
  if (years.includes(old)) $("calendar-year").value = old;
}

function renderCalendar() {
  if (!state.data.activity) return;
  const year = $("calendar-year").value;
  charts.calendar(state.data.activity, year, context());
  const rows = state.data.activity.days
    .filter((item) => item.day.startsWith(year))
    .map((item) => {
      const button = element("button", item.day, "entity-button");
      button.type = "button";
      button.disabled = !item.covered;
      button.dataset.day = item.day;
      return [
        button,
        number(item.plays),
        item.covered
          ? item.partial
            ? "Partial boundary day"
            : "Inside observed range"
          : "Outside observed range",
      ];
    });
  renderTable("calendar-table", ["Date", "Recorded plays", "Coverage"], rows);
}

function renderRhythm() {
  if (!state.data.activity) return;
  charts.rhythm(state.data.activity, $("rhythm-mode").value, context());
  renderTable(
    "rhythm-table",
    [
      "Weekday",
      "Local hour",
      "Recorded plays",
      "Covered hours",
      "Plays / covered hour",
    ],
    state.data.activity.hours.map((item) => {
      const button = element("button", weekdays[item.weekday], "entity-button");
      button.type = "button";
      button.dataset.weekday = item.weekday;
      button.dataset.hour = item.hour;
      return [
        button,
        `${String(item.hour).padStart(2, "0")}:00`,
        number(item.plays),
        item.occurrences.toFixed(2),
        item.average.toFixed(2),
      ];
    }),
  );
}

function renderTasteTables() {
  const evolution = state.data.evolution;
  renderTable(
    "evolution-table",
    ["Period", ...evolution.series.map((item) => item.name)],
    evolution.buckets.map((bucket, index) => [
      bucket,
      ...evolution.series.map((item) => number(item.counts[index])),
    ]),
  );
  renderTable(
    "breadth-table",
    ["Period", "Artists", "Tracks", "Top-artist share"],
    evolution.buckets.map((bucket, index) => [
      bucket,
      number(evolution.breadth[index].artists),
      number(evolution.breadth[index].tracks),
      percent(evolution.breadth[index].top_artist_share),
    ]),
  );
  const comparison = state.data.comparison;
  $("comparison-description").textContent =
    `Selected period: ${number(comparison.current_total)} plays. Previous period ${comparison.previous_start} → ${comparison.previous_end}: ${number(comparison.previous_total)} plays.${comparison.previous_covered ? "" : " The earlier period extends beyond fully observed source coverage."} The table shows count and share changes separately.`;
  renderTable(
    "comparison-table",
    [
      "Artist",
      "Previous plays",
      "Selected plays",
      "Previous share",
      "Selected share",
      "Share change (pp)",
    ],
    comparison.items.map((item) => [
      entityButton(item, "artist"),
      number(item.previous),
      number(item.current),
      percent(item.previous_share),
      percent(item.current_share),
      ((item.current_share - item.previous_share) * 100).toFixed(1),
    ]),
  );
}

function renderDiscovery() {
  const data = state.data.discovery;
  $("discovery-description").textContent = data.observed_through
    ? `Follow-up uses complete calendar days through ${data.observed_through}. Pending artists are excluded from each return-rate denominator; a partial latest day is not treated as complete.`
    : "No recorded artists in this publication.";
  renderTable(
    "discovery-table",
    [
      "First-observed month",
      "Artists",
      "7-day returns",
      "30-day returns",
      "90-day returns",
    ],
    data.cohorts.map((item) => [
      item.month,
      number(item.artists),
      returnRate(item.returned_7, item.eligible_7, item.artists),
      returnRate(item.returned_30, item.eligible_30, item.artists),
      returnRate(item.returned_90, item.eligible_90, item.artists),
    ]),
  );
}

function renderRediscovery() {
  const data = state.data.rediscovery;
  $("rediscovery-description").textContent =
    `Analysis date: ${data.as_of}. ${number(data.total)} matching favorites; showing up to 100 with the most historical plays. Later scrobbles are excluded.`;
  renderTable(
    "rediscovery-table",
    [
      "Favorite / artist",
      "Historical plays",
      "Last recorded",
      "Days since last",
    ],
    data.items.map((item) => [
      entityButton(item.entity, $("rediscovery-kind").value),
      number(item.entity.plays),
      recordedTime(item.entity.last_ms, state.timezone),
      number(item.days_since_last),
    ]),
  );
}

function rankingQuery() {
  return {
    kind: $("rank-kind").value,
    q: $("rank-search").value,
    page: state.rankingPage,
    order: $("rank-order").value,
  };
}

function rediscoveryQuery() {
  return {
    kind: $("rediscovery-kind").value,
    minimum_plays: $("minimum-plays").value,
    minimum_gap: $("minimum-gap").value,
  };
}

function pageControls(prefix, data) {
  const last = Math.max(1, Math.ceil(data.total / data.limit));
  $(prefix + "-page").textContent =
    `Page ${number(data.page)} of ${number(last)} · ${number(data.total)} results`;
  $(prefix + "-previous").disabled = data.page <= 1;
  $(prefix + "-next").disabled = data.page >= last;
}

async function openEntity(kind, key) {
  if (
    !["artist", "album", "track"].includes(kind) ||
    !/^[a-f0-9]{64}$/.test(key || "")
  )
    return;
  state.selected = { kind, key };
  state.recordsPage = 1;
  persist();
  state.detailController?.abort();
  state.detailController = new AbortController();
  const controller = state.detailController;
  state.detailData = null;
  state.data.records = null;
  document.querySelector('#detail [data-csv="records"]').disabled = true;
  $("detail-title").textContent = "Loading listening history…";
  $("detail-description").textContent = "";
  $("detail-facts").replaceChildren();
  $("records-table").replaceChildren();
  $("related-table").replaceChildren();
  $("detail-chart").hidden = true;
  $("detail-related").hidden = true;
  $("detail-loading").textContent = "Reading the selected history…";
  if (!$("detail").open) $("detail").showModal();
  try {
    const data = await analytics(
      `entities/${kind}/${key}`,
      {},
      controller.signal,
    );
    if (controller.signal.aborted || controller !== state.detailController)
      return;
    state.detailData = data;
    $("detail-title").textContent = data.lifetime.name;
    $("detail-kind").textContent = `${kind.toUpperCase()} / RECORDED HISTORY`;
    $("detail-description").textContent =
      `${kind === "artist" ? "" : data.lifetime.artist + " · "}Lifetime means all available history through ${state.to}. Selected counts use ${state.from} → ${state.to}.`;
    const facts = [
      [number(data.lifetime.plays), "Lifetime recorded plays"],
      [number(data.overview.counts.scrobbles), "Plays in selection"],
      [localDay(data.lifetime.first_ms, state.timezone), "First recorded"],
      [localDay(data.lifetime.last_ms, state.timezone), "Last recorded"],
    ];
    for (const [value, label] of facts) {
      const item = element("div");
      item.append(element("strong", value), element("span", label));
      $("detail-facts").append(item);
    }
    if (kind === "artist") {
      const button = element(
        "button",
        "Filter all views to this artist",
        "small-button",
      );
      button.addEventListener("click", () => {
        state.artist = key;
        state.artistName = data.lifetime.name;
        $("detail").close();
        state.rankingPage = 1;
        loadSelection();
      });
      $("detail-facts").append(button);
    }
    $("detail-chart").hidden = false;
    charts.detail(data.activity, context());
    $("detail-related").hidden = kind === "track";
    rankingTable("related-table", data.related, "track");
    state.data.records = data.records;
    document.querySelector('#detail [data-csv="records"]').disabled = false;
    recordsTable(data.records, state.timezone);
    pageControls("records", data.records);
    $("detail-loading").textContent = "";
  } catch (error) {
    if (error.name !== "AbortError" && error.status !== 401)
      $("detail-loading").textContent = error.message;
  }
}

async function openRecords() {
  state.selected = null;
  state.detailData = null;
  state.recordsPage = 1;
  persist();
  $("detail-title").textContent = "Recorded plays";
  $("detail-kind").textContent = "YOUR SELECTION";
  $("detail-description").textContent =
    `${state.from} → ${state.to} · ${state.timezone}`;
  $("detail-facts").replaceChildren();
  $("detail-chart").hidden = true;
  $("detail-related").hidden = true;
  if (!$("detail").open) $("detail").showModal();
  await loadRecords();
}

async function loadRecords() {
  state.detailController?.abort();
  state.detailController = new AbortController();
  const controller = state.detailController;
  state.data.records = null;
  document.querySelector('#detail [data-csv="records"]').disabled = true;
  $("detail-loading").textContent = "Loading recorded plays…";
  try {
    const extra = { page: state.recordsPage, limit: state.selected ? 25 : 50 };
    if (state.selected) Object.assign(extra, state.selected);
    const data = await analytics("scrobbles", extra, controller.signal);
    if (controller.signal.aborted || controller !== state.detailController)
      return;
    state.data.records = data;
    document.querySelector('#detail [data-csv="records"]').disabled = false;
    recordsTable(data, state.timezone);
    pageControls("records", data);
    $("detail-loading").textContent = "";
  } catch (error) {
    if (error.name !== "AbortError" && error.status !== 401)
      $("detail-loading").textContent = error.message;
  }
}

function selectDay(day) {
  state.from = day;
  state.to = day;
  state.preset = null;
  state.rankingPage = 1;
  loadSelection().then(() => openRecords());
}

function selectRhythm(weekday, hour) {
  state.weekday = Number(weekday);
  state.hour = Number(hour);
  state.rankingPage = 1;
  loadSelection();
}

function exportData(name) {
  const data = state.data;
  let headers = [],
    rows = [];
  if (name === "calendar" && data.activity) {
    headers = [
      "Local date",
      "Recorded plays",
      "Inside source bounds",
      "Partial boundary day",
    ];
    rows = data.activity.days.map((item) => [
      item.day,
      item.plays,
      item.covered,
      item.partial,
    ]);
  }
  if (name === "rhythm" && data.activity) {
    headers = [
      "Weekday (Monday=0)",
      "Local hour",
      "Recorded plays",
      "Covered hours",
      "Plays per covered hour",
    ];
    rows = data.activity.hours.map((item) => [
      item.weekday,
      item.hour,
      item.plays,
      item.occurrences,
      item.average,
    ]);
  }
  if (name === "rankings" && data.rankings) {
    headers = ["Name", "Artist", "Recorded plays", "Share", "Identity"];
    rows = data.rankings.items.map((item) => [
      item.name,
      item.artist,
      item.plays,
      item.share,
      item.key,
    ]);
  }
  if (name === "evolution" && data.evolution) {
    headers = ["Period", ...data.evolution.series.map((item) => item.name)];
    rows = data.evolution.buckets.map((bucket, index) => [
      bucket,
      ...data.evolution.series.map((item) => item.counts[index]),
    ]);
  }
  if (name === "breadth" && data.evolution) {
    headers = ["Period", "Artists", "Tracks", "Top artist share"];
    rows = data.evolution.buckets.map((bucket, index) => [
      bucket,
      data.evolution.breadth[index].artists,
      data.evolution.breadth[index].tracks,
      data.evolution.breadth[index].top_artist_share,
    ]);
  }
  if (name === "comparison" && data.comparison) {
    headers = [
      "Artist",
      "Previous plays",
      "Selected plays",
      "Previous share",
      "Selected share",
    ];
    rows = data.comparison.items.map((item) => [
      item.name,
      item.previous,
      item.current,
      item.previous_share,
      item.current_share,
    ]);
  }
  if (name === "discovery" && data.discovery) {
    headers = [
      "Month",
      "Artists",
      "Eligible 7 days",
      "Returned 7 days",
      "Eligible 30 days",
      "Returned 30 days",
      "Eligible 90 days",
      "Returned 90 days",
    ];
    rows = data.discovery.cohorts.map((item) => [
      item.month,
      item.artists,
      item.eligible_7,
      item.returned_7,
      item.eligible_30,
      item.returned_30,
      item.eligible_90,
      item.returned_90,
    ]);
  }
  if (name === "rediscovery" && data.rediscovery) {
    headers = [
      "Name",
      "Artist",
      "Historical plays",
      "Days since last",
      "First recorded UTC",
      "Last recorded UTC",
    ];
    rows = data.rediscovery.items.map((item) => [
      item.entity.name,
      item.entity.artist,
      item.entity.plays,
      item.days_since_last,
      new Date(item.entity.first_ms).toISOString(),
      new Date(item.entity.last_ms).toISOString(),
    ]);
  }
  if (name === "records" && data.records) {
    headers = [
      "Recorded UTC",
      "Track",
      "Artist",
      "Album",
      "Source row ordinal",
    ];
    rows = data.records.items.map((item) => [
      new Date(item.timestamp_ms).toISOString(),
      item.track,
      item.artist,
      item.album,
      item.ordinal,
    ]);
  }
  if (headers.length) exportCSV(name, headers, rows, context());
}

let artistTimer;
let artistController;
async function searchArtists() {
  const search = $("artist-search").value.trim();
  artistController?.abort();
  if (search.length < 2 || !state.metadata || state.metadata.first_ms == null) {
    $("artist-results").hidden = true;
    return;
  }
  artistController = new AbortController();
  const snapshot = state.snapshot;
  try {
    const data = await request(
      "/lastfm/analytics/rankings",
      {
        snapshot,
        from: localDay(state.metadata.first_ms, state.timezone),
        to: localDay(state.metadata.last_ms, state.timezone),
        tz: state.timezone,
        kind: "artist",
        q: search,
        limit: 10,
      },
      artistController.signal,
    );
    if (
      snapshot !== state.snapshot ||
      $("artist-search").value.trim() !== search
    )
      return;
    const target = $("artist-results");
    target.replaceChildren();
    for (const item of data.data.items) {
      const button = element(
        "button",
        `${item.name} · ${number(item.plays)} plays`,
      );
      button.type = "button";
      button.addEventListener("click", () => {
        state.artist = item.key;
        state.artistName = item.name;
        target.hidden = true;
        state.rankingPage = 1;
        loadSelection();
      });
      target.append(button);
    }
    if (!data.data.items.length)
      target.append(element("p", "No matching recorded artist.", "empty"));
    target.hidden = false;
  } catch (error) {
    if (error.name !== "AbortError" && error.status !== 401)
      $("artist-results").hidden = true;
  }
}

$("login").addEventListener("submit", (event) => {
  event.preventDefault();
  state.password = $("password").value;
  authenticate();
});
$("lock").addEventListener("click", () => showLogin());
$("retry").addEventListener("click", () =>
  state.authenticated
    ? checkStatus(true).then(() => loadSelection())
    : authenticate(),
);
$("filters").addEventListener("submit", (event) => {
  event.preventDefault();
  const timezone = $("timezone").value.trim();
  try {
    new Intl.DateTimeFormat("en", { timeZone: timezone });
  } catch {
    $("timezone").setCustomValidity(
      "Choose a valid IANA timezone, such as Europe/Berlin or UTC.",
    );
    $("timezone").reportValidity();
    return;
  }
  state.from = $("from").value;
  state.to = $("to").value;
  state.timezone = timezone;
  state.timezoneNotice = "";
  state.preset = null;
  state.rankingPage = 1;
  loadSelection();
});
$("timezone").addEventListener("input", () =>
  $("timezone").setCustomValidity(""),
);
$("reset").addEventListener("click", () => {
  state.artist = null;
  state.artistName = "";
  state.weekday = null;
  state.hour = null;
  state.timezone = "Europe/Berlin";
  state.rankingPage = 1;
  applyPreset("year");
  loadSelection();
});
$("artist-search").addEventListener("input", () => {
  clearTimeout(artistTimer);
  artistTimer = setTimeout(searchArtists, 250);
});
$("artist-search").addEventListener("keydown", (event) => {
  if (event.key === "Escape") $("artist-results").hidden = true;
});
$("rank-kind").addEventListener("change", () => {
  state.rankingPage = 1;
  loadSelection();
});
$("rank-order").addEventListener("change", () => {
  state.rankingPage = 1;
  loadSelection();
});
let rankTimer;
$("rank-search").addEventListener("input", () => {
  clearTimeout(rankTimer);
  rankTimer = setTimeout(() => {
    state.rankingPage = 1;
    loadSelection();
  }, 300);
});
$("rank-previous").addEventListener("click", () => {
  state.rankingPage--;
  loadSelection();
});
$("rank-next").addEventListener("click", () => {
  state.rankingPage++;
  loadSelection();
});
$("calendar-year").addEventListener("change", renderCalendar);
$("rhythm-mode").addEventListener("change", renderRhythm);
$("grain").addEventListener("change", () => loadSelection());
$("evolution-mode").addEventListener("change", () => {
  if (state.data.evolution)
    charts.evolution(
      state.data.evolution,
      $("evolution-mode").value,
      context(),
    );
});
$("rediscovery-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  loadSelection();
});
$("close-detail").addEventListener("click", () => $("detail").close());
$("detail").addEventListener("close", () => {
  state.detailController?.abort();
  state.selected = null;
  state.detailData = null;
  persist();
});
$("records-previous").addEventListener("click", () => {
  state.recordsPage--;
  loadRecords();
});
$("records-next").addEventListener("click", () => {
  state.recordsPage++;
  loadRecords();
});
$("all-records").addEventListener("click", openRecords);

document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest("button");
  if (button?.dataset.preset) {
    applyPreset(button.dataset.preset);
    loadSelection();
  }
  if (button?.dataset.tab) {
    if (state.tab !== button.dataset.tab) charts.clearCharts();
    state.tab = button.dataset.tab;
    loadSelection();
  }
  if (button?.dataset.entityKey)
    openEntity(button.dataset.entityKind, button.dataset.entityKey);
  if (button?.dataset.day) selectDay(button.dataset.day);
  if (button?.dataset.weekday !== undefined)
    selectRhythm(button.dataset.weekday, button.dataset.hour);
  if (button?.dataset.chartExport)
    charts.exportChart(button.dataset.chartExport, context());
  if (button?.dataset.csv) exportData(button.dataset.csv);
  if (!event.target.closest(".artist-control"))
    $("artist-results").hidden = true;
});
document.addEventListener("listening:select", (event) => {
  const detail = event.detail;
  if (detail.type === "entity") openEntity(detail.kind, detail.key);
  if (detail.type === "day") selectDay(detail.day);
  if (detail.type === "rhythm") selectRhythm(detail.weekday, detail.hour);
});
window.addEventListener("resize", charts.resizeCharts);
setInterval(() => {
  if (state.authenticated && !document.hidden) checkStatus();
}, 60000);
authenticate();

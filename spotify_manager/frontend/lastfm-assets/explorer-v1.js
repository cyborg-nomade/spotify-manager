import * as charts from "./charts-v1.js?v=7";
import * as library from "./library-v1.js?v=7";
import * as tags from "./tags-v1.js?v=7";
import * as origins from "./origins-v1.js?v=9";
import * as quilt from "./quilt-v1.js?v=10";
import * as sessions from "./sessions-v1.js?v=7";
import { eraHighlight, groupedEraOrder } from "./eras-v1.js?v=7";
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
} from "./tables-v1.js?v=7";

const $ = (id) => document.getElementById(id);
const parameters = new URLSearchParams(location.search);
const tabs = [
  "overview",
  "taste",
  "discovery",
  "rediscovery",
  "capsule",
  "library",
  "tags",
  "origins",
  "quilt",
  "sessions",
];
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
  eraReference: parameters.get("era_ref"),
  eraGrouped: parameters.get("era_order") === "grouped",
  eraThreshold: Math.round(
    Math.max(0, Math.min(100, Number(parameters.get("era_min")) || 0)),
  ),
  eraOrder: [],
  groupedOrder: null,
  sessionPage: 1,
  sessionRecordPage: 1,
  selectedSession: /^\d{1,13}$/.test(parameters.get("session") || "")
    ? parameters.get("session")
    : null,
  sessionContext: null,
  sessionController: null,
  sessionDetail: null,
  rankingPage: 1,
  libraryPage: 1,
  libraryForce: false,
  libraryTimer: null,
  tagPage: 1,
  originPage: 1,
  originTimer: null,
  quiltTimer: null,
  tagTimer: null,
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
  state.selectedSession = null;
  state.snapshot = null;
  state.metadata = null;
  state.data = {};
  state.detailData = null;
  state.controller?.abort();
  quilt.reset();
  sessions.reset();
  state.sessionController?.abort();
  state.sessionDetail = null;
  state.detailController?.abort();
  clearTimeout(state.pollTimer);
  clearTimeout(state.libraryTimer);
  clearTimeout(state.tagTimer);
  clearTimeout(state.originTimer);
  clearTimeout(state.quiltTimer);
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

async function request(path, query, signal, method = "GET") {
  const suffix = query ? `?${new URLSearchParams(query)}` : "";
  const response = await fetch(path + suffix, {
    method,
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
    throw Object.assign(new Error(message), {
      status: response.status,
      conflict: response.headers.get("X-Listening-Conflict"),
    });
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
  state.libraryPage = 1;
  state.tagPage = 1;
  state.originPage = 1;
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
  if (state.tab === "library") {
    values.library_kind = $("library-kind").value;
    values.library_status = $("library-status").value;
    values.library_min = $("library-minimum").value;
    if ($("library-search").value) values.library_q = $("library-search").value;
  }
  if (state.tab === "sessions") {
    values.session_gap = $("session-gap").value;
    values.session_min = $("session-minimum").value;
    values.session_order = $("session-order").value;
    if (state.selectedSession !== null) values.session = state.selectedSession;
  }
  if (state.tab === "quilt") {
    values.quilt_size = $("quilt-size").value;
    values.quilt_labels = String($("quilt-labels").checked);
    if ($("quilt-search").value) values.quilt_q = $("quilt-search").value;
  }
  if (state.tab === "origins") {
    values.origin_metric = $("origin-metric").value;
    values.origin_evidence = $("origin-evidence").value;
    if ($("origin-country").value)
      values.origin_country = $("origin-country").value;
    if ($("origin-search").value) values.origin_q = $("origin-search").value;
  }
  if (state.tab === "tags") {
    values.tags_per_artist = $("tag-per-artist").value;
    values.tag_display = $("tag-display").value;
    if ($("tag-filter").value) values.tag = $("tag-filter").value;
    if ($("tag-search").value) values.tag_q = $("tag-search").value;
  }
  if (state.tab === "capsule" && state.eraReference)
    values.era_ref = state.eraReference;
  if (state.tab === "capsule") {
    values.era_order = state.eraGrouped ? "grouped" : "chronological";
    values.era_min = state.eraThreshold;
  }
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

function libraryQuery() {
  return {
    kind: $("library-kind").value,
    status: $("library-status").value,
    minimum_plays: $("library-minimum").value,
    q: $("library-search").value,
    page: state.libraryPage,
    limit: 25,
  };
}

async function loadLibrary() {
  try {
    const status = await request(
      "/lastfm/analytics/library/status",
      { refresh: state.libraryForce },
      state.controller.signal,
    );
    state.libraryForce = false;
    if (!status.snapshot)
      return { unavailable: status.message, checking: status.checking };
    const result = await analytics("library", {
      ...libraryQuery(),
      library_snapshot: status.snapshot,
    });
    if (status.state === "stale") result.unavailable = status.message;
    return result;
  } catch (error) {
    if (
      error.name === "AbortError" ||
      error.status === 401 ||
      error.status === 409
    )
      throw error;
    return {
      unavailable:
        "Collection evidence could not be loaded. Your listening history is still available. Use Check publications to retry.",
    };
  }
}

function tagQuery() {
  const values = {
    per_artist: $("tag-per-artist").value,
    q: $("tag-search").value,
    page: state.tagPage,
    limit: 25,
  };
  if ($("tag-filter").value) values.tag = $("tag-filter").value;
  return values;
}

async function loadTags(recoverMetadata = true) {
  try {
    const status = await request(
      "/lastfm/analytics/tags/status",
      null,
      state.controller.signal,
    );
    const data = await analytics("tags", {
      ...tagQuery(),
      metadata_snapshot: status.metadata_snapshot,
    });
    return { ...data, lookup: status };
  } catch (error) {
    if (error.status === 409 && error.conflict === "tags") {
      if (recoverMetadata) return loadTags(false);
      return {
        unavailable:
          "Tag metadata changed repeatedly. History remains available; retry this view shortly.",
      };
    }
    if (
      error.name === "AbortError" ||
      error.status === 401 ||
      error.status === 409
    )
      throw error;
    return {
      unavailable:
        "Cached tag metadata is unavailable. Your listening history remains available; retry this view later.",
    };
  }
}

function scheduleTagPoll() {
  clearTimeout(state.tagTimer);
  clearTimeout(state.originTimer);
  clearTimeout(state.quiltTimer);
  state.tagTimer = setTimeout(pollTagLookup, 2000);
}

async function pollTagLookup() {
  if (state.tab !== "tags" || !state.authenticated) return;
  const epoch = state.epoch;
  try {
    const status = await request(
      "/lastfm/analytics/tags/status",
      null,
      state.controller?.signal,
    );
    if (epoch !== state.epoch || state.tab !== "tags") return;
    tags.progress(status);
    if (["running", "cancelling"].includes(status.state) || $("detail").open)
      scheduleTagPoll();
    else if (status.metadata_snapshot !== state.data.tags?.metadata_snapshot)
      await loadSelection();
  } catch (error) {
    if (error.status !== 401 && error.name !== "AbortError")
      $("tag-progress").textContent =
        "Lookup progress is unavailable. Cached history remains visible; retry later.";
  }
}

async function tagAction(cancel = false) {
  try {
    const parameters = cancel
      ? null
      : query({
          limit: $("tag-batch-size").value,
          force: $("tag-force").checked,
        });
    const status = await request(
      `/lastfm/analytics/tags/${cancel ? "cancel" : "refresh"}`,
      parameters,
      undefined,
      "POST",
    );
    if (!state.authenticated || state.tab !== "tags") return;
    tags.progress(status);
    scheduleTagPoll();
  } catch (error) {
    if (error.status !== 401)
      $("tag-progress").textContent =
        error.message ||
        "Tag lookup could not start. Cached history remains available.";
  }
}

function quiltQuery() {
  return { size: $("quilt-size").value, q: $("quilt-search").value };
}

async function loadQuilt(recoverMetadata = true) {
  try {
    const status = await request(
      "/lastfm/analytics/quilt/status",
      null,
      state.controller.signal,
    );
    const data = await analytics("quilt", {
      ...quiltQuery(),
      metadata_snapshot: status.metadata_snapshot,
    });
    return { ...data, lookup: status };
  } catch (error) {
    if (error.status === 409 && error.conflict === "covers") {
      if (recoverMetadata) return loadQuilt(false);
      return {
        unavailable:
          "Cover metadata changed repeatedly. Your listening history remains available; reload the quilt shortly.",
      };
    }
    if (error.name === "AbortError" || [401, 409].includes(error.status))
      throw error;
    return {
      unavailable:
        "Cached cover metadata is unavailable. Your listening history remains available; retry this view later.",
    };
  }
}

function scheduleQuiltPoll(delay = 2000) {
  clearTimeout(state.quiltTimer);
  state.quiltTimer = setTimeout(pollQuiltLookup, delay);
}

function appliedQuiltQuery() {
  const { size, search } = state.data.quilt.options;
  return { size, q: search };
}

async function updateQuiltArtwork(status, signal) {
  const data = await analytics(
    "quilt",
    { ...appliedQuiltQuery(), metadata_snapshot: status.metadata_snapshot },
    signal,
  );
  if (signal.aborted || state.tab !== "quilt") return;
  state.data.quilt = { ...data, lookup: status };
  quilt.render(state.data.quilt, context(), state.password, signal);
}

function isTemporaryLookupStatusError(error) {
  if (error.name === "AbortError") return false;
  return error.status == null || error.status === 429 || error.status >= 500;
}

async function pollQuiltLookup() {
  if (state.tab !== "quilt" || !state.authenticated) return;
  const epoch = state.epoch;
  const signal = state.controller.signal;
  try {
    const status = await request(
      "/lastfm/analytics/quilt/status",
      null,
      signal,
    );
    if (epoch !== state.epoch || signal.aborted || state.tab !== "quilt")
      return;
    quilt.progress(status);
    if (
      !$("detail").open &&
      state.data.quilt?.items &&
      status.metadata_snapshot !== state.data.quilt?.metadata_snapshot
    )
      await updateQuiltArtwork(status, signal);
    if (
      !signal.aborted &&
      state.tab === "quilt" &&
      (["running", "cancelling"].includes(status.state) || $("detail").open)
    )
      scheduleQuiltPoll();
  } catch (error) {
    if (epoch !== state.epoch || signal.aborted || state.tab !== "quilt")
      return;
    if (error.status === 409 && error.conflict === "covers") {
      scheduleQuiltPoll();
      return;
    }
    if (isTemporaryLookupStatusError(error)) {
      $("quilt-progress").textContent =
        "Cover lookup progress is temporarily unavailable. Checking again…";
      scheduleQuiltPoll(5000);
    } else if (error.status !== 401 && error.name !== "AbortError") {
      $("quilt-progress").textContent =
        "Cover lookup progress could not be read. Reload the quilt to check again.";
    }
  }
}

async function quiltAction(cancel = false) {
  try {
    const parameters = cancel
      ? null
      : query({
          ...appliedQuiltQuery(),
          limit: $("quilt-batch-size").value,
          force: $("quilt-force").checked,
        });
    const status = await request(
      `/lastfm/analytics/quilt/${cancel ? "cancel" : "refresh"}`,
      parameters,
      undefined,
      "POST",
    );
    if (!state.authenticated || state.tab !== "quilt") return;
    quilt.progress(status);
    scheduleQuiltPoll();
  } catch (error) {
    if (error.status !== 401)
      $("quilt-progress").textContent =
        error.message ||
        "Cover lookup could not start. Cached artwork remains available.";
  }
}

function originQuery() {
  const values = {
    evidence: $("origin-evidence").value,
    q: $("origin-search").value,
    page: state.originPage,
    limit: 25,
  };
  if ($("origin-country").value) values.country = $("origin-country").value;
  return values;
}

async function loadOrigins(recoverMetadata = true) {
  try {
    const status = await request(
      "/lastfm/analytics/origins/status",
      null,
      state.controller.signal,
    );
    const data = await analytics("origins", {
      ...originQuery(),
      metadata_snapshot: status.metadata_snapshot,
    });
    return {
      ...data,
      lookup: status,
      map_ready: await origins.prepare(state.controller.signal),
    };
  } catch (error) {
    if (error.status === 409 && error.conflict === "origins") {
      if (recoverMetadata) return loadOrigins(false);
      return {
        unavailable:
          "Country metadata changed repeatedly. History remains available; retry this view shortly.",
      };
    }
    if (
      error.name === "AbortError" ||
      error.status === 401 ||
      error.status === 409
    )
      throw error;
    return {
      unavailable:
        "Cached country metadata is unavailable. Your listening history remains available; retry this view later.",
    };
  }
}

function scheduleOriginPoll(delay = 2000) {
  clearTimeout(state.originTimer);
  clearTimeout(state.quiltTimer);
  state.originTimer = setTimeout(pollOriginLookup, delay);
}

async function pollOriginLookup() {
  if (state.tab !== "origins" || !state.authenticated) return;
  const epoch = state.epoch;
  try {
    const status = await request(
      "/lastfm/analytics/origins/status",
      null,
      state.controller?.signal,
    );
    if (epoch !== state.epoch || state.tab !== "origins") return;
    origins.progress(status);
    if (
      !$("detail").open &&
      status.metadata_snapshot !== state.data.origins?.metadata_snapshot
    )
      await loadSelection();
    else if (
      ["running", "cancelling"].includes(status.state) ||
      $("detail").open
    )
      scheduleOriginPoll();
  } catch (error) {
    if (epoch !== state.epoch || state.tab !== "origins") return;
    if (isTemporaryLookupStatusError(error)) {
      $("origin-progress").textContent =
        "Country lookup progress is temporarily unavailable. Checking again…";
      scheduleOriginPoll(5000);
    } else if (error.status !== 401 && error.name !== "AbortError") {
      $("origin-progress").textContent =
        "Country lookup progress could not be read. Reload the map to check again.";
    }
  }
}

async function originAction(action) {
  try {
    const parameters = {
      refresh: query({
        limit: $("origin-batch-size").value,
        force: $("origin-force").checked,
      }),
      backfill: new URLSearchParams({ snapshot: state.snapshot }),
      cancel: null,
    };
    const status = await request(
      `/lastfm/analytics/origins/${action}`,
      parameters[action],
      undefined,
      "POST",
    );
    if (!state.authenticated || state.tab !== "origins") return;
    origins.progress(status);
    scheduleOriginPoll();
  } catch (error) {
    if (error.status !== 401)
      $("origin-progress").textContent =
        error.message ||
        "Origin lookup could not start. Cached history remains available.";
  }
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
      state.libraryPage = 1;
      state.tagPage = 1;
      state.originPage = 1;
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
    .querySelectorAll(
      "[data-csv],[data-chart-export],[data-quilt-export],[data-session-export]",
    )
    .forEach((button) => (button.disabled = value));
  if (!value && state.tab === "sessions") {
    document.querySelectorAll("[data-session-export]").forEach((button) => {
      button.disabled =
        !state.data.sessions ||
        (button.dataset.sessionExport === "records" && !state.sessionDetail);
    });
  }
  if (!value && state.tab === "library") {
    $("library-export").disabled = !state.data.library?.items;
    document.querySelector('[data-chart-export="library"]').disabled =
      !state.data.library?.items;
  }
  if (!value && state.tab === "tags") {
    document
      .querySelectorAll("#tab-tags [data-csv], #tab-tags [data-chart-export]")
      .forEach((button) => (button.disabled = !state.data.tags?.items));
  }
  if (!value && state.tab === "quilt") {
    $("quilt-png").disabled = !state.data.quilt?.items?.length;
    $("quilt-csv").disabled = !state.data.quilt?.items;
  }
  if (!value && state.tab === "origins") {
    document
      .querySelectorAll("#tab-origins [data-csv]")
      .forEach((button) => (button.disabled = !state.data.origins?.items));
    document.querySelector('[data-chart-export="origins"]').disabled =
      !state.data.origins?.items || !state.data.origins?.map_ready;
  }
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
  clearTimeout(state.libraryTimer);
  clearTimeout(state.tagTimer);
  clearTimeout(state.originTimer);
  clearTimeout(state.quiltTimer);
  state.controller?.abort();
  quilt.reset();
  sessions.reset();
  state.sessionController?.abort();
  state.sessionDetail = null;
  state.detailController?.abort();
  const revision = ++state.revision;
  state.controller = new AbortController();
  state.data = {};
  $("view-error").hidden = true;
  if (["discovery", "rediscovery", "capsule"].includes(state.tab)) {
    state.weekday = null;
    state.hour = null;
  }
  configure();
  const sessionContext = JSON.stringify(
    query({ gap_minutes: $("session-gap").value }),
  );
  if (state.sessionContext && state.sessionContext !== sessionContext) {
    state.selectedSession = null;
    state.sessionPage = 1;
  }
  state.sessionContext = sessionContext;
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
    if (state.tab === "capsule")
      tasks.push(analytics("on-this-day"), analytics("eras"));
    if (state.tab === "library") tasks.push(loadLibrary());
    if (state.tab === "tags") tasks.push(loadTags());
    if (state.tab === "origins") tasks.push(loadOrigins());
    if (state.tab === "quilt") tasks.push(loadQuilt());
    if (state.tab === "sessions")
      tasks.push(analytics("sessions", sessionQuery()));
    const results = await Promise.all(tasks);
    if (revision !== state.revision) return;
    renderOverview(results[0]);
    renderView(results.slice(1));
    if (state.tab === "sessions" && state.selectedSession !== null)
      await loadSessionRecords();
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
  if (state.tab === "sessions") {
    state.data.sessions = results[0];
    sessions.render(results[0], ctx);
  }
  if (state.tab === "quilt") {
    state.data.quilt = results[0];
    charts.clearCharts();
    quilt.render(results[0], ctx, state.password, state.controller.signal);
    if (["running", "cancelling"].includes(results[0].lookup?.state))
      scheduleQuiltPoll();
  }
  if (state.tab === "origins") {
    state.data.origins = results[0];
    origins.render(results[0], ctx);
    if (["running", "cancelling"].includes(results[0].lookup?.state))
      scheduleOriginPoll();
  }
  if (state.tab === "tags") {
    state.data.tags = results[0];
    tags.render(results[0], ctx);
    if (["running", "cancelling"].includes(results[0].lookup?.state))
      scheduleTagPoll();
  }
  if (state.tab === "library") {
    state.data.library = results[0];
    library.render(
      results[0],
      results[0].source?.kind || $("library-kind").value,
      ctx,
    );
    if (results[0].checking)
      state.libraryTimer = setTimeout(() => {
        if (state.tab === "library" && state.authenticated) loadSelection();
      }, 2000);
  }
  if (state.tab === "capsule") renderCapsule(results[0], results[1]);
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

function coverageLabel(item) {
  if (!item.covered) return "Outside observed range";
  return item.partial ? "Partial boundary period" : "Inside observed range";
}

function periodButton(item) {
  const button = element("button", item.label, "entity-button");
  button.type = "button";
  button.dataset.periodStart = item.start;
  button.dataset.periodEnd = item.end;
  button.disabled = !item.covered;
  return button;
}

function renderCapsule(anniversaries, eras) {
  state.data.anniversaries = anniversaries;
  state.data.eras = eras;
  const ctx = context();
  $("anniversary-description").textContent =
    `Anniversary: ${anniversaries.as_of.slice(5)} · earlier years before ${anniversaries.as_of}. Source coverage: ${anniversaries.observed_from || "none"} → ${anniversaries.observed_through || "none"} · ${state.timezone}. Zero means no recorded plays; dates outside coverage remain labeled.`;
  const archive = {
    ...ctx,
    from: anniversaries.observed_from || ctx.from,
    to: anniversaries.as_of,
  };
  charts.anniversaries(anniversaries, archive);
  renderTable(
    "anniversary-table",
    [
      "Local date",
      "Recorded plays",
      "Artists",
      "Leading artists (up to 5)",
      "Coverage",
    ],
    anniversaries.days.map((item) => {
      const button = element("button", item.day, "entity-button");
      button.type = "button";
      button.dataset.day = item.day;
      button.disabled = !item.covered;
      return [
        button,
        number(item.plays),
        number(item.artists),
        item.top_artists
          .map((artist) => `${artist.name} (${number(artist.plays)})`)
          .join(" · ") || "—",
        coverageLabel(item),
      ];
    }),
  );
  $("eras-description").textContent =
    `${eras.periods.length} ${eras.grain === "month" ? "monthly" : "yearly"} periods in the selected range. ${eras.grain === "year" ? "Selections longer than 240 months use calendar years to keep comparisons readable. " : ""}Partial selection and source boundaries are labeled. Select a matrix cell or use the period selector and table.`;
  state.groupedOrder = null;
  const fallback =
    eras.periods.findLast((item) => item.plays) || eras.periods.at(-1);
  if (!eras.periods.some((item) => item.label === state.eraReference))
    state.eraReference = fallback?.label;
  renderEraView();
}

function renderEraView() {
  const data = state.data.eras;
  if (!data) return;
  if (state.eraGrouped && !state.groupedOrder)
    state.groupedOrder = groupedEraOrder(data);
  state.eraOrder = state.eraGrouped
    ? state.groupedOrder
    : data.periods.map((_item, index) => index);
  $("era-grouped").checked = state.eraGrouped;
  $("era-threshold").value = state.eraThreshold;
  $("era-threshold-value").textContent = `${state.eraThreshold}%`;
  $("era-view-description").textContent =
    `${state.eraGrouped ? "Periods are grouped by similarity of their artist mix; empty periods appear last." : "Periods follow calendar order."} Comparisons below ${state.eraThreshold}% are dimmed. Gray self-comparisons are kept separate. Scores, tables, and exports retain all observations.`;
  $("era-reference").replaceChildren(
    ...state.eraOrder.map((index) => {
      const item = data.periods[index];
      return new Option(
        `${item.label}${item.plays ? "" : " · no recorded plays"}`,
        item.label,
      );
    }),
  );
  $("era-reference").value = state.eraReference;
  charts.eras(data, context(), {
    order: state.eraOrder,
    grouped: state.eraGrouped,
    threshold: state.eraThreshold / 100,
  });
  renderEraTable();
  persist();
}

function renderEraTable(comparison = null) {
  const data = state.data.eras;
  if (!data) return;
  const reference = data.periods.findIndex(
    (item) => item.label === state.eraReference,
  );
  if (reference < 0) return;
  $("era-reference").value = state.eraReference;
  const summary =
    comparison === null ? null : data.similarities[reference][comparison];
  $("era-comparison").textContent =
    comparison === null
      ? `Comparing every period with ${state.eraReference}. Open a period to inspect its recorded plays.`
      : `${state.eraReference} ↔ ${data.periods[comparison].label}: ${summary === null ? "not comparable (one or both periods have no recorded plays)" : percent(summary) + " artist-share similarity"}.`;
  renderTable(
    "eras-table",
    [
      "Period",
      "Recorded plays",
      "Artists",
      `Similarity to ${state.eraReference}`,
      "Coverage",
      "Highlight status",
    ],
    state.eraOrder.map((index) => {
      const item = data.periods[index];
      return [
        periodButton(item),
        number(item.plays),
        number(item.artists),
        data.similarities[reference][index] === null
          ? "Not comparable"
          : percent(data.similarities[reference][index]),
        coverageLabel(item),
        eraHighlight(
          data.similarities[reference][index],
          reference === index,
          state.eraThreshold / 100,
        ),
      ];
    }),
  );
}

async function selectPeriod(start, end) {
  state.from = start;
  state.to = end;
  state.preset = null;
  state.selected = null;
  state.tab = "overview";
  state.rankingPage = 1;
  state.libraryPage = 1;
  state.tagPage = 1;
  state.originPage = 1;
  charts.clearCharts();
  await loadSelection();
  await openRecords();
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

function boundedInteger(value, minimum, maximum, fallback) {
  const number = Number(value);
  return Number.isInteger(number) && number >= minimum && number <= maximum
    ? number
    : fallback;
}

function sessionQuery() {
  return {
    gap_minutes: $("session-gap").value,
    minimum_plays: $("session-minimum").value,
    order: $("session-order").value,
    page: state.sessionPage,
    limit: 25,
  };
}

function closeSession() {
  state.sessionController?.abort();
  state.selectedSession = null;
  state.sessionDetail = null;
  $("session-detail").hidden = true;
  $("session-records-table").replaceChildren();
  document.querySelector('[data-session-export="records"]').disabled = true;
  persist();
}

async function loadSessionRecords(scroll = false) {
  state.sessionController?.abort();
  if (
    state.selectedSession === null ||
    !state.authenticated ||
    state.tab !== "sessions"
  )
    return;
  const selected = state.selectedSession;
  const revision = state.revision;
  state.sessionController = new AbortController();
  const signal = state.sessionController.signal;
  state.sessionDetail = null;
  $("session-detail").hidden = false;
  $("session-records-table").replaceChildren();
  $("session-record-status").textContent = "Loading recorded session rows…";
  document.querySelector('[data-session-export="records"]').disabled = true;
  persist();
  try {
    const data = await analytics(
      `sessions/${selected}/records`,
      {
        gap_minutes: $("session-gap").value,
        page: state.sessionRecordPage,
        limit: 50,
      },
      signal,
    );
    if (
      signal.aborted ||
      revision !== state.revision ||
      selected !== state.selectedSession
    )
      return;
    state.sessionDetail = data;
    sessions.renderRecords(data, context());
    document.querySelector('[data-session-export="records"]').disabled = false;
    if (scroll) $("session-detail").scrollIntoView({ block: "start" });
  } catch (error) {
    if (signal.aborted || revision !== state.revision || error.status === 401)
      return;
    $("session-record-status").textContent =
      error.status === 404
        ? "This session is absent from the selected records and gap. Choose a session from the list."
        : "Session records are unavailable. Choose the session again to retry.";
  }
}

async function exportSessions(kind) {
  const data = state.data.sessions;
  if (!data) return;
  if (!["starts", "sizes"].includes(kind)) {
    sessions.csv(kind, data, context(), state.sessionDetail);
    return;
  }
  try {
    await sessions.png(kind, data, context());
  } catch {
    $("session-coverage").textContent =
      "The chart image could not be exported. Retry or export its complete data CSV.";
  }
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
        state.libraryPage = 1;
        state.tagPage = 1;
        state.originPage = 1;
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
  selectPeriod(day, day);
}

function selectRhythm(weekday, hour) {
  state.weekday = Number(weekday);
  state.hour = Number(hour);
  state.rankingPage = 1;
  state.libraryPage = 1;
  state.tagPage = 1;
  state.originPage = 1;
  loadSelection();
}

function exportData(name) {
  const data = state.data;
  let headers = [],
    rows = [];
  if (name === "origins" && data.origins?.items) {
    headers = [
      "Reported code",
      "Reported country",
      "Selected plays",
      "Artists",
      "Share of all selected plays",
    ];
    rows = origins.countriesCSV(data.origins);
  }
  if (name === "origin-artists" && data.origins?.items) {
    headers = [
      "Artist key",
      "Artist",
      "Actual selected plays",
      "Name/country evidence",
      "Exact-name candidates found",
      "Candidate IDs and reported places",
      "Retrieved at",
    ];
    rows = origins.artistsCSV(data.origins);
  }
  if (name === "tags" && data.tags?.items) {
    headers = ["Month", ...data.tags.series.map((series) => series.name)];
    rows = tags.evolutionCSV(data.tags);
  }
  if (name === "tag-artists" && data.tags?.items) {
    headers = [
      "Artist key",
      "Artist",
      "Actual selected plays",
      "Metadata coverage",
      "Ranked current community tags",
      "Retrieved at",
      "Source URL",
    ];
    rows = tags.artistsCSV(data.tags);
  }
  if (name === "library" && data.library?.items) {
    headers = [
      "History key",
      "Name",
      "Artist",
      "Selected plays",
      "First selected UTC milliseconds",
      "Last selected UTC milliseconds",
      "Name evidence",
      "Distinct candidates",
      "Displayed Spotify candidate URIs",
    ];
    rows = library.csv(data.library);
  }
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
  if (name === "anniversaries" && data.anniversaries) {
    headers = [
      "Local date",
      "Recorded plays",
      "Artists",
      "Inside source bounds",
      "Partial boundary day",
      "Leading artists (up to 5)",
      "Anniversary as of",
      "Observed from",
      "Observed through",
    ];
    rows = data.anniversaries.days.map((item) => [
      item.day,
      item.plays,
      item.artists,
      item.covered,
      item.partial,
      item.top_artists
        .map((artist) => `${artist.name} (${artist.plays})`)
        .join(" · "),
      data.anniversaries.as_of,
      data.anniversaries.observed_from,
      data.anniversaries.observed_through,
    ]);
  }
  if (name === "eras" && data.eras) {
    headers = [
      "Period",
      "Selected from",
      "Selected through",
      "Recorded plays",
      "Artists",
      "Inside source bounds",
      "Partial period",
      ...state.eraOrder.map((index) => data.eras.periods[index].label),
    ];
    rows = state.eraOrder.map((index) => {
      const item = data.eras.periods[index];
      return [
        item.label,
        item.start,
        item.end,
        item.plays,
        item.artists,
        item.covered,
        item.partial,
        ...state.eraOrder.map((column) =>
          data.eras.similarities[index][column] === null
            ? "Not comparable"
            : data.eras.similarities[index][column],
        ),
      ];
    });
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
  if (headers.length) {
    const ctx = context();
    if (["origins", "origin-artists"].includes(name)) {
      ctx.notes = origins.notes(data.origins);
      if (name === "origin-artists")
        ctx.notes.push(
          ["Country filter", data.origins.options.country || "All countries"],
          ["Evidence filter", data.origins.options.evidence],
          ["Artist search", data.origins.options.search],
          [
            "Export scope",
            `Current page ${data.origins.page}; ${data.origins.total} matching artists`,
          ],
        );
    }
    if (["tags", "tag-artists"].includes(name)) {
      ctx.notes = tags.notes(data.tags);
      if (name === "tag-artists")
        ctx.notes.push(
          ["Evidence filter", data.tags.options.tag || "All artists"],
          ["Artist search", data.tags.options.search],
          [
            "Export scope",
            `Current page ${data.tags.page}; ${data.tags.total} matching artists`,
          ],
        );
    }
    if (name === "library")
      ctx.notes = library.notes(data.library, data.library.options);
    if (name === "anniversaries")
      ctx.from = data.anniversaries.observed_from || ctx.from;
    if (name === "eras")
      ctx.notes = [
        [
          "Period ordering",
          state.eraGrouped
            ? "Grouped by similarity (average linkage)"
            : "Chronological",
        ],
        ["Highlight minimum (%)", state.eraThreshold],
        ["Color bands (%)", "<2; 2–5; 5–10; 10–20; 20–35; ≥35"],
        ["Values", "Full matrix; highlighting does not filter scores"],
      ];
    exportCSV(name, headers, rows, ctx);
  }
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
        state.libraryPage = 1;
        state.tagPage = 1;
        state.originPage = 1;
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
  state.libraryPage = 1;
  state.tagPage = 1;
  state.originPage = 1;
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
  state.libraryPage = 1;
  state.tagPage = 1;
  state.originPage = 1;
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
  state.libraryPage = 1;
  state.tagPage = 1;
  state.originPage = 1;
  loadSelection();
});
$("rank-order").addEventListener("change", () => {
  state.rankingPage = 1;
  state.libraryPage = 1;
  state.tagPage = 1;
  state.originPage = 1;
  loadSelection();
});
let rankTimer;
$("rank-search").addEventListener("input", () => {
  clearTimeout(rankTimer);
  rankTimer = setTimeout(() => {
    state.rankingPage = 1;
    state.libraryPage = 1;
    state.tagPage = 1;
    state.originPage = 1;
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
$("era-grouped").addEventListener("change", () => {
  state.eraGrouped = $("era-grouped").checked;
  renderEraView();
});
$("era-threshold").addEventListener("input", () => {
  $("era-threshold-value").textContent = `${$("era-threshold").value}%`;
});
$("era-threshold").addEventListener("change", () => {
  state.eraThreshold = Number($("era-threshold").value);
  renderEraView();
});
$("era-reference").addEventListener("change", () => {
  state.eraReference = $("era-reference").value;
  renderEraTable();
  persist();
});
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
$("library-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  state.libraryPage = 1;
  state.tagPage = 1;
  state.originPage = 1;
  loadSelection();
});
$("library-refresh").addEventListener("click", () => {
  state.libraryForce = true;
  loadSelection();
});
$("library-previous").addEventListener("click", () => {
  state.libraryPage--;
  loadSelection();
});
$("library-next").addEventListener("click", () => {
  state.libraryPage++;
  loadSelection();
});
document.addEventListener("listening-auth-required", () =>
  showLogin("Enter your app password to continue."),
);
$("session-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  state.sessionPage = 1;
  closeSession();
  loadSelection();
});
$("session-order").addEventListener("change", () => {
  if ($("session-filters").reportValidity()) {
    state.sessionPage = 1;
    loadSelection();
  }
});
$("session-previous").addEventListener("click", () => {
  state.sessionPage--;
  loadSelection();
});
$("session-next").addEventListener("click", () => {
  state.sessionPage++;
  loadSelection();
});
$("session-record-previous").addEventListener("click", () => {
  state.sessionRecordPage--;
  loadSessionRecords();
});
$("session-record-next").addEventListener("click", () => {
  state.sessionRecordPage++;
  loadSessionRecords();
});
$("session-close").addEventListener("click", closeSession);

$("quilt-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  loadSelection();
});
$("quilt-size").addEventListener("change", () => loadSelection());
$("quilt-labels").addEventListener("change", () => {
  quilt.labels();
  persist();
});
$("quilt-fetch").addEventListener("click", () => quiltAction());
$("quilt-cancel").addEventListener("click", () => quiltAction(true));
$("quilt-retry").addEventListener("click", () => loadSelection());
$("quilt-csv").addEventListener("click", () => {
  if (state.data.quilt?.items) quilt.csv(state.data.quilt, context());
});
$("quilt-png").addEventListener("click", async () => {
  if (!state.data.quilt?.items?.length) return;
  $("quilt-png").disabled = true;
  try {
    await quilt.png(state.data.quilt, context());
  } catch {
    $("quilt-images").textContent =
      "The image export could not finish. Retry or export the complete quilt CSV.";
  } finally {
    $("quilt-png").disabled =
      !state.authenticated || !state.data.quilt?.items?.length;
  }
});

$("origin-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  state.originPage = 1;
  loadSelection();
});
$("origin-metric").addEventListener("change", () => {
  if (state.data.origins?.items) origins.render(state.data.origins, context());
  persist();
});
$("origin-fetch").addEventListener("click", () => originAction("refresh"));
$("origin-backfill").addEventListener("click", () => originAction("backfill"));
$("origin-cancel").addEventListener("click", () => originAction("cancel"));
$("origin-previous").addEventListener("click", () => {
  state.originPage--;
  loadSelection();
});
$("origin-next").addEventListener("click", () => {
  state.originPage++;
  loadSelection();
});
$("tag-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  state.tagPage = 1;
  state.originPage = 1;
  loadSelection();
});
$("tag-display").addEventListener("change", () => {
  if (state.data.tags?.items) tags.render(state.data.tags, context());
  persist();
});
$("tag-fetch").addEventListener("click", () => tagAction());
$("tag-cancel").addEventListener("click", () => tagAction(true));
$("tag-previous").addEventListener("click", () => {
  state.tagPage--;
  loadSelection();
});
$("tag-next").addEventListener("click", () => {
  state.tagPage++;
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
  if (button?.dataset.session) {
    state.selectedSession = button.dataset.session;
    state.sessionRecordPage = 1;
    loadSessionRecords(true);
  }
  if (button?.dataset.tab) {
    if (state.tab !== button.dataset.tab) charts.clearCharts();
    state.tab = button.dataset.tab;
    loadSelection();
  }
  if (button?.dataset.entityKey)
    openEntity(button.dataset.entityKind, button.dataset.entityKey);
  if (button?.dataset.day) selectDay(button.dataset.day);
  if (button?.dataset.periodStart)
    selectPeriod(button.dataset.periodStart, button.dataset.periodEnd);
  if (button?.dataset.weekday !== undefined)
    selectRhythm(button.dataset.weekday, button.dataset.hour);
  if (button?.dataset.chartExport)
    charts.exportChart(button.dataset.chartExport, {
      ...context(),
      from:
        button.dataset.chartExport === "anniversaries"
          ? state.data.anniversaries?.observed_from || state.from
          : state.from,
    });
  if (button?.dataset.sessionExport && state.data.sessions)
    exportSessions(button.dataset.sessionExport);
  if (button?.dataset.csv) exportData(button.dataset.csv);
  if (!event.target.closest(".artist-control"))
    $("artist-results").hidden = true;
});
document.addEventListener("listening:select", (event) => {
  const detail = event.detail;
  if (detail.type === "era" && state.data.eras) {
    state.eraReference = state.data.eras.periods[detail.reference].label;
    renderEraTable(detail.comparison);
    persist();
  }
  if (detail.type === "library-status") {
    $("library-status").value = detail.status;
    state.libraryPage = 1;
    state.tagPage = 1;
    state.originPage = 1;
    loadSelection();
  }
  if (detail.type === "origin-country") {
    if (
      ![...$("origin-country").options].some(
        (option) => option.value === detail.country,
      )
    )
      $("origin-country").append(
        new Option(origins.countryName(detail.country), detail.country),
      );
    $("origin-country").value = detail.country;
    state.originPage = 1;
    loadSelection();
  }
  if (detail.type === "tag") {
    $("tag-filter").value = detail.key;
    state.tagPage = 1;
    state.originPage = 1;
    loadSelection();
  }
  if (detail.type === "entity") openEntity(detail.kind, detail.key);
  if (detail.type === "day") selectDay(detail.day);
  if (detail.type === "rhythm") selectRhythm(detail.weekday, detail.hour);
});
window.addEventListener("resize", charts.resizeCharts);
setInterval(() => {
  if (state.authenticated && !document.hidden) checkStatus();
}, 60000);
for (const [id, key] of [
  ["library-kind", "library_kind"],
  ["library-status", "library_status"],
]) {
  const value = parameters.get(key);
  if ([...$(id).options].some((option) => option.value === value))
    $(id).value = value;
}
$("library-minimum").value = Math.max(
  1,
  Math.min(100000000, Number(parameters.get("library_min")) || 1),
);
$("library-search").value = (parameters.get("library_q") || "").slice(0, 100);
$("tag-per-artist").value =
  parameters.get("tags_per_artist") === "1" ? "1" : "3";
$("tag-display").value =
  parameters.get("tag_display") === "share" ? "share" : "count";
$("tag-search").value = (parameters.get("tag_q") || "").slice(0, 100);
if (/^(unknown|other|[0-9a-f]{64})$/.test(parameters.get("tag") || "")) {
  $("tag-filter").append(
    new Option("Selected evidence tag", parameters.get("tag")),
  );
  $("tag-filter").value = parameters.get("tag");
}
$("session-gap").value = boundedInteger(
  parameters.get("session_gap"),
  1,
  240,
  30,
);
$("session-minimum").value = boundedInteger(
  parameters.get("session_min"),
  1,
  100000000,
  1,
);
$("session-order").value =
  parameters.get("session_order") === "plays" ? "plays" : "recent";

$("quilt-size").value = ["9", "16", "25", "49"].includes(
  parameters.get("quilt_size"),
)
  ? parameters.get("quilt_size")
  : "16";
$("quilt-search").value = (parameters.get("quilt_q") || "").slice(0, 100);
$("quilt-labels").checked = parameters.get("quilt_labels") !== "false";

$("origin-metric").value =
  parameters.get("origin_metric") === "artists" ? "artists" : "plays";
$("origin-search").value = (parameters.get("origin_q") || "").slice(0, 100);
if (
  [...$("origin-evidence").options].some(
    (option) => option.value === parameters.get("origin_evidence"),
  )
)
  $("origin-evidence").value = parameters.get("origin_evidence");
if (/^[A-Z]{2}$/.test(parameters.get("origin_country") || "")) {
  $("origin-country").append(
    new Option(
      origins.countryName(parameters.get("origin_country")),
      parameters.get("origin_country"),
    ),
  );
  $("origin-country").value = parameters.get("origin_country");
}
authenticate();

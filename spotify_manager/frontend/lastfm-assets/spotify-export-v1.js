import { spotifyLink } from "./library-v1.js?v=15";
import { element, number, renderTable } from "./tables-v1.js?v=7";

const $ = (id) => document.getElementById("spotify-export-" + id);
const base = "/lastfm/analytics/playlist-export";
const key = "listening-spotify-export";
let controller;
let request;
let selection;
let page;
let timer;
let busy = false;
let unlocked = false;
let configured = null;

function remembered() {
  try {
    const value = sessionStorage.getItem(key);
    return /^[a-f0-9]{32}$/.test(value) ? value : null;
  } catch {
    return null;
  }
}

function remember(identity) {
  try {
    if (identity) sessionStorage.setItem(key, identity);
    else sessionStorage.removeItem(key);
  } catch {
    // The open dialog remains usable if browser storage is disabled.
  }
  showStatusButton();
}

function showStatusButton() {
  $("resume").hidden = !unlocked || !remembered();
}

export function unlock() {
  unlocked = true;
  showStatusButton();
}

export function lock() {
  unlocked = false;
  clear();
}

function clear() {
  $("dialog").close();
  controller?.abort();
  clearTimeout(timer);
  selection = null;
  page = null;
  busy = false;
  configured = null;
  $("items").replaceChildren();
  $("existing").replaceChildren();
  $("link").replaceChildren();
  $("summary").textContent = "";
  $("state").textContent = "";
  $("resume").hidden = true;
}

function begin(fetcher) {
  clear();
  request = fetcher;
  controller = new AbortController();
  $("dialog").showModal();
  showStatusButton();
}

export function open(source, fetcher) {
  begin(fetcher);
  selection = source;
  $("kind").value = "new";
  $("kind").options[1].textContent =
    source.source.kind === "albums"
      ? "Palace of Memory · first track per album"
      : "A Blast from the Past · selected tracks";
  $("name").value = source.name;
  $("form").hidden = false;
  $("review").hidden = true;
  showDestination();
  $("name").focus();
}

export function reconnect(fetcher) {
  const identity = remembered();
  if (!identity) return;
  begin(fetcher);
  $("form").hidden = true;
  $("review").hidden = true;
  act((signal) => readPage(identity, 1, signal));
}

function showDestination() {
  const existing = $("kind").value === "existing";
  $("kind").disabled = busy;
  $("existing").hidden = !existing || !configured;
  $("name-field").hidden = existing;
  $("name").disabled = existing;
  $("prepare").disabled = busy || (existing && !configured);
}

function loadDestinations() {
  showDestination();
  if ($("kind").value !== "existing" || configured) return;
  act(async (signal) => {
    $("state").textContent = "Checking the configured Spotify playlist…";
    const destinations = await request(
      base + "/destinations",
      { source: selection.source.kind },
      signal,
    );
    if (signal.aborted) return;
    configured = destinations[0] || null;
    if (configured)
      $("existing").textContent =
        `${configured.name} · ${configured.public ? "public" : "private"}`;
    $("state").textContent = configured
      ? ""
      : "The configured playlist is unavailable to the signed-in Spotify account.";
  });
}

function render(result) {
  page = result;
  const { status, items } = result;
  $("form").hidden = true;
  $("review").hidden = false;
  const operation = status.append
    ? `Append to ${status.public ? "public" : "private"} playlist “${status.name}”`
    : `Create private playlist “${status.name}”`;
  $("summary").textContent =
    `${operation} · ${number(status.total)} ${status.total === 1 ? "track" : "tracks"} in this order.`;
  renderTable(
    "spotify-export-items",
    ["Position", "Spotify track", "Artist or album"],
    items.map((item, index) => [
      (result.page - 1) * result.page_size + index + 1,
      spotifyLink(item.uri, item.name) || item.name,
      item.credit,
    ]),
  );
  $("page").textContent =
    `Page ${number(result.page)} of ${number(Math.ceil(status.total / result.page_size))}`;
  renderStatus(status);
}

function renderStatus(status) {
  if (!page) return;
  page.status = status;
  const active = ["running", "queued"].includes(status.stage);
  const review = status.stage === "prepared";
  $("edit").hidden = !selection || !review;
  $("confirm").hidden = !review && status.stage !== "paused";
  $("confirm").textContent = review
    ? "Confirm Spotify export"
    : "Recheck and resume";
  $("pause").hidden = !active;
  $("previous").disabled = busy || page.page <= 1;
  $("next").disabled = busy || page.page * page.page_size >= status.total;
  $("confirm").disabled = busy;
  $("pause").disabled = busy;
  const progress = `${number(status.added)} / ${number(status.total)} tracks confirmed`;
  const observed = status.observed
    ? ` · ${number(status.observed)} seen in the last batch`
    : "";
  $("state").textContent = review
    ? "Review the destination and additions before confirming."
    : `${progress}${observed}. ${status.message}`;
  $("link").replaceChildren();
  if (/^[A-Za-z0-9]{22}$/.test(status.playlist_id) && !review) {
    const link = element("a", "Open playlist in Spotify");
    link.href = "https://open.spotify.com/playlist/" + status.playlist_id;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    $("link").append(link);
  }
  clearTimeout(timer);
}

async function act(action) {
  if (busy || !controller) return;
  const signal = controller.signal;
  busy = true;
  showDestination();
  if (page) renderStatus(page.status);
  try {
    await action(signal);
  } catch (error) {
    if (signal.aborted || error.status === 401) return;
    if (error.status === 404 && !selection) remember(null);
    $("state").textContent =
      error.message || "The Spotify export could not be reached.";
  } finally {
    if (!signal.aborted) {
      busy = false;
      showDestination();
      if (page) {
        $("previous").disabled = page.page <= 1;
        $("next").disabled = page.page * page.page_size >= page.status.total;
        $("confirm").disabled = false;
        $("pause").disabled = false;
        if (["running", "queued"].includes(page.status.stage))
          timer = setTimeout(() => turnPage(page.page), 1200);
      }
    }
  }
}

function prepare() {
  if (!selection) return;
  act(async (signal) => {
    const destination =
      $("kind").value === "new"
        ? { kind: "new", name: $("name").value.trim() }
        : { kind: "existing", identity: configured.identity };
    $("state").textContent = "Preparing the exact additions…";
    const result = await request(
      base + "/plans",
      selection.params,
      signal,
      "POST",
      {
        body: { destination, source: selection.source },
      },
    );
    if (!signal.aborted) render(result);
  });
}

async function readPage(identity, index, signal) {
  const result = await request(
    base + "/plans/" + identity,
    { page: index },
    signal,
  );
  if (!signal.aborted) render(result);
}

function turnPage(index) {
  if (!page) return;
  act((signal) => readPage(page.status.identity, index, signal));
}

function changeJob(action) {
  if (!page) return;
  act(async (signal) => {
    const identity = page.status.identity;
    if (action === "confirm") remember(identity);
    const status = await request(
      base + "/plans/" + identity + "/" + action,
      null,
      signal,
      "POST",
    );
    if (!signal.aborted) renderStatus(status);
  });
}

$("form").addEventListener("submit", (event) => {
  event.preventDefault();
  prepare();
});
$("kind").addEventListener("change", loadDestinations);
$("close").addEventListener("click", () => $("dialog").close());
$("dialog").addEventListener("close", () => {
  if ($("dialog").open) return;
  clear();
  showStatusButton();
});
$("edit").addEventListener("click", () => {
  page = null;
  $("review").hidden = true;
  $("form").hidden = false;
  $("state").textContent = "";
  showDestination();
});
$("previous").addEventListener("click", () => turnPage(page.page - 1));
$("next").addEventListener("click", () => turnPage(page.page + 1));
$("confirm").addEventListener("click", () => changeJob("confirm"));
$("pause").addEventListener("click", () => changeJob("pause"));

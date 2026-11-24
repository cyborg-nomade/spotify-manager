import {
  element,
  entityButton,
  exportCSV,
  number,
  recordedTime,
  renderTable,
} from "./tables-v1.js?v=7";

const $ = (id) => document.getElementById(id);
const HEADER_HEIGHT = 260;
export const outcomes = {
  ready: "Representative cover available",
  no_cover: "One name candidate · no available front cover",
  unmatched: "No exact title/artist candidate",
  ambiguous: "Multiple title/artist candidates",
  incomplete: "Search incomplete",
  missing: "Not looked up",
};
let revision = 0;
let imageUpdate = 0;
let tiles = [];
let pending = Promise.resolve();

export function reset() {
  revision++;
  imageUpdate++;
  for (const node of tiles) {
    node.request = null;
    clearArtwork(node);
  }
  tiles = [];
  pending = Promise.resolve();
  $("quilt-grid").replaceChildren();
}

export function labels() {
  $("quilt-grid").classList.toggle("hide-captions", !$("quilt-labels").checked);
}

export function progress(status) {
  const busy = ["running", "cancelling"].includes(status.state);
  $("quilt-progress").textContent =
    `${status.state} · ${status.completed}/${status.total} albums completed in the latest batch. ${status.message}`;
  $("quilt-progress").classList.toggle(
    "warning",
    status.state === "error" || !status.cache_available,
  );
  $("quilt-fetch").disabled =
    busy || !status.configured || !status.cache_available || !tiles.length;
  $("quilt-cancel").disabled = !busy || status.state === "cancelling";
}

function hue(key) {
  return parseInt(key.slice(0, 6), 16) % 360;
}
function initial(item) {
  return Array.from(item.album.name.trim())[0] || "♪";
}

function tile(item, rank) {
  const row = element("div");
  row.className = "quilt-tile";
  row.setAttribute("role", "listitem");
  const button = entityButton(item.album, "album");
  button.className = "quilt-open";
  button.replaceChildren();
  const art = element("span");
  art.className = "quilt-art";
  art.style.setProperty("--quilt-hue", hue(item.album.key));
  const placeholder = element("span", initial(item));
  placeholder.className = "quilt-initial";
  placeholder.setAttribute("aria-hidden", "true");
  const badge = element("span", String(rank).padStart(2, "0"));
  badge.className = "quilt-rank";
  badge.setAttribute("aria-hidden", "true");
  art.append(placeholder, badge);
  const caption = element("span");
  caption.className = "quilt-caption";
  const count = element("span", "", "quilt-count");
  caption.append(
    element("span", item.album.name, "quilt-title"),
    element("span", item.album.artist, "quilt-artist"),
    count,
  );
  button.append(art, caption);
  row.append(button);
  return {
    key: item.album.key,
    row,
    button,
    art,
    placeholder,
    count,
    artwork: null,
    request: null,
  };
}

function renderTiles(data) {
  const grid = $("quilt-grid");
  if (
    tiles.length !== data.items.length ||
    tiles.some((node, index) => node.key !== data.items[index].album.key)
  ) {
    reset();
    tiles = data.items.map((item, index) => tile(item, index + 1));
    grid.append(...tiles.map((node) => node.row));
  }
  grid.style.setProperty("--quilt-columns", Math.sqrt(data.options.size));
  labels();
  if (!tiles.length && !grid.firstChild) {
    grid.append(
      element(
        "p",
        "No named albums match this selection. Try another date range or clear the quilt search.",
        "quilt-empty",
      ),
    );
  }
  data.items.forEach((item, index) => {
    const node = tiles[index];
    node.button.setAttribute(
      "aria-label",
      `${index + 1}. ${item.album.name} by ${item.album.artist} · ${number(item.album.plays)} recorded plays · ${outcomes[item.evidence]}`,
    );
    node.count.textContent = `${number(item.album.plays)} plays · ${item.artwork ? "Cover cached" : "Placeholder"}`;
  });
}

function sourceCell(item) {
  const node = element("div");
  for (const candidate of item.candidates) {
    const link = element(
      "a",
      `${candidate.title} · ${candidate.artist}${candidate.description ? ` · ${candidate.description}` : ""}`,
    );
    link.href = `https://musicbrainz.org/release-group/${candidate.mbid}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const row = element("p");
    row.append(link);
    node.append(row);
  }
  if (item.candidate_count > item.candidates.length)
    node.append(
      element(
        "p",
        `${item.candidate_count} candidates found; showing ${item.candidates.length}.`,
      ),
    );
  if (item.artwork) {
    const lastfm = item.artwork.source === "lastfm";
    const link = element(
      "a",
      lastfm ? "Last.fm album artwork" : "Representative release / artwork",
    );
    link.href = lastfm
      ? item.artwork.page_url
      : `https://musicbrainz.org/release/${item.artwork.release_mbid}/cover-art`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    node.append(link);
  }
  if (!node.childNodes.length)
    node.append(element("span", "No available candidate evidence"));
  return node;
}

export function render(data, context, password, signal) {
  if (data.unavailable) {
    reset();
    $("quilt-coverage").textContent = data.unavailable;
    $("quilt-images").textContent =
      "Listening totals remain available. Retry this view to read cached covers.";
    for (const id of [
      "quilt-table",
      "quilt-coverage-table",
      "quilt-source",
      "quilt-progress",
    ])
      $(id).replaceChildren();
    $("quilt-fetch").disabled = true;
    $("quilt-cancel").disabled = true;
    return;
  }
  const coverage = data.coverage;
  $("quilt-coverage").textContent =
    `${number(data.items.length)} of ${number(coverage.matching_albums)} matching albums · ${number(coverage.shown_plays)} recorded plays in this quilt. ${number(coverage.artwork_albums)} tiles have cached representative covers. The full selection contains ${number(coverage.plays)} plays: ${number(coverage.album_plays)} with album names and ${number(coverage.missing_album_plays)} without. ${number(coverage.album_plays - coverage.shown_plays)} named-album plays are outside this quilt.`;
  $("quilt-source").textContent = data.retrieved_from
    ? `Current observations retrieved ${recordedTime(Date.parse(data.retrieved_from), context.timezone)} through ${recordedTime(Date.parse(data.retrieved_through), context.timezone)}. Name evidence does not verify identity or the edition heard. Covers: Last.fm or Cover Art Archive / Internet Archive.`
    : "No current cover observations cached for these tiles. Album ranks and recorded plays are complete without artwork.";
  const attributed = data.items.find(
    (item) => item.artwork?.source === "lastfm",
  );
  if (attributed) {
    const credit = element("a", "Powered by AudioScrobbler");
    credit.href = attributed.artwork.page_url;
    credit.target = "_blank";
    credit.rel = "noopener noreferrer";
    $("quilt-source").append(" ", credit);
  }
  const firstRender = !tiles.length;
  renderTiles(data);
  renderTable(
    "quilt-table",
    [
      "Album / recorded history",
      "Artist",
      "Selected plays",
      "Artwork evidence",
      "Source candidates / representative release",
      "Retrieved",
    ],
    data.items.map((item) => [
      entityButton(item.album, "album"),
      item.album.artist,
      number(item.album.plays),
      outcomes[item.evidence],
      sourceCell(item),
      item.fetched_at
        ? recordedTime(Date.parse(item.fetched_at), context.timezone)
        : "Not retrieved",
    ]),
  );
  renderTable(
    "quilt-coverage-table",
    ["Displayed artwork evidence", "Albums", "Selected plays"],
    coverage.outcomes.map((item) => [
      outcomes[item.evidence],
      number(item.albums),
      number(item.plays),
    ]),
  );
  progress(data.lookup);
  if (firstRender && coverage.artwork_albums)
    $("quilt-images").textContent = "Loading cached artwork…";
  const current = ++imageUpdate;
  pending = loadImages(data, tiles, password, signal, current).then(
    (results) => {
      if (current === imageUpdate && !signal.aborted) showImageResults(results);
    },
  );
}

function clearArtwork(node) {
  if (node.artwork) {
    node.artwork.image.remove();
    URL.revokeObjectURL(node.artwork.url);
    node.artwork = null;
  }
  node.placeholder.hidden = false;
}

async function loadOne(item, node, snapshot, password, signal, current) {
  if (current !== imageUpdate || signal.aborted) return "cancelled";
  const hash = item.artwork?.sha256;
  if (!hash || node.artwork?.hash === hash) {
    node.request = null;
    if (!hash) clearArtwork(node);
    return hash ? "loaded" : "placeholder";
  }
  if (node.request?.hash === hash) {
    const request = node.request;
    const result = await request.promise;
    if (result !== "expired" || request.snapshot === snapshot || signal.aborted)
      return result;
    return loadOne(item, node, snapshot, password, signal, current);
  }
  const request = { hash, snapshot };
  node.request = request;
  request.promise = fetchArtwork(node, request, password, signal);
  return request.promise;
}

async function fetchArtwork(node, request, password, signal) {
  let url;
  try {
    const query = new URLSearchParams({
      metadata_snapshot: request.snapshot,
    });
    const response = await fetch(
      `/lastfm/analytics/quilt/images/${node.key}?${query}`,
      { headers: { "X-App-Password": password }, signal, cache: "no-store" },
    );
    if (node.request !== request || signal.aborted) return "cancelled";
    if (response.status === 401) {
      document.dispatchEvent(new CustomEvent("listening-auth-required"));
      return "unavailable";
    }
    if (response.status === 409) return "expired";
    if (!response.ok) {
      clearArtwork(node);
      return "unavailable";
    }
    const blob = await response.blob();
    if (node.request !== request || signal.aborted) return "cancelled";
    url = URL.createObjectURL(blob);
    const image = new Image();
    image.alt = "";
    image.src = url;
    await image.decode();
    if (node.request !== request || signal.aborted) return "cancelled";
    clearArtwork(node);
    node.placeholder.hidden = true;
    node.art.append(image);
    node.artwork = { hash: request.hash, image, url };
    return "loaded";
  } catch (error) {
    if (node.request !== request || signal.aborted) return "cancelled";
    clearArtwork(node);
    return "unavailable";
  } finally {
    if (url && node.artwork?.url !== url) URL.revokeObjectURL(url);
    if (node.request === request) node.request = null;
  }
}

async function loadImages(data, nodes, password, signal, current) {
  const results = [];
  for (let index = 0; index < data.items.length; index += 4) {
    if (signal.aborted || current !== imageUpdate) return results;
    const batch = data.items
      .slice(index, index + 4)
      .map((item, offset) =>
        loadOne(
          item,
          nodes[index + offset],
          data.metadata_snapshot,
          password,
          signal,
          current,
        ),
      );
    results.push(...(await Promise.all(batch)));
  }
  return results;
}

function showImageResults(results) {
  const loaded = tiles.filter((node) => node.artwork).length;
  const failed = results.filter((item) =>
    ["unavailable", "expired"].includes(item),
  ).length;
  $("quilt-images").textContent =
    `${loaded} covers displayed · ${tiles.length - loaded} placeholders. ${failed ? "Some cached images could not load; reload cached artwork to retry. " : ""}${results.includes("expired") ? "The cover version changed. " : ""}PNG always includes every tile; unavailable artwork is replaced with a labelled placeholder.`;
}

export function notes(data) {
  return [
    ["Metadata snapshot", data.metadata_snapshot],
    ["Artwork source", "Last.fm or Cover Art Archive / Internet Archive"],
    [
      "Interpretation",
      "Current representative covers supported by exact title and artist credit. Names do not verify identity or the edition heard.",
    ],
    [
      "Retrieved",
      `${data.retrieved_from || "None"} through ${data.retrieved_through || "None"}`,
    ],
    ["Quilt size", data.options.size],
    ["Album/artist search", data.options.search || "None"],
    [
      "Scope",
      `${data.items.length} visible ranked albums; ${data.coverage.shown_plays} plays. ${data.coverage.missing_album_plays} plays lack album names; ${data.coverage.album_plays - data.coverage.shown_plays} named-album plays outside quilt.`,
    ],
  ];
}

export function csv(data, context) {
  const headers = [
    "Rank",
    "Album key",
    "Album",
    "Artist",
    "Selected plays",
    "Share of named-album plays",
    "Artwork evidence",
    "Candidates found",
    "Release group candidates",
    "Representative release",
    "Archive image ID",
    "Artwork provider",
    "Last.fm album page",
    "Image SHA256",
    "Retrieved",
  ];
  const rows = data.items.map((item, index) => [
    index + 1,
    item.album.key,
    item.album.name,
    item.album.artist,
    item.album.plays,
    item.album.share,
    item.evidence,
    item.candidate_count,
    item.candidates
      .map(
        (candidate) =>
          `https://musicbrainz.org/release-group/${candidate.mbid}`,
      )
      .join(" | "),
    item.artwork?.release_mbid || "",
    item.artwork?.image_id || "",
    item.artwork
      ? item.artwork.source === "lastfm"
        ? "Last.fm"
        : "Cover Art Archive"
      : "",
    item.artwork?.page_url || "",
    item.artwork?.sha256 || "",
    item.fetched_at || "",
  ]);
  exportCSV("album-quilt", headers, rows, { ...context, notes: notes(data) });
}

function wrap(ctx, text, x, y, width, lineHeight, maxLines = 2) {
  const characters = Array.from(text);
  let line = "";
  let lines = 1;
  for (const char of characters) {
    if (ctx.measureText(line + char).width > width && line) {
      ctx.fillText(line, x, y);
      y += lineHeight;
      line = "";
      lines++;
      if (lines > maxLines) return y;
    }
    line += char;
  }
  ctx.fillText(line, x, y);
  return y + lineHeight;
}

export async function png(data, context) {
  const current = revision;
  const ready = pending;
  const captions = $("quilt-labels").checked;
  $("quilt-images").textContent =
    "Preparing the quilt export with available cached artwork…";
  await ready;
  if (current !== revision) return;
  const images = new Map();
  for (const [index, item] of data.items.entries()) {
    const artwork = tiles[index]?.artwork;
    if (artwork && artwork.hash === item.artwork?.sha256)
      images.set(item.album.key, artwork.image);
  }
  const canvas = document.createElement("canvas");
  const columns = Math.sqrt(data.options.size);
  const cell = 220;
  const gap = 12;
  const margin = 36;
  const caption = captions ? 88 : 0;
  const rows = Math.ceil(data.items.length / columns);
  canvas.width = columns * (cell + gap) - gap + margin * 2;
  canvas.height =
    HEADER_HEIGHT + Math.max(1, rows) * (cell + caption + gap) + 210;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#101c22";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#e0eee9";
  ctx.font = "italic 34px Georgia";
  ctx.fillText("Your listening, in covers.", margin, 50);
  ctx.font = "16px sans-serif";
  ctx.fillText(
    `${context.from} → ${context.to} · ${context.timezone}`,
    margin,
    82,
  );
  ctx.fillStyle = "#b7c9c5";
  wrap(
    ctx,
    `${data.items.length} albums · ${number(data.coverage.shown_plays)} recorded plays in this quilt · ${images.size} covers embedded. Every other tile is a placeholder.`,
    margin,
    110,
    canvas.width - margin * 2,
    22,
  );
  wrap(
    ctx,
    `Artist filter: ${context.artist || "All"} · Weekday: ${context.weekday ?? "All"} · Hour: ${context.hour ?? "All"} · Album/artist search: ${data.options.search || "None"}`,
    margin,
    166,
    canvas.width - margin * 2,
    19,
    4,
  );
  data.items.forEach((item, index) =>
    drawTile(
      ctx,
      item,
      index,
      columns,
      cell,
      gap,
      caption,
      margin,
      images.get(item.album.key),
    ),
  );
  let y = HEADER_HEIGHT + Math.max(1, rows) * (cell + caption + gap) + 20;
  ctx.fillStyle = "#b7c9c5";
  ctx.font = "13px sans-serif";
  for (const text of [
    "Current representative covers: Last.fm or Cover Art Archive / Internet Archive.",
    "One exact title/artist-credit candidate does not verify identity or the edition heard.",
    `History: ${context.snapshot}`,
    `Covers: ${data.metadata_snapshot}`,
    `Retrieved: ${data.retrieved_from || "None"} through ${data.retrieved_through || "None"}`,
    `Full selection: ${data.coverage.plays} plays; ${data.coverage.missing_album_plays} without album names; ${data.coverage.album_plays - data.coverage.shown_plays} named-album plays outside quilt.`,
  ])
    y = wrap(ctx, text, margin, y, canvas.width - margin * 2, 18);
  const blob = await new Promise((resolve) =>
    canvas.toBlob(resolve, "image/png"),
  );
  if (blob && current === revision) {
    const url = URL.createObjectURL(blob);
    const link = element("a");
    link.href = url;
    link.download = `listening-album-quilt-${context.from}-${context.to}.png`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    if (ready === pending)
      $("quilt-images").textContent =
        `Quilt PNG exported with ${images.size} cached covers and ${data.items.length - images.size} labelled placeholders.`;
  }
}

function drawTile(
  ctx,
  item,
  index,
  columns,
  cell,
  gap,
  caption,
  margin,
  image,
) {
  const x = margin + (index % columns) * (cell + gap);
  const y =
    HEADER_HEIGHT + Math.floor(index / columns) * (cell + caption + gap);
  ctx.fillStyle = `hsl(${hue(item.album.key)} 24% 19%)`;
  ctx.fillRect(x, y, cell, cell);
  if (image) {
    const scale = Math.min(
      cell / image.naturalWidth,
      cell / image.naturalHeight,
    );
    const width = image.naturalWidth * scale;
    const height = image.naturalHeight * scale;
    ctx.drawImage(
      image,
      x + (cell - width) / 2,
      y + (cell - height) / 2,
      width,
      height,
    );
  } else {
    ctx.fillStyle = "#d9e6e3";
    ctx.font = "italic 64px Georgia";
    ctx.fillText(initial(item), x + 20, y + 100);
    ctx.font = "13px sans-serif";
    wrap(ctx, "Artwork unavailable", x + 14, y + 145, cell - 28, 17);
  }
  ctx.fillStyle = "#101c22e8";
  ctx.fillRect(x + 8, y + 8, 34, 23);
  ctx.fillStyle = "#e0eee9";
  ctx.font = "14px sans-serif";
  ctx.fillText(String(index + 1).padStart(2, "0"), x + 15, y + 25);
  if (caption || !image) {
    const labelY = caption ? y + cell + 21 : y + 166;
    ctx.fillStyle = "#e0eee9";
    ctx.font = "bold 14px sans-serif";
    wrap(ctx, item.album.name, x + 6, labelY, cell - 12, 17, 2);
    ctx.font = "13px sans-serif";
    ctx.fillStyle = "#bfd0cc";
    wrap(
      ctx,
      `${item.album.artist} · ${number(item.album.plays)} plays`,
      x + 6,
      labelY + 38,
      cell - 12,
      16,
      caption ? 2 : 1,
    );
  }
}

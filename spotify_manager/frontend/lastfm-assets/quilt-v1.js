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
let visible = 0;
let images = new Map();
let urls = [];
let pending = Promise.resolve();

export function reset() {
  revision++;
  visible = 0;
  for (const url of urls) URL.revokeObjectURL(url);
  urls = [];
  images = new Map();
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
    busy || !status.configured || !status.cache_available || !visible;
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
  button.setAttribute(
    "aria-label",
    `${rank}. ${item.album.name} by ${item.album.artist} · ${number(item.album.plays)} recorded plays · ${outcomes[item.evidence]}`,
  );
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
  for (const [name, text] of [
    ["title", item.album.name],
    ["artist", item.album.artist],
    [
      "count",
      `${number(item.album.plays)} plays · ${item.artwork ? "Cover cached" : "Placeholder"}`,
    ],
  ]) {
    const node = element("span", text);
    node.className = `quilt-${name}`;
    caption.append(node);
  }
  button.append(art, caption);
  row.append(button);
  return { row, art, placeholder };
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
  reset();
  if (data.unavailable) {
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
  visible = data.items.length;
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
  const columns = Math.sqrt(data.options.size);
  $("quilt-grid").style.setProperty("--quilt-columns", columns);
  const nodes = data.items.map((item, index) => tile(item, index + 1));
  $("quilt-grid").append(...nodes.map((node) => node.row));
  labels();
  if (!nodes.length) {
    const empty = element(
      "p",
      "No named albums match this selection. Try another date range or clear the quilt search.",
    );
    empty.className = "quilt-empty";
    $("quilt-grid").append(empty);
  }
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
  pending = loadImages(data, nodes, password, signal, revision);
}

async function loadOne(item, node, password, signal, current) {
  if (!item.artwork || current !== revision) return "placeholder";
  try {
    const query = new URLSearchParams({
      metadata_snapshot: item.metadata_snapshot,
    });
    const response = await fetch(
      `/lastfm/analytics/quilt/images/${item.album.key}?${query}`,
      { headers: { "X-App-Password": password }, signal, cache: "no-store" },
    );
    if (response.status === 401) {
      document.dispatchEvent(new CustomEvent("listening-auth-required"));
      return "unavailable";
    }
    if (!response.ok)
      return response.status === 409 ? "expired" : "unavailable";
    const blob = await response.blob();
    if (current !== revision || signal.aborted) return "cancelled";
    const url = URL.createObjectURL(blob);
    urls.push(url);
    const image = new Image();
    image.alt = "";
    image.src = url;
    await image.decode();
    if (current !== revision || signal.aborted) return "cancelled";
    node.placeholder.remove();
    node.art.append(image);
    images.set(item.album.key, image);
    return "loaded";
  } catch (error) {
    return error.name === "AbortError" ? "cancelled" : "unavailable";
  }
}

async function loadImages(data, nodes, password, signal, current) {
  $("quilt-images").textContent = data.coverage.artwork_albums
    ? "Loading cached artwork…"
    : "All tiles use labelled placeholders. Fetch covers explicitly to expand artwork coverage.";
  const results = [];
  for (let index = 0; index < data.items.length; index += 4) {
    if (current !== revision || signal.aborted) return;
    const batch = data.items
      .slice(index, index + 4)
      .map((item, offset) =>
        loadOne(
          { ...item, metadata_snapshot: data.metadata_snapshot },
          nodes[index + offset],
          password,
          signal,
          current,
        ),
      );
    results.push(...(await Promise.all(batch)));
  }
  if (current !== revision || signal.aborted) return;
  const loaded = results.filter((item) => item === "loaded").length;
  const failed = results.filter((item) =>
    ["unavailable", "expired"].includes(item),
  ).length;
  $("quilt-images").textContent =
    `${loaded} covers displayed · ${data.items.length - loaded} placeholders. ${failed ? "Some cached images could not load; reload cached artwork to retry. " : ""}${results.includes("expired") ? "The cover version changed. " : ""}PNG always includes every tile; unavailable artwork is replaced with a labelled placeholder.`;
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
    drawTile(ctx, item, index, columns, cell, gap, caption, margin),
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
    $("quilt-images").textContent =
      `Quilt PNG exported with ${images.size} cached covers and ${data.items.length - images.size} labelled placeholders.`;
  }
}

function drawTile(ctx, item, index, columns, cell, gap, caption, margin) {
  const x = margin + (index % columns) * (cell + gap);
  const y =
    HEADER_HEIGHT + Math.floor(index / columns) * (cell + caption + gap);
  ctx.fillStyle = `hsl(${hue(item.album.key)} 24% 19%)`;
  ctx.fillRect(x, y, cell, cell);
  const image = images.get(item.album.key);
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

import * as charts from "./charts-v1.js?v=12";
import {
  download,
  element,
  entityButton,
  exportCSV,
  number,
  recordedTime,
  renderTable,
} from "./tables-v1.js?v=7";

const $ = (id) => document.getElementById(id);
let revision = 0;

export function reset() {
  revision++;
  $("session-detail").hidden = true;
  $("session-records-table").replaceChildren();
  $("session-record-status").textContent = "";
  for (const id of [
    "sessions-table",
    "session-starts-table",
    "session-sizes-table",
    "session-metrics",
  ])
    $(id).replaceChildren();
  $("session-coverage").textContent = "";
}

export function span(milliseconds) {
  return `${number(Math.round(milliseconds / 6000) / 10)} min span`;
}

function edge(group) {
  if (group.selection_first && group.selection_last)
    return "First and last selected group";
  if (group.selection_first) return "First selected group";
  if (group.selection_last) return "Last selected group";
  return "Within selection";
}

function openButton(group, timezone) {
  const button = element(
    "button",
    recordedTime(group.window.first_ms, timezone),
    "entity-button",
  );
  button.type = "button";
  button.dataset.session = group.window.first_ms;
  button.append(element("small", "Open recorded plays ↗"));
  return button;
}

export function render(data, context) {
  const summary = data.summary;
  $("session-metrics").replaceChildren();
  for (const [value, label] of [
    [number(summary.matching_sessions), "Matching sessions"],
    [number(summary.matching_plays), "Plays in matching sessions"],
    [
      summary.matching_sessions ? number(summary.median_plays) : "—",
      "Median plays per matching session",
    ],
    [
      summary.matching_sessions ? span(summary.median_span_ms) : "—",
      "Median first-to-last recorded span",
    ],
  ]) {
    const metric = element("div");
    metric.append(element("strong", value), element("span", label));
    $("session-metrics").append(metric);
  }
  $("session-coverage").textContent =
    `${number(summary.selected_plays)} selected plays form ${number(summary.selected_sessions)} inferred groups. The minimum of ${number(data.options.minimum_plays)} plays keeps ${number(summary.matching_sessions)} groups / ${number(summary.matching_plays)} plays; ${number(summary.selected_plays - summary.matching_plays)} plays are below that minimum. A span is the elapsed gap from the first to last recorded timestamp, including pauses; it is not time listened. Single-record groups have a zero span and unknown duration.`;
  renderTable(
    "sessions-table",
    [
      "Starts / records",
      "Last recorded",
      "Plays",
      "Artists / tracks",
      "Leading artist",
      "Observed span",
      "Selection edges",
    ],
    data.items.map((group) => [
      openButton(group, context.timezone),
      recordedTime(group.window.last_ms, context.timezone),
      number(group.plays),
      `${number(group.artists)} / ${number(group.tracks)}`,
      entityButton(group.leading_artist, "artist"),
      span(group.window.last_ms - group.window.first_ms),
      edge(group),
    ]),
  );
  pagination(
    "session",
    data.options.page,
    data.options.limit,
    summary.matching_sessions,
  );
  charts.sessionStarts(data, context);
  charts.sessionSizes(data, context);
  renderTable(
    "session-starts-table",
    [
      data.grain === "week" ? "Week starting Monday" : "Month",
      "Session starts",
      "Plays in these groups",
    ],
    data.buckets.map((item) => [item.label, item.sessions, item.plays]),
  );
  renderTable(
    "session-sizes-table",
    ["Recorded plays per session", "Sessions", "Plays"],
    data.sizes.map((item) => [item.label, item.sessions, item.plays]),
  );
}

export function pagination(prefix, page, limit, total) {
  $(prefix + "-page").textContent =
    `Page ${number(page)} of ${number(Math.max(1, Math.ceil(total / limit)))} · ${number(total)} results`;
  $(prefix + "-previous").disabled = page <= 1;
  $(prefix + "-next").disabled = page * limit >= total;
}

export function renderRecords(data, context) {
  const group = data.session;
  $("session-detail").hidden = false;
  $("session-detail-title").textContent =
    `Session · ${recordedTime(group.window.first_ms, context.timezone)}`;
  $("session-detail-description").textContent =
    `${number(group.plays)} selected records, ${span(group.window.last_ms - group.window.first_ms)}, gap threshold ${data.gap_minutes} minutes. ${edge(group)}. Records are chronological, retaining original names, duplicates and source order at equal timestamps. No playback duration is inferred.`;
  $("session-record-status").textContent = "";
  renderTable(
    "session-records-table",
    ["Recorded at", "Track", "Artist", "Album", "Source row"],
    data.records.items.map((item) => [
      recordedTime(item.timestamp_ms, context.timezone),
      item.track,
      entityButton({ key: item.artist_key, name: item.artist }, "artist"),
      item.album || "Album not recorded",
      item.ordinal,
    ]),
  );
  pagination(
    "session-record",
    data.records.page,
    data.records.limit,
    data.records.total,
  );
}

export function notes(data) {
  return [
    [
      "Inference",
      "Consecutive selected records; strictly greater UTC gaps split groups; no listening duration inferred",
    ],
    ["Gap threshold (minutes)", data.options.gap_minutes],
    ["Minimum recorded plays", data.options.minimum_plays],
    [
      "Selected plays / groups",
      `${data.summary.selected_plays} / ${data.summary.selected_sessions}`,
    ],
    [
      "Matching plays / groups",
      `${data.summary.matching_plays} / ${data.summary.matching_sessions}`,
    ],
    [
      "Boundaries",
      "Filters can split activity; first/last selected groups may continue outside selection",
    ],
    [
      "Span",
      "Last minus first recorded timestamp, including pauses; single-record span zero, duration unknown",
    ],
  ];
}

export function csv(kind, data, context, detail) {
  let headers, rows;
  const metadata = notes(data);
  if (kind === "groups") {
    headers = [
      "First UTC ms / context-dependent session ID",
      "Last UTC ms",
      "Start in selected timezone",
      "Last in selected timezone",
      "Recorded plays",
      "Artists",
      "Tracks",
      "Leading artist",
      "Leading artist key",
      "Leading artist plays",
      "Observed span ms (not listening duration)",
      "First selected group",
      "Last selected group",
    ];
    rows = data.items.map((group) => [
      group.window.first_ms,
      group.window.last_ms,
      recordedTime(group.window.first_ms, context.timezone),
      recordedTime(group.window.last_ms, context.timezone),
      group.plays,
      group.artists,
      group.tracks,
      group.leading_artist.name,
      group.leading_artist.key,
      group.leading_artist.plays,
      group.window.last_ms - group.window.first_ms,
      group.selection_first,
      group.selection_last,
    ]);
    metadata.push([
      "Export scope",
      `Current group page ${data.options.page}; ${data.options.order} order; ${data.items.length} of ${data.summary.matching_sessions} matching groups`,
    ]);
  } else if (kind === "buckets") {
    headers = [
      data.grain === "week" ? "Monday" : "Month",
      "Session starts",
      "Plays in these groups",
    ];
    rows = data.buckets.map((item) => [item.label, item.sessions, item.plays]);
    metadata.push([
      "Export scope",
      "All matching groups by their first selected record's local bucket",
    ]);
  } else if (kind === "sizes-csv") {
    headers = ["Recorded plays per session", "Sessions", "Plays"];
    rows = data.sizes.map((item) => [item.label, item.sessions, item.plays]);
    metadata.push([
      "Export scope",
      "All matching groups, disjoint inclusive size bands",
    ]);
  } else if (kind === "records" && detail) {
    headers = [
      "Recorded UTC ms",
      "Recorded at",
      "Track",
      "Artist",
      "Album",
      "Source row",
    ];
    rows = detail.records.items.map((item) => [
      item.timestamp_ms,
      recordedTime(item.timestamp_ms, context.timezone),
      item.track,
      item.artist,
      item.album,
      item.ordinal,
    ]);
    metadata.push(
      [
        "Session first / last UTC ms",
        `${detail.session.window.first_ms} / ${detail.session.window.last_ms}`,
      ],
      [
        "Export scope",
        `Chronological record page ${detail.records.page}; ${detail.records.items.length} of ${detail.records.total} selected source records`,
      ],
    );
  } else return;
  exportCSV(`sessions-${kind}`, headers, rows, { ...context, notes: metadata });
}

function drawLines(ctx, lines, y) {
  for (const line of lines) {
    let text = "";
    for (const word of line.split(" ")) {
      if (ctx.measureText(`${text} ${word}`).width > 1140) {
        ctx.fillText(text, 30, y);
        y += 22;
        text = "";
      }
      text += (text ? " " : "") + word;
    }
    ctx.fillText(text, 30, y);
    y += 22;
  }
  return y;
}

export async function png(kind, data, context) {
  const current = revision;
  const url = charts.sessionImage(`session-${kind}`);
  if (!url) return;
  const image = new Image();
  image.src = url;
  await image.decode();
  const canvas = element("canvas");
  canvas.width = 1200;
  const height = Math.round(
    (image.naturalHeight * canvas.width) / image.naturalWidth,
  );
  canvas.height = height + 450;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#14232a";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, 0, 0, canvas.width, height);
  ctx.fillStyle = "#d7e6e1";
  ctx.font = "15px sans-serif";
  drawLines(
    ctx,
    [
      `Listening sessions · ${context.from} through ${context.to} · ${context.timezone}`,
      `Source: ${context.snapshot}`,
      `Artist: ${context.artist || "All"} · weekday: ${context.weekday ?? "All"} · hour: ${context.hour ?? "All"}`,
      ...notes(data).map(([label, value]) => `${label}: ${value}`),
      "Export scope: all matching groups; charts are independent of group pagination.",
    ],
    height + 30,
  );
  const blob = await new Promise((resolve) =>
    canvas.toBlob(resolve, "image/png"),
  );
  if (blob && revision === current)
    download(
      `listening-sessions-${kind}-${context.from}-${context.to}.png`,
      blob,
    );
}

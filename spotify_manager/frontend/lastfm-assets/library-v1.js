import * as charts from "./charts-v1.js?v=4";
import {
  element,
  entityButton,
  number,
  recordedTime,
  renderTable,
} from "./tables-v1.js?v=4";

export const labels = {
  name_match: "One exact name candidate",
  unmatched: "No exact name match",
  ambiguous: "Multiple name candidates",
  unavailable: "Collection unavailable",
};
const collections = {
  artist: "Followed artists",
  album: "Saved albums",
  track: "Liked tracks",
};
const $ = (id) => document.getElementById(id);

function candidateLinks(item) {
  const node = element("span");
  for (const candidate of item.candidates) {
    const match = /^spotify:(artist|album|track):([A-Za-z0-9]{22})$/.exec(
      candidate.uri,
    );
    if (!match) continue;
    const link = element("a", candidate.name);
    link.href = `https://open.spotify.com/${match[1]}/${match[2]}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    node.append(link, document.createTextNode(" "));
  }
  if (item.candidate_count > item.candidates.length)
    node.append(
      element(
        "small",
        `Showing ${item.candidates.length} of ${item.candidate_count} candidates`,
      ),
    );
  return node;
}

export function render(data, kind, context) {
  $("library-message").textContent =
    data.unavailable ||
    "Name evidence is not a verified cross-service identity. No exact match can reflect spelling, editions, collaborations, or an item absent from this publication.";
  $("library-message").classList.toggle("warning", Boolean(data.unavailable));
  $("library-export").disabled = !data.items;
  $("library-previous").disabled = !data.items || data.page <= 1;
  $("library-next").disabled =
    !data.items || data.page * data.limit >= data.total;
  if (!data.items) {
    charts.clearCharts();
    $("library-table").replaceChildren();
    $("library-coverage-table").replaceChildren();
    $("library-source").textContent =
      "Listening history remains available while collection evidence is unavailable.";
    $("library-page").textContent = "";
    return;
  }
  const source = data.source;
  const published = source.published_at ? new Date(source.published_at) : null;
  const validDate = published && Number.isFinite(published.getTime());
  const age = validDate
    ? Math.max(0, Math.floor((Date.now() - published) / 86400000))
    : null;
  $("library-source").textContent =
    `${collections[kind]} · ${source.state} · ${number(source.entries)} collection identities · published ${validDate ? published.toLocaleString() : "unknown"}${age !== null ? ` (${age} days ago)` : ""}. ${source.message} Source: ${source.source || "unavailable"}.`;
  $("library-page").textContent =
    `Page ${data.page} · ${number(data.total)} results`;
  charts.library(data, context);
  renderTable(
    "library-coverage-table",
    ["Name evidence", "Historical entities", "Selected plays"],
    data.coverage.map((item) => [
      labels[item.status],
      number(item.entities),
      number(item.plays),
    ]),
  );
  const rows = data.items.map((item) => [
    entityButton(item.history, kind),
    number(item.history.plays),
    recordedTime(item.history.last_ms, context.timezone),
    labels[item.status],
    candidateLinks(item),
  ]);
  renderTable(
    "library-table",
    [
      "Recorded music / artist",
      "Selected plays",
      "Last selected play",
      "Name evidence",
      "Spotify candidates",
    ],
    rows,
  );
}

export function csv(data) {
  return data.items.map((item) => [
    item.history.key,
    item.history.name,
    item.history.artist,
    item.history.plays,
    item.history.first_ms,
    item.history.last_ms,
    item.status,
    item.candidate_count,
    item.candidates.map((candidate) => candidate.uri).join("; "),
  ]);
}

export function notes(data, options) {
  return [
    ["Library snapshot", data.library_snapshot],
    ["Publication revision", data.revision],
    ["Collection", collections[options.kind]],
    ["Collection published", data.source.published_at || "Unknown"],
    ["Collection source SHA-256", data.source.sha256 || "Unavailable"],
    ["Collection provenance", data.source.source || "Unavailable"],
    ["Collection availability", data.source.state],
    ["Evidence filter", options.status],
    ["Minimum selected plays", options.minimum_plays],
    ["Search", options.search],
    [
      "Export scope",
      `Current page ${data.page}, at most ${data.limit} rows; ${data.total} filtered results`,
    ],
    [
      "Meaning",
      "Current published collection compared with selected history; exact names are candidate evidence, unmatched is unresolved, and membership is not historical.",
    ],
  ];
}

import { spotifyLink } from "./library-v1.js?v=15";
import {
  element,
  entityButton,
  number,
  recordedTime,
  renderTable,
} from "./tables-v1.js?v=7";

const $ = (id) => document.getElementById(id);
const reasons = {
  unmatched: "No exact name in liked tracks",
  ambiguous: "Multiple exact-name candidates",
  publication_unavailable: "Liked tracks unavailable",
  review_unavailable: "Reviewed Spotify URI unavailable",
};

function metrics(summary) {
  const node = $("playlist-metrics");
  node.replaceChildren();
  if (!summary) return;
  for (const [value, label] of [
    [summary.selected_plays, "Selected plays"],
    [summary.playlist_tracks, "Proposed tracks"],
    [summary.duplicate_plays, "Repeat plays"],
    [summary.unresolved_plays, "Unresolved plays"],
  ]) {
    const item = element("div");
    item.append(element("strong", number(value)), element("span", label));
    node.append(item);
  }
}

function resolvedRow(row, timezone) {
  const target = element("div");
  const link = spotifyLink(row.track.uri, row.track.name);
  if (link) target.append(link);
  target.append(element("small", row.track.artist, "playlist-credit"));
  return [
    row.position,
    target,
    entityButton(row.history, "track"),
    row.evidence === "reviewed"
      ? "Confirmed in Library Bridge"
      : "One exact name candidate",
    recordedTime(row.history.first_ms, timezone),
    number(row.plays),
    number(row.plays - 1),
  ];
}

function unresolvedRow(row, timezone) {
  return [
    entityButton(row.history, "track"),
    reasons[row.reason],
    number(row.candidate_count),
    recordedTime(row.history.first_ms, timezone),
    number(row.history.plays),
  ];
}

export function render(data, timezone) {
  metrics(data.summary);
  $("playlist-export").disabled = !data.summary?.playlist_tracks;
  $("playlist-source").textContent = data.source?.published_at
    ? `Liked tracks published ${recordedTime(Date.parse(data.source.published_at), timezone)}. ${data.source.message}`
    : data.source?.message || "";
  $("playlist-message").textContent =
    data.unavailable ||
    (data.summary?.selected_plays
      ? ""
      : "No recorded plays match this selection.");
  $("playlist-previous").disabled = !data.options || data.options.page <= 1;
  $("playlist-next").disabled =
    !data.options || data.options.page * data.options.limit >= data.total;
  $("playlist-page").textContent = data.options
    ? `Page ${number(data.options.page)} · ${number(data.total)} tracks`
    : "";
  if (!data.items) {
    $("playlist-table").replaceChildren();
    return;
  }
  if (data.options.view === "unresolved") {
    renderTable(
      "playlist-table",
      [
        "Recorded track",
        "Reason",
        "Exact candidates",
        "First selected play",
        "Plays",
      ],
      data.items.map((row) => unresolvedRow(row, timezone)),
    );
    return;
  }
  renderTable(
    "playlist-table",
    [
      "Position",
      "Spotify track",
      "Recorded track",
      "First match evidence",
      "First selected play",
      "Selected plays",
      "Repeat plays",
    ],
    data.items.map((row) => resolvedRow(row, timezone)),
  );
}

import * as charts from "./charts-v1.js?v=7";
import {
  element,
  entityButton,
  number,
  percent,
  recordedTime,
  renderTable,
} from "./tables-v1.js?v=7";

const $ = (id) => document.getElementById(id);
const outcomes = {
  tagged: "Available tags",
  empty: "Looked up · no tags",
  unresolved: "Artist unresolved",
  missing: "Not looked up",
};

export function progress(status) {
  const busy = ["running", "cancelling"].includes(status.state);
  $("tag-progress").textContent =
    `${status.state} · ${status.completed}/${status.total} completed in the latest batch. ${status.message}`;
  $("tag-progress").classList.toggle(
    "warning",
    status.state === "error" || !status.cache_available,
  );
  $("tag-fetch").disabled =
    busy || !status.configured || !status.cache_available;
  $("tag-cancel").disabled = !busy || status.state === "cancelling";
}

export function render(data, context) {
  if (data.unavailable) {
    $("tag-progress").textContent = data.unavailable;
    $("tag-coverage").textContent =
      "Tag metadata unavailable; actual listening totals remain available above.";
    $("tag-source").textContent = "";
    $("tag-artists-table").replaceChildren();
    $("tag-evolution-table").replaceChildren();
    $("tag-fetch").disabled = true;
    $("tag-cancel").disabled = true;
    charts.clearCharts();
    return;
  }
  const coverage = data.coverage;
  const share = coverage.plays ? coverage.tagged_plays / coverage.plays : 0;
  $("tag-coverage").textContent =
    `${number(coverage.tagged_plays)} of ${number(coverage.plays)} selected plays (${percent(share)}) have available artist tags. ${number(coverage.tagged_artists)} of ${number(coverage.artists)} artists have tags; ${number(coverage.looked_up_artists)} have completed lookups, including ${number(coverage.empty_artists)} empty and ${number(coverage.unresolved_artists)} unresolved results.`;
  $("tag-source").textContent = data.retrieved_from
    ? `Current cached labels retrieved ${recordedTime(Date.parse(data.retrieved_from), context.timezone)} through ${recordedTime(Date.parse(data.retrieved_through), context.timezone)}. These dates describe metadata retrieval, not historical genre labels.`
    : "No cached metadata for these artists yet. All plays remain visible in Unknown / no tags.";
  const selection = $("tag-filter").value;
  $("tag-filter").replaceChildren(new Option("All artist evidence", ""));
  for (const series of data.series)
    $("tag-filter").append(new Option(series.name, series.key));
  if (
    selection &&
    ![...$("tag-filter").options].some((option) => option.value === selection)
  )
    $("tag-filter").append(
      new Option("Selected tag outside the top eight", selection),
    );
  $("tag-filter").value = selection;
  charts.tags(data, $("tag-display").value, context);
  const rows = data.items.map((item) => [
    entityButton(item.artist, "artist"),
    number(item.artist.plays),
    outcomes[item.state],
    item.tags.map((tag) => tag.name).join(" · ") || "No available tags",
    item.fetched_at
      ? recordedTime(Date.parse(item.fetched_at), context.timezone)
      : "Not retrieved",
    sourceLink(item),
  ]);
  renderTable(
    "tag-artists-table",
    [
      "Artist",
      "Selected recorded plays",
      "Metadata coverage",
      "Ranked community labels (up to 10)",
      "Retrieved",
      "Source",
    ],
    rows,
  );
  renderTable(
    "tag-evolution-table",
    ["Month", ...data.series.map((series) => series.name)],
    data.periods.map((period, index) => [
      period,
      ...data.series.map((series) => series.counts[index].toFixed(2)),
    ]),
  );
  $("tag-page").textContent =
    `Page ${data.page} · ${number(data.total)} artists`;
  $("tag-previous").disabled = data.page <= 1;
  $("tag-next").disabled = data.page * data.limit >= data.total;
  progress(data.lookup);
}

function sourceLink(item) {
  if (!item.source_url) return "Not retrieved";
  const link = element("a", "Last.fm tags");
  const expected = `https://www.last.fm/music/${encodeURIComponent(item.artist.name)}/+tags`;
  // Links use a fixed public host and a name-derived path, never a provider URL.
  link.href = expected;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

export function notes(data) {
  return [
    ["Metadata snapshot", data.metadata_snapshot],
    ["Metadata source", "Last.fm artist.getTopTags"],
    [
      "Retrieval dates",
      `${data.retrieved_from || "None"} through ${data.retrieved_through || "None"}`,
    ],
    [
      "Allocation",
      data.options.per_artist === 1
        ? "Leading tag per artist"
        : "Equal allocation among up to three leading tags per artist",
    ],
    [
      "Interpretation",
      "Current community labels applied to historical plays; tags are not verified historical genres. Unknown includes missing, empty and unresolved metadata.",
    ],
  ];
}

export function evolutionCSV(data) {
  return data.periods.map((period, index) => [
    period,
    ...data.series.map((series) => series.counts[index]),
  ]);
}

export function artistsCSV(data) {
  return data.items.map((item) => [
    item.artist.key,
    item.artist.name,
    item.artist.plays,
    item.state,
    item.tags.map((tag) => tag.name).join("; "),
    item.fetched_at || "",
    item.source_url || "",
  ]);
}

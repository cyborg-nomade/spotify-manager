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
let world;
const regionNames = new Intl.DisplayNames(["en"], { type: "region" });
export const outcomes = {
  single_country: "One name candidate · one country",
  multiple_countries: "One candidate · multiple countries",
  no_country: "One candidate · no geographic country",
  unmatched: "No exact-name candidate",
  ambiguous: "Multiple name candidates",
  incomplete: "Search incomplete",
  missing: "Not looked up",
};
export function countryName(code) {
  return regionNames.of(code) || code;
}

export async function prepare(signal) {
  if (world) return true;
  try {
    const response = await fetch("/lastfm/assets/world-110m-v1.geojson", {
      signal,
    });
    if (!response.ok) return false;
    const value = await response.json();
    if (value.type !== "FeatureCollection" || !Array.isArray(value.features))
      return false;
    world = value;
    return true;
  } catch (error) {
    if (error.name === "AbortError") throw error;
    return false;
  }
}

export function progress(status) {
  const busy = ["running", "cancelling"].includes(status.state);
  $("origin-progress").textContent =
    `${status.state} · ${status.completed}/${status.total} completed in the latest batch. ${status.message}`;
  $("origin-progress").classList.toggle(
    "warning",
    status.state === "error" || !status.cache_available,
  );
  $("origin-fetch").disabled =
    busy || !status.configured || !status.cache_available;
  $("origin-cancel").disabled = !busy || status.state === "cancelling";
}

function candidateCell(item) {
  const cell = element("div");
  for (const candidate of item.candidates) {
    const row = element("p");
    const link = element("a", candidate.name);
    link.href = `https://musicbrainz.org/artist/${candidate.mbid}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    row.append(link);
    const codes =
      candidate.countries.map(countryName).join(" / ") || "No country reported";
    row.append(
      document.createTextNode(
        ` · ${candidate.artist_type || "Type unknown"}${candidate.description ? ` · ${candidate.description}` : ""} · ${codes}. Associated area: ${candidate.area || "Not reported"}. Birth/formation area: ${candidate.begin_area || "Not reported"}.`,
      ),
    );
    cell.append(row);
  }
  if (item.candidate_count > item.candidates.length)
    cell.append(
      element(
        "p",
        `${number(item.candidate_count)} exact-name candidates found; showing the first ${item.candidates.length}.`,
      ),
    );
  if (!item.candidates.length)
    cell.append(element("span", "No available candidate evidence"));
  return cell;
}

export function render(data, context) {
  if (data.unavailable) {
    $("origin-progress").textContent = data.unavailable;
    $("origin-coverage").textContent =
      "Country metadata unavailable; actual listening totals remain available above.";
    $("origin-source").textContent = "";
    for (const id of [
      "origin-artists-table",
      "origin-countries-table",
      "origin-coverage-table",
    ])
      $(id).replaceChildren();
    $("origin-fetch").disabled = true;
    $("origin-cancel").disabled = true;
    charts.clearCharts();
    $("origins-chart").replaceChildren();
    return;
  }
  const coverage = data.coverage;
  const share = coverage.plays ? coverage.country_plays / coverage.plays : 0;
  $("origin-coverage").textContent =
    `${number(coverage.country_plays)} of ${number(coverage.plays)} selected plays (${percent(share)}) have one exact-name candidate and one reported country. ${number(coverage.country_artists)} of ${number(coverage.artists)} artists support these totals; ${number(coverage.looked_up_artists)} have completed lookups. Names are evidence, not verified cross-service identities.`;
  $("origin-source").textContent = data.retrieved_from
    ? `Current metadata retrieved ${recordedTime(Date.parse(data.retrieved_from), context.timezone)} through ${recordedTime(Date.parse(data.retrieved_through), context.timezone)}. Country associations do not establish historical birthplace, nationality, or where you listened.`
    : "No country lookups cached for this selection yet. Every play remains included in the coverage table.";
  const selection = $("origin-country").value;
  $("origin-country").replaceChildren(
    new Option("All countries and unknowns", ""),
  );
  const codes = new Set(data.available_countries);
  if (selection) codes.add(selection);
  for (const code of [...codes].sort((a, b) =>
    countryName(a).localeCompare(countryName(b)),
  ))
    $("origin-country").append(new Option(countryName(code), code));
  $("origin-country").value = selection;
  if (data.map_ready && world) {
    $("origins-chart").querySelector("p")?.remove();
    charts.origins(data, world, $("origin-metric").value, context);
  } else {
    charts.clearCharts();
    $("origins-chart").replaceChildren(
      element(
        "p",
        "Map outlines are unavailable. Complete country counts and artist evidence remain in the tables below; retry this view to load the map.",
      ),
    );
  }
  renderTable(
    "origin-countries-table",
    [
      "Reported country",
      "Selected plays",
      "Artists",
      "Share of all selected plays",
    ],
    data.countries.map((item) => [
      countryName(item.code),
      number(item.plays),
      number(item.artists),
      percent(item.share),
    ]),
  );
  renderTable(
    "origin-coverage-table",
    ["Evidence", "Artists", "Selected plays"],
    coverage.outcomes.map((item) => [
      outcomes[item.evidence],
      number(item.artists),
      number(item.plays),
    ]),
  );
  renderTable(
    "origin-artists-table",
    [
      "Artist",
      "Selected plays",
      "Evidence",
      "MusicBrainz candidates · reported places",
      "Retrieved",
    ],
    data.items.map((item) => [
      entityButton(item.artist, "artist"),
      number(item.artist.plays),
      outcomes[item.evidence],
      candidateCell(item),
      item.fetched_at
        ? recordedTime(Date.parse(item.fetched_at), context.timezone)
        : "Not retrieved",
    ]),
  );
  $("origin-page").textContent =
    `Page ${data.page} · ${number(data.total)} artists`;
  $("origin-previous").disabled = data.page <= 1;
  $("origin-next").disabled = data.page * data.limit >= data.total;
  progress(data.lookup);
}

export function notes(data) {
  return [
    ["Metadata snapshot", data.metadata_snapshot],
    ["Metadata source", "MusicBrainz exact-name artist search"],
    [
      "Retrieval dates",
      `${data.retrieved_from || "None"} through ${data.retrieved_through || "None"}`,
    ],
    [
      "Interpretation",
      "Current country associations from a single exact-name candidate. Names do not verify identity. Ambiguous, multiple, missing and incomplete results are retained separately; historical origin and listening location are not inferred.",
    ],
    [
      "Country scope",
      "Full selected history before supporting evidence filters; small or historical countries may only appear in tables.",
    ],
  ];
}
export function countriesCSV(data) {
  const rows = data.countries.map((item) => [
    item.code,
    countryName(item.code),
    item.plays,
    item.artists,
    item.share,
  ]);
  rows.push([
    "",
    "Without single-country evidence",
    data.coverage.plays - data.coverage.country_plays,
    data.coverage.artists - data.coverage.country_artists,
    data.coverage.plays
      ? 1 - data.coverage.country_plays / data.coverage.plays
      : 0,
  ]);
  return rows;
}
export function artistsCSV(data) {
  return data.items.map((item) => [
    item.artist.key,
    item.artist.name,
    item.artist.plays,
    item.evidence,
    item.candidate_count,
    item.candidates
      .map(
        (c) =>
          `${c.mbid}: ${c.name}; ${c.countries.join(" / ")}; area=${c.area}; begin=${c.begin_area}; ${c.description}`,
      )
      .join(" | "),
    item.fetched_at || "",
  ]);
}

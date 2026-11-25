import * as charts from "./charts-v1.js?v=12";
import {
  element,
  entityButton,
  number,
  recordedTime,
  renderTable,
} from "./tables-v1.js?v=7";

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
const STORAGE_PREFIX = "listening-library-review-v1:";
const spotifyUri = /^spotify:(artist|album|track):([A-Za-z0-9]{22})$/;

function spotifyLink(uri, text) {
  const match = spotifyUri.exec(uri);
  if (!match) return null;
  const link = element("a", text);
  link.href = `https://open.spotify.com/${match[1]}/${match[2]}`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function validReview(value) {
  const uri = spotifyUri.exec(value?.uri);
  return (
    value &&
    uri &&
    uri[1] === value.kind &&
    /^[a-f0-9]{64}$/.test(value.key) &&
    /^v1-[a-f0-9]{64}$/.test(value.historySnapshot) &&
    /^l1-[a-f0-9]{64}$/.test(value.librarySnapshot) &&
    Number.isFinite(Date.parse(value.reviewedAt))
  );
}

function reviewKey(kind, key) {
  return `${kind}:${key}`;
}

export function reviewFor(kind, key) {
  try {
    const stored = JSON.parse(
      localStorage.getItem(STORAGE_PREFIX + reviewKey(kind, key)) ?? "null",
    );
    if (validReview(stored) && stored.kind === kind && stored.key === key)
      return stored;
  } catch {
    return undefined;
  }
}

function isCurrentReview(review, scope) {
  return Boolean(
    review &&
      review.historySnapshot === scope.historySnapshot &&
      review.librarySnapshot === scope.librarySnapshot,
  );
}

export function currentReview(kind, key, scope) {
  const review = reviewFor(kind, key);
  return isCurrentReview(review, scope) ? review : null;
}

export function playlistReviews(scope) {
  const prefix = STORAGE_PREFIX + "track:";
  try {
    return Object.keys(localStorage)
      .filter((key) => key.startsWith(prefix))
      .sort()
      .map((key) => reviewFor("track", key.slice(prefix.length)))
      .filter((review) => isCurrentReview(review, scope))
      .map(({ key, uri }) => ({ key, uri }));
  } catch {
    return [];
  }
}

export { spotifyLink };

export function storeReview(scope, uri) {
  const { kind, key, historySnapshot, librarySnapshot } = scope;
  const storeKey = STORAGE_PREFIX + reviewKey(kind, key);
  if (uri === null) {
    localStorage.removeItem(storeKey);
    return;
  }
  const review = {
    kind,
    key,
    historySnapshot,
    librarySnapshot,
    uri,
    reviewedAt: new Date().toISOString(),
  };
  if (!validReview(review)) throw new TypeError("Invalid publication review.");
  localStorage.setItem(storeKey, JSON.stringify(review));
}

function reviewBadge(node, review, scope) {
  node.replaceChildren();
  if (!review) return;
  if (!isCurrentReview(review, scope)) {
    node.textContent = "Review expired";
    return;
  }
  node.append(spotifyLink(review.uri, "Confirmed match"));
}

export function refreshReviewBadge(scope, review) {
  const badge = document.querySelector(
    `[data-library-review-badge="${reviewKey(scope.kind, scope.key)}"]`,
  );
  if (badge) reviewBadge(badge, review, scope);
}

export function reviewStatus(scope, review) {
  $("library-review-remove").hidden = !review;
  $("library-review-saved").textContent = isCurrentReview(review, scope)
    ? `Match confirmed in this browser on ${recordedTime(Date.parse(review.reviewedAt), scope.timezone)}.`
    : review
      ? "The previous review used a different publication. Confirm a candidate from this publication to renew it."
      : "";
}

export function renderReviewResults(data, scope, review) {
  const prior = isCurrentReview(review, scope) ? review.uri : null;
  const result = [];
  for (const candidate of data.items) {
    const { entry, exact_name } = candidate;
    const name = element("div");
    const link = spotifyLink(entry.uri, entry.name);
    if (!link) continue;
    name.append(link, element("small", entry.uri, "library-review-uri"));
    const selected = entry.uri === prior;
    const button = element(
      "button",
      selected ? "Confirmed" : "Confirm match",
      "small-button",
    );
    button.type = "button";
    button.dataset.libraryConfirmUri = entry.uri;
    button.disabled = selected;
    button.setAttribute(
      "aria-label",
      `${button.textContent} for ${entry.name}`,
    );
    result.push([
      name,
      entry.artist || "—",
      exact_name ? "Exact name" : "Search result",
      button,
    ]);
  }
  renderTable(
    "library-review-table",
    ["Published Spotify title", "Artist credit", "Name evidence", "Review"],
    result,
  );
  $("library-review-status").textContent =
    data.source.state !== "ready"
      ? data.source.message
      : data.total
        ? `${number(data.total)} candidates · Page ${number(data.page)} of ${number(Math.ceil(data.total / data.limit))}`
        : "No candidates in this publication. Try a title, artist credit, or Spotify URI.";
  $("library-review-previous").disabled = data.page <= 1;
  $("library-review-next").disabled = data.page * data.limit >= data.total;
  reviewStatus(scope, review);
}

function candidateLinks(item, kind, context, review) {
  const node = element("span");
  for (const candidate of item.candidates) {
    const link = spotifyLink(candidate.uri, candidate.name);
    if (link) node.append(link, document.createTextNode(" "));
  }
  if (item.candidate_count > item.candidates.length)
    node.append(
      element(
        "small",
        `Showing ${item.candidates.length} of ${item.candidate_count} candidates`,
      ),
    );
  if (review || ["unmatched", "ambiguous"].includes(item.status)) {
    const actions = element("div", undefined, "library-review-actions");
    const button = element("button", "Review match", "small-button");
    button.type = "button";
    button.dataset.libraryReviewKey = item.history.key;
    button.setAttribute("aria-label", `Review match for ${item.history.name}`);
    const badge = element("span");
    badge.dataset.libraryReviewBadge = reviewKey(kind, item.history.key);
    reviewBadge(badge, review, context);
    actions.append(button, badge);
    node.append(actions);
  }
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
  const scope = {
    historySnapshot: context.snapshot,
    librarySnapshot: data.library_snapshot,
  };
  const rows = data.items.map((item) => [
    entityButton(item.history, kind),
    number(item.history.plays),
    recordedTime(item.history.last_ms, context.timezone),
    labels[item.status],
    candidateLinks(item, kind, scope, reviewFor(kind, item.history.key)),
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

export function csv(data, context) {
  const scope = {
    historySnapshot: context.snapshot,
    librarySnapshot: data.library_snapshot,
  };
  return data.items.map((item) => {
    const review = reviewFor(data.options.kind, item.history.key);
    const current = isCurrentReview(review, scope);
    return [
      item.history.key,
      item.history.name,
      item.history.artist,
      item.history.plays,
      item.history.first_ms,
      item.history.last_ms,
      item.status,
      item.candidate_count,
      item.candidates.map((candidate) => candidate.uri).join("; "),
      current ? review.uri : "",
      current ? review.reviewedAt : "",
    ];
  });
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
    [
      "Reviewed matches",
      "Saved in this browser for the two pinned publications",
    ],
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

import { currentReview, spotifyLink } from "./library-v1.js?v=15";
import {
  element,
  entityButton,
  exportCSV,
  number,
  renderTable,
} from "./tables-v1.js?v=7";

const $ = (id) => document.getElementById(id);
const maxAlbums = 10;
let shortlist = null;
let scope = null;
let activeRead = null;
let loaded = new Map();

export function configureDates() {
  const custom = $("revisit-history").value === "selection";
  $("revisit-custom-dates").hidden = !custom;
  $("revisit-from").disabled = !custom;
  $("revisit-to").disabled = !custom;
}

export function historicalRange() {
  return shortlist?.dates.historical;
}

export function cancelRead() {
  activeRead?.abort();
  activeRead = null;
  updateButtons();
}

export function clear() {
  cancelRead();
  shortlist = null;
  scope = null;
  loaded.clear();
  for (const id of ["coverage", "library", "table", "message", "tracks"])
    $("revisit-" + id).replaceChildren();
  $("revisit-actions").hidden = true;
}

function savedEdition(option) {
  if (!shortlist.albums_ready) return null;
  const review = currentReview("album", option.album.key, {
    historySnapshot: shortlist.snapshot,
    librarySnapshot: shortlist.library_snapshot,
  });
  return review?.uri || option.spotify?.uri || null;
}

function coverage(data) {
  const {
    historical,
    recent,
    observed_from,
    observed_through,
    recent_complete,
  } = data.dates;
  const dates = `Then ${historical.start} to ${historical.end} · Now ${recent.start} to ${recent.end} · ${recent.timezone}.`;
  if (!recent_complete) {
    return `${dates} The archive does not cover the full recent window. Try a shorter window.`;
  }
  const counts =
    data.artists.length < data.qualifying
      ? `Showing ${number(data.artists.length)} of ${number(data.qualifying)} artists.`
      : `${number(data.qualifying)} matching artists.`;
  const partial =
    historical.start <= observed_from
      ? ` Historical coverage starts on ${observed_from}.`
      : "";
  return `${dates} ${counts}${partial} Recent history is measured through ${observed_through}, the last complete published day.`;
}

function albumStatus(option) {
  if (!shortlist.albums_ready) return "Saved albums unavailable";
  if (savedEdition(option)) return "Spotify edition available";
  if (option.exact_editions > 1) return "Multiple saved editions";
  return "No exact saved edition";
}

function renderArtist(artist, index) {
  const evidence = artist.evidence;
  const choices = element("div", undefined, "revisit-album");
  const select = element("select");
  select.dataset.revisitAlbum = index;
  select.setAttribute("aria-label", `Album for ${evidence.name}`);
  artist.albums.forEach((option, position) => {
    const { album } = option;
    select.append(
      new Option(
        `${album.name} · ${number(album.days)} listening ${album.days === 1 ? "day" : "days"} · ${albumStatus(option)}`,
        position,
      ),
    );
  });
  if (artist.albums.length) choices.append(select);
  else choices.append(element("span", "No album recorded in this period"));

  const checkbox = element("input");
  checkbox.type = "checkbox";
  checkbox.dataset.revisitInclude = index;
  checkbox.setAttribute("aria-label", `Include ${evidence.name}`);
  checkbox.disabled = !artist.albums[0] || !savedEdition(artist.albums[0]);
  const recent = evidence.recent_plays
    ? `${number(evidence.recent_tracks)} distinct ${evidence.recent_tracks === 1 ? "track" : "tracks"} on one day · ${number(evidence.recent_plays)} plays`
    : "No recorded plays";
  return [
    checkbox,
    entityButton(evidence, "artist"),
    `${number(evidence.historical_weeks)} listening weeks · ${number(evidence.historical_plays)} plays`,
    recent,
    choices,
  ];
}

export function render(result) {
  if (!result.data) {
    clear();
    $("revisit-coverage").textContent = result.message;
    return;
  }
  const next = JSON.stringify([
    result.snapshot,
    result.data.library_snapshot,
    result.data.dates,
    result.data.rules,
  ]);
  if (next !== scope) {
    clear();
    scope = next;
    shortlist = { ...result.data, snapshot: result.snapshot };
    if (shortlist.artists.length) {
      renderTable(
        "revisit-table",
        ["Include", "Artist", "Then", "Now", "Album to revisit"],
        shortlist.artists.map(renderArtist),
      );
      Array.from($("revisit-table").querySelectorAll("input:not(:disabled)"))
        .slice(0, 5)
        .forEach((input) => {
          input.checked = true;
        });
    }
  }
  $("revisit-coverage").textContent = coverage(shortlist);
  $("revisit-library").textContent =
    result.libraryMessage ||
    (shortlist.albums_ready
      ? "Playlist tracks come from the Spotify editions in your published saved albums."
      : "Saved albums are unavailable. You can still browse the artist and album suggestions.");
  $("revisit-actions").hidden =
    !shortlist.artists.length || !shortlist.albums_ready;
  updateButtons();
}

function selectedAlbums() {
  const table = $("revisit-table");
  return Array.from(table.querySelectorAll("input:checked")).map((input) => {
    const index = input.dataset.revisitInclude;
    const artist = shortlist.artists[index];
    const select = table.querySelector(`[data-revisit-album="${index}"]`);
    const option = artist.albums[Number(select.value)];
    return {
      artist: artist.evidence.name,
      name: option.album.name,
      uri: savedEdition(option),
    };
  });
}

function updateButtons() {
  const choices = selectedAlbums();
  const unique = new Set(choices.map((choice) => choice.uri));
  const eligible =
    choices.length > 0 &&
    choices.length <= maxAlbums &&
    unique.size === choices.length &&
    !unique.has(null);
  $("revisit-selection").textContent =
    choices.length && unique.size !== choices.length
      ? "Choose each Spotify edition only once."
      : `${choices.length} of ${maxAlbums} albums selected`;
  const complete = choices.every(
    (choice) => loaded.get(choice.uri)?.tracks.length,
  );
  $("revisit-preview").disabled = Boolean(activeRead) || !eligible || complete;
  $("revisit-export").disabled = Boolean(activeRead) || !eligible || !complete;
}

export function changeChoice(target) {
  if (target.matches("[data-revisit-album]")) {
    const checkbox = $("revisit-table").querySelector(
      `[data-revisit-include="${target.dataset.revisitAlbum}"]`,
    );
    const options = shortlist.artists[target.dataset.revisitAlbum].albums;
    checkbox.disabled = !savedEdition(options[Number(target.value)]);
    if (checkbox.disabled) checkbox.checked = false;
  }
  if (
    target.matches("[data-revisit-include]") &&
    selectedAlbums().length > maxAlbums
  )
    target.checked = false;
  cancelRead();
  loaded.clear();
  $("revisit-message").textContent = "";
  $("revisit-tracks").replaceChildren();
  updateButtons();
}

function renderTracklists(choices) {
  const panel = $("revisit-tracks");
  panel.replaceChildren();
  for (const album of choices) {
    const result = loaded.get(album.uri);
    const block = element("details", undefined, "revisit-tracklist");
    const link = spotifyLink(album.uri, "Open album in Spotify");
    const heading = `${album.artist} — ${album.name}`;
    const count = result?.tracks.length;
    block.append(
      element(
        "summary",
        `${heading} · ${count ? `${number(count)} tracks` : "Tracklist unavailable"}`,
      ),
    );
    if (link) block.append(link);
    if (!count) {
      block.open = true;
      block.append(
        element("p", result?.message || "Spotify did not return this album."),
      );
    } else {
      const tracks = element("ol");
      for (const track of result.tracks) {
        const item = element("li");
        const label = `${track.disc}.${track.track} ${track.name}`;
        item.append(
          spotifyLink(track.uri, label) || document.createTextNode(label),
        );
        tracks.append(item);
      }
      block.append(tracks);
    }
    panel.append(block);
  }
  const complete = choices.filter(
    (choice) => loaded.get(choice.uri)?.tracks.length,
  ).length;
  $("revisit-message").textContent =
    complete === choices.length
      ? `${number(complete)} albums ready in playlist order.`
      : `${number(complete)} of ${number(choices.length)} albums loaded. Use Preview album tracks to retry the unavailable albums.`;
}

export async function preview(request) {
  if (!shortlist || $("revisit-preview").disabled) return;
  const choices = selectedAlbums();
  const albums = choices
    .filter((choice) => !loaded.get(choice.uri)?.tracks.length)
    .map((choice) => choice.uri);
  if (!albums.length) return;
  const controller = new AbortController();
  activeRead = controller;
  const { historical } = shortlist.dates;
  const params = {
    from: historical.start,
    to: historical.end,
    tz: historical.timezone,
    snapshot: shortlist.snapshot,
    library_snapshot: shortlist.library_snapshot,
  };
  updateButtons();
  $("revisit-message").textContent =
    "Reading selected album tracklists from Spotify…";
  try {
    const result = await request(
      "/lastfm/analytics/rediscovery/album-tracklists",
      params,
      controller.signal,
      "POST",
      { body: { albums } },
    );
    if (controller.signal.aborted) return;
    if (
      result.snapshot !== params.snapshot ||
      result.data.library_snapshot !== params.library_snapshot
    )
      throw Object.assign(new Error(), { status: 409 });
    for (const album of result.data.albums) loaded.set(album.uri, album);
    renderTracklists(choices);
  } catch (error) {
    if (controller.signal.aborted) return;
    $("revisit-message").textContent =
      error.status === 409
        ? "A publication changed. Use Find artists to reload the shortlist."
        : "Spotify tracklists could not be loaded. Try Preview album tracks again.";
  } finally {
    if (activeRead === controller) cancelRead();
  }
}

export function csv() {
  if (!shortlist || $("revisit-export").disabled) return;
  const { historical, recent } = shortlist.dates;
  const rows = [];
  for (const album of selectedAlbums()) {
    for (const track of loaded.get(album.uri).tracks)
      rows.push([
        rows.length + 1,
        album.artist,
        album.name,
        album.uri,
        track.disc,
        track.track,
        track.name,
        track.uri,
      ]);
  }
  exportCSV(
    "rediscovery",
    [
      "Position",
      "Artist",
      "Album",
      "Spotify album URI",
      "Disc",
      "Track",
      "Spotify title",
      "Spotify track URI",
    ],
    rows,
    {
      snapshot: shortlist.snapshot,
      from: historical.start,
      to: historical.end,
      timezone: historical.timezone,
      notes: [
        ["Saved albums snapshot", shortlist.library_snapshot],
        ["Recent from", recent.start],
        ["Recent through", recent.end],
        ["Minimum historical plays", shortlist.rules.minimum_plays],
        ["Minimum historical listening weeks", shortlist.rules.minimum_weeks],
        ["Order", "Ranked artists, then Spotify disc and track number"],
      ],
    },
  );
}

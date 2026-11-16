// Text-only DOM rendering keeps recorded music names out of HTML parsing.
export const number = (value) => new Intl.NumberFormat().format(value);
export const percent = (value) => `${(100 * value).toFixed(1)}%`;

export function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

export function entityButton(item, kind) {
  const button = element("button", item.name, "entity-button");
  button.type = "button";
  button.dataset.entityKind = kind;
  button.dataset.entityKey = item.key;
  if (kind !== "artist" && item.artist)
    button.append(element("small", item.artist));
  return button;
}

export function renderTable(id, headers, rows) {
  const target = document.getElementById(id);
  target.replaceChildren();
  if (!rows.length) {
    target.append(
      element("p", "No recorded results for this selection.", "empty"),
    );
    return;
  }
  const table = element("table");
  const head = element("thead");
  const header = element("tr");
  for (const title of headers) {
    const th = element("th", title);
    th.scope = "col";
    header.append(th);
  }
  head.append(header);
  table.append(head);
  const body = element("tbody");
  for (const cells of rows) {
    const row = element("tr");
    for (const value of cells) {
      const cell = element("td");
      cell.append(
        value instanceof Node
          ? value
          : document.createTextNode(String(value ?? "")),
      );
      row.append(cell);
    }
    body.append(row);
  }
  table.append(body);
  target.append(table);
}

export function rankingTable(id, data, kind) {
  const rows = data.items.map((item, index) => [
    number((data.page - 1) * data.limit + index + 1),
    entityButton(item, kind),
    number(item.plays),
    percent(item.share),
  ]);
  renderTable(
    id,
    ["#", kind === "artist" ? "Artist" : "Music / artist", "Plays", "Share"],
    rows,
  );
}

export function recordedTime(timestamp, timezone) {
  if (!Number.isFinite(timestamp)) return "Unknown timestamp";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(timestamp));
}

export function recordsTable(data, timezone) {
  const rows = data.items.map((item) => [
    recordedTime(item.timestamp_ms, timezone),
    item.track,
    entityButton({ key: item.artist_key, name: item.artist }, "artist"),
    item.album || "Album not recorded",
  ]);
  renderTable(
    "records-table",
    ["Recorded at", "Track", "Artist", "Album"],
    rows,
  );
}

export function returnRate(returned, eligible, artists) {
  if (!eligible) return `${artists} pending`;
  const pending = artists - eligible;
  return `${percent(returned / eligible)} · ${returned}/${eligible}${pending ? ` · ${pending} pending` : ""}`;
}

export function csvCell(value) {
  let text = String(value ?? "");
  // Prevent music titles from becoming executable formulas in spreadsheet apps.
  if (typeof value === "string" && /^[\s]*[=+\-@\t\r]/.test(text))
    text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function download(filename, blob) {
  const link = element("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function exportCSV(name, headers, rows, context) {
  const metadata = [
    ["Source snapshot", context.snapshot],
    ["From", context.from],
    ["Through", context.to],
    ["Timezone", context.timezone],
    ["Artist filter", context.artist || "All artists"],
    ["Weekday filter (Monday=0)", context.weekday ?? "All weekdays"],
    ["Hour filter", context.hour ?? "All hours"],
    [],
    headers,
  ];
  const csv = [...metadata, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n");
  download(
    `listening-${name}-${context.from}-${context.to}.csv`,
    new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }),
  );
}

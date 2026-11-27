import { api } from "./requests-v1.js";

const sources = document.querySelectorAll("[data-server-file-date]");
const summary = document.getElementById("serverFilesSummary");
const sharedState = document.getElementById("sharedStateUpdatedAt");

function formatPublication(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function setSourceDate(element, label, missing = false) {
  element.textContent = label;
  element.classList.toggle("missing", missing);
}

function renderSources({ files = [] } = {}) {
  const publications = new Map(files.map((file) => [file.filename, file]));
  for (const source of sources) {
    const file = publications.get(source.dataset.serverFileDate);
    if (file?.exists && file.updated_at) {
      setSourceDate(source, formatPublication(file.updated_at));
    } else {
      setSourceDate(source, "Missing", true);
    }
  }
  const available = files.filter((file) => file.exists).length;
  summary.textContent = `${available} / ${files.length} sources available`;
}

export function renderSharedStateStatus({ updated_at, namespaces } = {}) {
  const count = Object.keys(namespaces || {}).length;
  const namespaceCount = `${count} ${count === 1 ? "namespace" : "namespaces"}`;
  const label = updated_at
    ? `${formatPublication(updated_at)} · ${namespaceCount}`
    : namespaceCount;
  setSourceDate(sharedState, label);
}

export async function loadServerFilesStatus() {
  try {
    renderSources(await api("/library-mirrors/status"));
  } catch {
    for (const source of sources) setSourceDate(source, "Unavailable", true);
    summary.textContent = "Status unavailable";
  }
  try {
    renderSharedStateStatus(await api("/state/summary"));
  } catch {
    setSourceDate(sharedState, "Unavailable", true);
  }
}

export function setMirrorMode(resource, mode) {
  const controls = document.querySelectorAll(
    `[data-action="mirrorMode"][data-resource="${resource}"]`,
  );
  for (const button of controls) {
    const active = button.dataset.mirrorMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

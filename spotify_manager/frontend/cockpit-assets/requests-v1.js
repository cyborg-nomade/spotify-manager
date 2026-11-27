let password = null;

export function setPassword(value) {
  password = value;
}

export function hasPassword() {
  return password !== null;
}

function headers() {
  return { "X-App-Password": password || "" };
}

async function request(path, { method = "GET", json } = {}) {
  const requestHeaders = headers();
  if (json !== undefined) requestHeaders["Content-Type"] = "application/json";
  try {
    return await fetch(path, {
      method,
      headers: requestHeaders,
      body: json === undefined ? undefined : JSON.stringify(json),
    });
  } catch {
    throw { status: 0, detail: "Network error — is the server awake?" };
  }
}

function readJSON(response) {
  return response.json().catch(() => null);
}

export async function api(path, options) {
  const response = await request(path, options);
  const data = await readJSON(response);
  const status = response.status;
  if (status === 401) throw { status, detail: "Wrong or missing password." };
  if (!response.ok) {
    const message = data?.detail || data?.message || `HTTP ${status}`;
    const detail =
      typeof message === "object"
        ? message.message || JSON.stringify(message)
        : message;
    throw { status, detail, data };
  }
  return data;
}

export async function downloadAttachment(path, fallbackFilename) {
  const response = await request(path);
  if (!response.ok) {
    const data = await readJSON(response);
    throw {
      status: response.status,
      detail: data?.detail || `HTTP ${response.status}`,
    };
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const filename =
    disposition.match(/filename="([^"]+)"/)?.[1] || fallbackFilename;
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

import { api, setPassword } from "./requests-v1.js";

// Genre Reveal reads this same tab-scoped handoff.
const SESSION_PREFIX = "sm_pw:";

function savedPassword() {
  try {
    return window.name.startsWith(SESSION_PREFIX)
      ? window.name.slice(SESSION_PREFIX.length)
      : "";
  } catch {
    return "";
  }
}

function rememberPassword(candidate) {
  try {
    window.name = candidate ? SESSION_PREFIX + candidate : "";
  } catch {
    // The cockpit remains usable when the browser restricts window.name.
  }
}

async function validatePassword(candidate) {
  setPassword(candidate);
  try {
    await api("/auth/check");
  } catch (error) {
    // Any other HTTP response crossed the application's password gate.
    if (error.status && error.status !== 401) return "";
    setPassword(null);
    return error.status === 401
      ? "Wrong password"
      : error.detail || "Could not reach server";
  }
  return "";
}

export function bindSession({ onUnlock, notify }) {
  const gate = document.getElementById("gate");
  const app = document.getElementById("app");
  const form = document.getElementById("unlockForm");
  const password = document.getElementById("pw");
  const remember = document.getElementById("remember");
  const unlockButton = document.getElementById("pwBtn");

  async function unlock(candidate, keepSignedIn) {
    if (unlockButton.disabled) return;
    unlockButton.disabled = true;
    form.setAttribute("aria-busy", "true");
    const error = await validatePassword(candidate);
    unlockButton.disabled = false;
    form.removeAttribute("aria-busy");
    if (error) {
      notify(error, "err");
      password.focus();
      return;
    }
    if (keepSignedIn) rememberPassword(candidate);
    password.value = "";
    gate.hidden = true;
    app.hidden = false;
    document.getElementById("cockpitTitle").focus();
    await onUnlock();
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    unlock(password.value, remember.checked);
  });
  document.getElementById("logout").addEventListener("click", () => {
    setPassword(null);
    rememberPassword("");
    app.hidden = true;
    gate.hidden = false;
    password.focus();
  });

  const saved = savedPassword();
  if (saved) unlock(saved, true);
}

export async function checkHealth() {
  const health = document.getElementById("health");
  let state = "offline";
  try {
    state = (await fetch("/health")).ok ? "online" : "error";
  } catch {
    // Keep the offline state for a network failure.
  }
  health.dataset.state = state;
  document.getElementById("healthTxt").textContent = state;
}

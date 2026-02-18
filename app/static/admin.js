const authSection = document.getElementById("auth-section");
const adminShell = document.getElementById("admin-shell");
const loginForm = document.getElementById("login-form");
const loginUsernameInput = document.getElementById("login-username");
const loginPasswordInput = document.getElementById("login-password");
const authError = document.getElementById("auth-error");
const sessionLabel = document.getElementById("session-label");



function bindPasswordToggles(root = document) {
  root.querySelectorAll("button[data-toggle-password][data-target]").forEach((button) => {
    if (button.dataset.bound === "true") return;
    button.dataset.bound = "true";

    button.addEventListener("click", () => {
      const targetId = button.dataset.target;
      const input = document.getElementById(targetId);
      if (!input) return;

      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
      button.setAttribute("aria-pressed", String(show));
    });
  });
}
const menuToggle = document.getElementById("menu-toggle");
const userMenu = document.getElementById("user-menu");
const themeSelect = document.getElementById("theme-select");
const logoutBtn = document.getElementById("logout-btn");

const adminUsersBody = document.getElementById("admin-users-body");
const adminMessage = document.getElementById("admin-message");
const createUserForm = document.getElementById("create-user-form");
const newUserUsernameInput = document.getElementById("new-user-username");
const newUserPasswordInput = document.getElementById("new-user-password");
const setPasswordModal = document.getElementById("set-password-modal");
const setPasswordForm = document.getElementById("set-password-form");
const setPasswordInput = document.getElementById("set-password-input");
const setPasswordUser = document.getElementById("set-password-user");
const closeSetPasswordBtn = document.getElementById("close-set-password");
const newUserRoleSelect = document.getElementById("new-user-role");

const settingsForm = document.getElementById("settings-form");
const defaultCurrencyInput = document.getElementById("default-currency");
const resetInstanceBtn = document.getElementById("reset-instance-btn");

const createTokenForm = document.getElementById("create-token-form");
const newTokenNameInput = document.getElementById("new-token-name");
const tokenCreatedLabel = document.getElementById("token-created");
const apiTokensBody = document.getElementById("api-tokens-body");

let currentUser = null;

function normalizeTheme(theme) {
  if (theme === "dark") return "midnight";
  if (["light", "midnight", "oled"].includes(theme)) return theme;
  return "midnight";
}



async function updateMyThemePreference(theme) {
  if (!currentUser) return;
  try {
    await apiFetch("/users/me/theme", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme }),
    });
  } catch {
    // Non-fatal; keep local preference.
  }
}
function setTheme(theme) {
  const normalized = normalizeTheme(theme);
  document.documentElement.setAttribute("data-theme", normalized);
  localStorage.setItem("theme:last", normalized);
  if (currentUser?.username) localStorage.setItem(`theme:user:${currentUser.username}`, normalized);
  if (themeSelect) themeSelect.value = normalized;
}

(function initTheme() {
  const saved = localStorage.getItem("theme:last");
  setTheme(saved || "midnight");
})();

bindPasswordToggles();

if (themeSelect) {
  themeSelect.addEventListener("change", () => {
    setTheme(themeSelect.value);
    updateMyThemePreference(themeSelect.value);
    closeMenu();
  });
}

function openMenu() {
  userMenu.hidden = false;
}

function closeMenu() {
  userMenu.hidden = true;
}

menuToggle.addEventListener("click", () => {
  if (userMenu.hidden) openMenu(); else closeMenu();
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".menu-wrap")) closeMenu();
});

function showAuthOnly() {
  currentUser = null;
  authSection.hidden = false;
  adminShell.hidden = true;
  authError.textContent = "";
}

function showAdmin() {
  authSection.hidden = true;
  adminShell.hidden = false;
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    showAuthOnly();
    throw new Error("Authentication required");
  }
  return response;
}

async function refreshSession() {
  try {
    const response = await apiFetch("/auth/me");
    if (!response.ok) {
      showAuthOnly();
      return false;
    }

    const data = await response.json();
    if (data.role !== "admin") {
      window.location.href = "/";
      return false;
    }

    currentUser = data;
    if (data.theme) setTheme(data.theme);
    localStorage.setItem("theme:last", normalizeTheme(data.theme || "midnight"));
    localStorage.setItem(`theme:user:${data.username}`, normalizeTheme(data.theme || "midnight"));
    sessionLabel.textContent = `Signed in as ${data.username} (admin)`;
    showAdmin();
    return true;
  } catch {
    showAuthOnly();
    return false;
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authError.textContent = "";

  const payload = {
    username: loginUsernameInput.value.trim(),
    password: loginPasswordInput.value,
  };

  const response = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    authError.textContent = data.detail || "Login failed";
    return;
  }

  loginPasswordInput.value = "";
  await initializeAdmin();
  if (!currentUser) {
    const isHttp = window.location && window.location.protocol === "http:";
    authError.textContent = isHttp
      ? "Login succeeded but your session could not be established. This often means SESSION_COOKIE_SECURE=true while using http://. Use https:// via your reverse proxy, or set SESSION_COOKIE_SECURE=false for local http."
      : "Login succeeded but your session could not be established. Check reverse proxy forwarded headers and cookie settings.";
  }
});

logoutBtn.addEventListener("click", async () => {
  try {
    await fetch("/auth/logout", { method: "POST" });
  } finally {
    showAuthOnly();
    closeMenu();
  }
});

function setAdminMessage(message, isError = false) {
  adminMessage.textContent = message;
  adminMessage.className = isError ? "err-text" : "";
}



async function loadApiTokens() {
  if (!apiTokensBody) return;

  const response = await apiFetch("/admin/api-tokens");
  if (!response.ok) return;

  const tokens = await response.json();
  apiTokensBody.innerHTML = "";

  if (!tokens.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="7" class="muted">No tokens created yet.</td>';
    apiTokensBody.appendChild(tr);
    return;
  }

  tokens.forEach((t) => {
    const tr = document.createElement("tr");
    const revokeBtn = t.revoked
      ? '<span class="muted">Revoked</span>'
      : `<button class="danger table-btn" type="button" data-revoke-token-id="${t.id}">Revoke</button>`;

    tr.innerHTML = `
      <td data-label="ID">${t.id}</td>
      <td data-label="Name">${t.name}</td>
      <td data-label="Prefix">${t.token_prefix}</td>
      <td data-label="Scope">${t.scope}</td>
      <td data-label="Revoked">${t.revoked ? "yes" : "no"}</td>
      <td data-label="Last Used">${t.last_used_at ? new Date(t.last_used_at).toLocaleString() : ""}</td>
      <td data-label="Actions">${revokeBtn}</td>
    `;
    apiTokensBody.appendChild(tr);
  });

  apiTokensBody.querySelectorAll("button[data-revoke-token-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const tokenId = Number(btn.dataset.revokeTokenId);
      if (!tokenId) return;
      if (!window.confirm(`Revoke token #${tokenId}?`)) return;

      const resp = await apiFetch(`/admin/api-tokens/${tokenId}/revoke`, { method: "PATCH" });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        setAdminMessage(`Revoke failed: ${data.detail || resp.status}`, true);
        return;
      }

      setAdminMessage(`Token #${tokenId} revoked.`);
      await loadApiTokens();
    });
  });
}
async function loadAdminUsers() {
  const response = await apiFetch("/admin/users");
  if (!response.ok) return;

  const users = await response.json();
  adminUsersBody.innerHTML = "";

  users.forEach((user) => {
    const tr = document.createElement("tr");
    const deleteAction = user.id === currentUser.id
      ? "Current"
      : `<button class=\"danger table-btn\" data-delete-user-id=\"${user.id}\" type=\"button\">Delete</button>`;

    const passwordAction = `<button class=\"secondary table-btn\" data-password-user-id=\"${user.id}\" type=\"button\">Set Password</button>`;

    tr.innerHTML = `<td data-label="ID">${user.id}</td><td data-label="Username">${user.username}</td><td data-label="Role">${user.role}</td><td data-label="Actions">${passwordAction} ${deleteAction}</td>`;
    adminUsersBody.appendChild(tr);
  });

  adminUsersBody.querySelectorAll("button[data-delete-user-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const userId = Number(button.dataset.deleteUserId);
      if (!window.confirm(`Delete user #${userId}?`)) return;

      const response = await apiFetch(`/admin/users/${userId}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setAdminMessage(`Delete user failed: ${data.detail || response.status}`, true);
        return;
      }

      setAdminMessage(`User #${userId} deleted.`);
      await loadAdminUsers();
    });
  });

  adminUsersBody.querySelectorAll("button[data-password-user-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const userId = Number(button.dataset.passwordUserId);
      if (!userId) return;

      setPasswordUser.textContent = `#${userId}`;
      setPasswordInput.value = "";
      setPasswordModal.dataset.userId = String(userId);
      bindPasswordToggles(setPasswordModal);
      setPasswordModal.showModal();
    });
  });
}

createUserForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    username: newUserUsernameInput.value.trim(),
    password: newUserPasswordInput.value,
    role: newUserRoleSelect.value,
  };

  const response = await apiFetch("/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    setAdminMessage(`Create user failed: ${data.detail || response.status}`, true);
    return;
  }

  setAdminMessage(`User ${payload.username} created.`);
  newUserPasswordInput.value = "";
  await loadAdminUsers();
});

async function loadSettings() {
  const response = await apiFetch("/admin/settings");
  if (!response.ok) return;

  const data = await response.json();
  defaultCurrencyInput.value = data.default_currency || "USD";
}

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = { default_currency: defaultCurrencyInput.value.trim().toUpperCase() };

  const response = await apiFetch("/admin/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    setAdminMessage(`Save settings failed: ${data.detail || response.status}`, true);
    return;
  }

  setAdminMessage("Default currency updated.");
});

resetInstanceBtn.addEventListener("click", async () => {
  const confirmed = window.prompt("Type DELETE to reset the entire instance:");
  if (confirmed !== "DELETE") {
    setAdminMessage("Instance reset cancelled.");
    return;
  }

  const response = await apiFetch("/admin/reset-instance", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: "DELETE" }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    setAdminMessage(`Instance reset failed: ${data.detail || response.status}`, true);
    return;
  }

  setAdminMessage("Instance reset complete.");
  await loadAdminUsers();
});

async function initializeAdmin() {
  const ok = await refreshSession();
  if (!ok) return;
  await loadAdminUsers();
  await loadApiTokens();
  await loadSettings();
}

initializeAdmin();


if (closeSetPasswordBtn) {
  closeSetPasswordBtn.addEventListener("click", () => {
    setPasswordModal.close();
  });
}

if (setPasswordForm) {
  setPasswordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const userId = Number(setPasswordModal.dataset.userId || "0");
    const newPassword = setPasswordInput.value;
    if (!userId) return;
    if (!newPassword || newPassword.length < 12) {
      setAdminMessage("Password must be at least 12 characters.", true);
      return;
    }

    const response = await apiFetch(`/admin/users/${userId}/password`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: newPassword }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      setAdminMessage(`Password update failed: ${data.detail || response.status}`, true);
      return;
    }

    setAdminMessage(`Password updated for user #${userId}.`);
    setPasswordModal.close();
  });
}

async function handleCreateTokenSubmit(event) {
  event.preventDefault();
  if (!newTokenNameInput) return;

  const name = newTokenNameInput.value.trim();
  if (!name) {
    setAdminMessage("Token name is required.", true);
    return;
  }

  try {
    const payload = { name, scope: "upload" };
    const response = await apiFetch("/admin/api-tokens", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      setAdminMessage(`Create token failed: ${data.detail || response.status}`, true);
      return;
    }

    const data = await response.json();
    const token = data.token;

    if (tokenCreatedLabel) {
      tokenCreatedLabel.textContent = `Token (save it now): ${token}`;
    }

    newTokenNameInput.value = "";
    setAdminMessage("Token created. Copy it now; it will not be shown again.");
    await loadApiTokens();
  } catch (error) {
    setAdminMessage(`Create token failed: ${error?.message || "unexpected error"}`, true);
  }
}

if (createTokenForm) {
  // Belt-and-suspenders: avoid browser default form navigation.
  createTokenForm.setAttribute("action", "javascript:void(0)");
  createTokenForm.addEventListener("submit", handleCreateTokenSubmit);
}

// Fallback delegated handler in case this form is re-rendered.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.id !== "create-token-form") return;
  handleCreateTokenSubmit(event);
});

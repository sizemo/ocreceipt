const authSection = document.getElementById("auth-section");
const adminShell = document.getElementById("admin-shell");
const loginForm = document.getElementById("login-form");
const loginUsernameInput = document.getElementById("login-username");
const loginPasswordInput = document.getElementById("login-password");
const authError = document.getElementById("auth-error");
const sessionLabel = document.getElementById("session-label");

const menuToggle = document.getElementById("menu-toggle");
const userMenu = document.getElementById("user-menu");
const themeSelect = document.getElementById("theme-select");
const logoutBtn = document.getElementById("logout-btn");

const adminUsersBody = document.getElementById("admin-users-body");
const adminMessage = document.getElementById("admin-message");
const createUserForm = document.getElementById("create-user-form");
const newUserUsernameInput = document.getElementById("new-user-username");
const newUserPasswordInput = document.getElementById("new-user-password");
const newUserRoleSelect = document.getElementById("new-user-role");

const settingsForm = document.getElementById("settings-form");
const defaultCurrencyInput = document.getElementById("default-currency");
const resetInstanceBtn = document.getElementById("reset-instance-btn");

let currentUser = null;

function normalizeTheme(theme) {
  if (theme === "dark") return "midnight";
  if (["light", "midnight", "oled"].includes(theme)) return theme;
  return "midnight";
}

function setTheme(theme) {
  const normalized = normalizeTheme(theme);
  document.documentElement.setAttribute("data-theme", normalized);
  localStorage.setItem("theme", normalized);
  if (themeSelect) themeSelect.value = normalized;
}

(function initTheme() {
  const saved = localStorage.getItem("theme");
  setTheme(saved || "midnight");
})();

if (themeSelect) {
  themeSelect.addEventListener("change", () => {
    setTheme(themeSelect.value);
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
    button.addEventListener("click", async () => {
      const userId = Number(button.dataset.passwordUserId);
      const newPassword = window.prompt(`Enter new password for user #${userId}:`);
      if (!newPassword) return;

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
  await loadSettings();
}

initializeAdmin();

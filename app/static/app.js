const authSection = document.getElementById("auth-section");
const appShell = document.getElementById("app-shell");
const loginForm = document.getElementById("login-form");
const loginUsernameInput = document.getElementById("login-username");
const loginPasswordInput = document.getElementById("login-password");
const authError = document.getElementById("auth-error");
const sessionLabel = document.getElementById("session-label");

const menuToggle = document.getElementById("menu-toggle");
const userMenu = document.getElementById("user-menu");
const adminLink = document.getElementById("admin-link");
const themeSelect = document.getElementById("theme-select");
const logoutBtn = document.getElementById("logout-btn");

const fileInput = document.getElementById("file-input");
const dropzone = document.getElementById("dropzone");
const uploadBtn = document.getElementById("upload-btn");
const uploadList = document.getElementById("upload-list");
const receiptsBody = document.getElementById("receipts-body");
const refreshBtn = document.getElementById("refresh-btn");

const receiptModal = document.getElementById("receipt-modal");
const receiptModalImage = document.getElementById("receipt-modal-image");
const closeModalBtn = document.getElementById("close-modal-btn");

const editModal = document.getElementById("edit-modal");
const editForm = document.getElementById("edit-form");
const cancelEditBtn = document.getElementById("cancel-edit-btn");
const editIdInput = document.getElementById("edit-id");
const editDateInput = document.getElementById("edit-date");
const editMerchantInput = document.getElementById("edit-merchant");
const merchantSuggestions = document.getElementById("merchant-suggestions");
const editTotalInput = document.getElementById("edit-total");
const editTaxInput = document.getElementById("edit-tax");
const editModalImage = document.getElementById("edit-modal-image");
const editModalImageHint = document.getElementById("edit-modal-image-hint");

const filterDateFromInput = document.getElementById("filter-date-from");
const filterDateToInput = document.getElementById("filter-date-to");
const filterMerchantInput = document.getElementById("filter-merchant");
const filterReviewSelect = document.getElementById("filter-review");
const applyFiltersBtn = document.getElementById("apply-filters-btn");
const clearFiltersBtn = document.getElementById("clear-filters-btn");
const merchantFilterList = document.getElementById("merchant-filter-list");

let selectedFiles = [];
let receiptRows = [];
let merchantSearchAbort = null;
let currentUser = null;
let defaultCurrency = "USD";

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

(function initTheme() {
  const saved = localStorage.getItem("theme");
  setTheme(saved || "midnight");
})();

bindPasswordToggles();

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
  if (userMenu.hidden) {
    openMenu();
  } else {
    closeMenu();
  }
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".menu-wrap")) {
    closeMenu();
  }
});

function isAdmin() {
  return currentUser?.role === "admin";
}

function setAdminVisibility() {
  const adminOnlyElements = document.querySelectorAll(".admin-only");
  adminOnlyElements.forEach((element) => {
    if (isAdmin()) {
      element.classList.remove("role-hidden");
    } else {
      element.classList.add("role-hidden");
    }
  });
  adminLink.hidden = !isAdmin();
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    showAuthOnly();
    throw new Error("Authentication required");
  }
  return response;
}

function showAuthOnly() {
  currentUser = null;
  authSection.hidden = false;
  appShell.hidden = true;
  authError.textContent = "";
  closeMenu();
}

function showAppShell() {
  authSection.hidden = true;
  appShell.hidden = false;
}

function setSessionLabel() {
  if (!currentUser) {
    sessionLabel.textContent = "Signed out";
    return;
  }
  sessionLabel.textContent = `Signed in as ${currentUser.username} (${currentUser.role})`;
}

async function refreshSession() {
  try {
    const response = await apiFetch("/auth/me");
    if (!response.ok) {
      showAuthOnly();
      return false;
    }

    const data = await response.json();
    currentUser = { id: data.id, username: data.username, role: data.role };
    defaultCurrency = data.default_currency || "USD";
    setSessionLabel();
    setAdminVisibility();
    showAppShell();
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
  await initializeAuthenticatedApp();
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

function addFiles(fileList) {
  if (!isAdmin()) {
    appendStatus("Only admin users can upload receipts.", "err");
    return;
  }

  const files = Array.from(fileList);
  const supportedFiles = files.filter((file) => file.type.startsWith("image/") || file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
  const skipped = files.length - supportedFiles.length;

  if (skipped > 0) {
    appendStatus(`Skipped ${skipped} unsupported file(s). Only images and PDFs are allowed.`, "err");
  }

  selectedFiles = [...selectedFiles, ...supportedFiles];
  renderSelectedFiles();
}

function renderSelectedFiles() {
  uploadList.innerHTML = "";
  if (selectedFiles.length === 0) {
    const item = document.createElement("li");
    item.textContent = "No files selected.";
    uploadList.appendChild(item);
    return;
  }

  selectedFiles.forEach((file, index) => {
    const item = document.createElement("li");
    item.innerHTML = `<span>${index + 1}. ${file.name}</span><span>${(file.size / 1024).toFixed(1)} KB</span>`;
    uploadList.appendChild(item);
  });
}

fileInput.addEventListener("change", (event) => {
  addFiles(event.target.files);
  fileInput.value = "";
});

dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropzone.classList.add("dragover");
});

dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("dragover");
});

dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragover");
  addFiles(event.dataTransfer.files);
});

dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

function createStatusRow(fileName) {
  const item = document.createElement("li");
  const left = document.createElement("span");
  const right = document.createElement("span");
  left.textContent = fileName;
  right.textContent = "Queued";
  item.appendChild(left);
  item.appendChild(right);
  uploadList.appendChild(item);
  return { item, right };
}

function updateStatusRow(statusRow, message, className = "") {
  statusRow.right.textContent = message;
  statusRow.item.className = className;
}

function uploadOne(file, onUploadFinished) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/receipts/upload");

    xhr.upload.addEventListener("load", () => {
      if (typeof onUploadFinished === "function") {
        onUploadFinished();
      }
    });

    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.onload = () => {
      let payload = {};
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : {};
      } catch {
        payload = {};
      }

      if (xhr.status === 401) {
        showAuthOnly();
        reject(new Error("Authentication required"));
        return;
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(payload.detail || `Upload failed (${xhr.status})`));
        return;
      }

      resolve(payload);
    };

    xhr.send(formData);
  });
}

function appendStatus(message, className = "") {
  const item = document.createElement("li");
  if (className) item.className = className;
  item.textContent = message;
  uploadList.appendChild(item);
}

uploadBtn.addEventListener("click", async () => {
  if (!isAdmin()) {
    appendStatus("Only admin users can upload receipts.", "err");
    return;
  }
  if (selectedFiles.length === 0) {
    appendStatus("Select at least one image first.", "err");
    return;
  }

  uploadBtn.disabled = true;
  uploadBtn.textContent = "Uploading...";

  const queue = [...selectedFiles];
  selectedFiles = [];
  renderSelectedFiles();

  let success = 0;
  let ocrComplete = 0;

  for (const file of queue) {
    const statusRow = createStatusRow(file.name);
    updateStatusRow(statusRow, "Uploading file...", "");

    try {
      const result = await uploadOne(file, () => updateStatusRow(statusRow, "Upload finished. OCR running...", ""));
      ocrComplete += 1;
      success += 1;
      updateStatusRow(statusRow, result.needs_review ? "OCR complete (needs review)" : "OCR complete", result.needs_review ? "err" : "ok");
    } catch (error) {
      updateStatusRow(statusRow, `Failed (${error.message})`, "err");
    }
  }

  uploadBtn.disabled = false;
  uploadBtn.textContent = "Upload selected files";
  appendStatus(`Done: ${success}/${queue.length} uploaded, OCR completed for ${ocrComplete}.`);
  await loadMerchantFilterOptions();
  await loadReceipts();
});

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "-";
  const currency = /^[A-Z]{3}$/.test(defaultCurrency) ? defaultCurrency : "USD";
  return Number(value).toLocaleString(undefined, { style: "currency", currency });
}

function formatDate(value) {
  if (!value) return "-";

  if (typeof value === "string") {
    const dateOnly = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (dateOnly) {
      const year = Number(dateOnly[1]);
      const month = Number(dateOnly[2]) - 1;
      const day = Number(dateOnly[3]);
      return new Date(year, month, day).toLocaleDateString();
    }
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

function formatConfidence(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${Number(value).toFixed(1)}%`;
}

function toDateInputValue(value) {
  if (!value) return "";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString().slice(0, 10);
}

function viewReceipt(imageUrl) {
  receiptModalImage.src = imageUrl;
  receiptModal.showModal();
}

closeModalBtn.addEventListener("click", () => {
  receiptModal.close();
  receiptModalImage.src = "";
});

receiptModal.addEventListener("click", (event) => {
  if (event.target === receiptModal) {
    receiptModal.close();
    receiptModalImage.src = "";
  }
});


function clearEditPreview() {
  if (!editModalImage) return;
  editModalImage.src = "";
  editModalImage.hidden = true;
  if (editModalImageHint) editModalImageHint.hidden = true;
}

if (editModalImage) {
  editModalImage.addEventListener("click", () => {
    if (editModalImage.src) viewReceipt(editModalImage.src);
  });
}

function openEditModal(receiptId) {
  if (!isAdmin()) return;
  const row = receiptRows.find((item) => item.id === receiptId);
  if (!row) return;

  editIdInput.value = String(row.id);
  editDateInput.value = toDateInputValue(row.purchase_date);
  editMerchantInput.value = row.merchant || "";
  editTotalInput.value = row.total_amount ?? "";
  editTaxInput.value = row.sales_tax_amount ?? "";
  if (editModalImage) {
    if (row.image_url) {
      editModalImage.src = row.image_url;
      editModalImage.hidden = false;
      if (editModalImageHint) editModalImageHint.hidden = false;
    } else {
      editModalImage.src = "";
      editModalImage.hidden = true;
      if (editModalImageHint) editModalImageHint.hidden = true;
    }
  }
  hideMerchantSuggestions();
  editModal.showModal();
}

cancelEditBtn.addEventListener("click", () => {
  hideMerchantSuggestions();
  clearEditPreview();
  editModal.close();
});

editModal.addEventListener("click", (event) => {
  if (event.target === editModal) {
    hideMerchantSuggestions();
    clearEditPreview();
    editModal.close();
  }
});

function showMerchantSuggestions(names) {
  merchantSuggestions.innerHTML = "";
  if (!names.length) {
    merchantSuggestions.classList.remove("open");
    return;
  }

  names.forEach((name) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion-item";
    button.textContent = name;
    button.addEventListener("click", () => {
      editMerchantInput.value = name;
      hideMerchantSuggestions();
      editMerchantInput.focus();
    });
    merchantSuggestions.appendChild(button);
  });
  merchantSuggestions.classList.add("open");
}

function hideMerchantSuggestions() {
  merchantSuggestions.innerHTML = "";
  merchantSuggestions.classList.remove("open");
}

async function fetchMerchantSuggestions(query) {
  if (merchantSearchAbort) merchantSearchAbort.abort();
  merchantSearchAbort = new AbortController();

  try {
    const response = await apiFetch(`/merchants?query=${encodeURIComponent(query)}&limit=8`, {
      signal: merchantSearchAbort.signal,
    });
    if (!response.ok) return;
    const payload = await response.json();
    showMerchantSuggestions(payload.merchants || []);
  } catch (error) {
    if (error.name !== "AbortError") hideMerchantSuggestions();
  }
}

editMerchantInput.addEventListener("input", () => {
  const query = editMerchantInput.value.trim();
  if (!query) {
    hideMerchantSuggestions();
    return;
  }
  fetchMerchantSuggestions(query);
});

editMerchantInput.addEventListener("blur", () => setTimeout(hideMerchantSuggestions, 120));

async function saveEdit(event) {
  event.preventDefault();
  if (!isAdmin()) return;

  const receiptId = Number(editIdInput.value);
  if (!receiptId) return;

  const payload = {
    purchase_date: editDateInput.value || null,
    merchant: editMerchantInput.value.trim() || null,
    total_amount: editTotalInput.value === "" ? null : Number(editTotalInput.value),
    sales_tax_amount: editTaxInput.value === "" ? null : Number(editTaxInput.value),
  };

  const response = await apiFetch(`/receipts/${receiptId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) return;
  appendStatus(`Updated receipt #${receiptId}.`, "ok");
  hideMerchantSuggestions();
  clearEditPreview();
  editModal.close();
  await loadMerchantFilterOptions();
  await loadReceipts();
}

editForm.addEventListener("submit", saveEdit);

async function markReviewed(receiptId) {
  if (!isAdmin()) return;
  const response = await apiFetch(`/receipts/${receiptId}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewed: true }),
  });
  if (!response.ok) return;
  await loadReceipts();
}

async function deleteReceipt(receiptId) {
  if (!isAdmin()) return;
  if (!window.confirm(`Delete receipt #${receiptId}? This cannot be undone.`)) return;

  const response = await apiFetch(`/receipts/${receiptId}`, { method: "DELETE" });
  if (!response.ok) return;
  await loadReceipts();
}

async function loadMerchantFilterOptions() {
  const response = await apiFetch("/merchants?limit=500");
  if (!response.ok) return;

  const payload = await response.json();
  merchantFilterList.innerHTML = "";
  (payload.merchants || []).forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    merchantFilterList.appendChild(option);
  });
}

function buildReceiptFiltersQuery() {
  const params = new URLSearchParams();
  const dateFrom = filterDateFromInput.value;
  const dateTo = filterDateToInput.value;
  const merchant = filterMerchantInput.value.trim();
  const review = filterReviewSelect.value;

  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (merchant) params.set("merchant", merchant);
  if (review === "reviewed") params.set("reviewed", "true");
  if (review === "needs_review") params.set("reviewed", "false");

  const query = params.toString();
  return query ? `?${query}` : "";
}

applyFiltersBtn.addEventListener("click", loadReceipts);
clearFiltersBtn.addEventListener("click", () => {
  filterDateFromInput.value = "";
  filterDateToInput.value = "";
  filterMerchantInput.value = "";
  filterReviewSelect.value = "all";
  loadReceipts();
});

async function loadReceipts() {
  const response = await apiFetch(`/receipts${buildReceiptFiltersQuery()}`);
  if (!response.ok) return;

  const rows = await response.json();
  receiptRows = rows;
  receiptsBody.innerHTML = "";

  const admin = isAdmin();
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="no-results" colspan="${admin ? 11 : 9}">No receipts found for current filters.</td>`;
    receiptsBody.appendChild(tr);
    return;
  }

  rows.forEach((row) => {
    const receiptCell = row.image_url
      ? `<button class="secondary table-btn" type="button" data-image-url="${row.image_url}">View</button>`
      : '<span class="muted">Missing</span>';

    const reviewCell = row.needs_review && admin
      ? `<div class="review-cell"><span class="badge review">Needs Review</span><button class="secondary table-btn" type="button" data-mark-reviewed-id="${row.id}">Mark reviewed</button></div>`
      : row.needs_review
        ? '<span class="badge review">Needs Review</span>'
        : '<span class="badge good">Reviewed</span>';

    const adminCells = admin
      ? `<td data-label="Edit"><button class="secondary table-btn" type="button" data-edit-id="${row.id}">Edit</button></td>
         <td data-label="Delete"><button class="danger table-btn" type="button" data-delete-id="${row.id}">Delete</button></td>`
      : "";

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td data-label="ID">${row.id}</td>
      <td data-label="Date">${formatDate(row.purchase_date)}</td>
      <td data-label="Merchant">${row.merchant || "-"}</td>
      <td data-label="Total">${formatMoney(row.total_amount)}</td>
      <td data-label="Sales Tax">${formatMoney(row.sales_tax_amount)}</td>
      <td data-label="Confidence">${formatConfidence(row.extraction_confidence)}</td>
      <td data-label="Review">${reviewCell}</td>
      <td data-label="Created">${formatDate(row.created_at)}</td>
      <td data-label="Receipt">${receiptCell}</td>
      ${adminCells}
    `;
    receiptsBody.appendChild(tr);
  });

  receiptsBody.querySelectorAll("button[data-image-url]").forEach((button) => {
    button.addEventListener("click", () => viewReceipt(button.dataset.imageUrl));
  });
  receiptsBody.querySelectorAll("button[data-edit-id]").forEach((button) => {
    button.addEventListener("click", () => openEditModal(Number(button.dataset.editId)));
  });
  receiptsBody.querySelectorAll("button[data-delete-id]").forEach((button) => {
    button.addEventListener("click", () => deleteReceipt(Number(button.dataset.deleteId)));
  });
  receiptsBody.querySelectorAll("button[data-mark-reviewed-id]").forEach((button) => {
    button.addEventListener("click", () => markReviewed(Number(button.dataset.markReviewedId)));
  });
}

refreshBtn.addEventListener("click", loadReceipts);

async function initializeAuthenticatedApp() {
  const ok = await refreshSession();
  if (!ok) return;
  renderSelectedFiles();
  await loadMerchantFilterOptions();
  await loadReceipts();
}

initializeAuthenticatedApp();

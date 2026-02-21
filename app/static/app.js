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
const uploadStatus = document.getElementById("upload-status");
const receiptsBody = document.getElementById("receipts-body");
const receiptsTable = receiptsBody?.closest("table");
const refreshBtn = document.getElementById("refresh-btn");
const exportCsvLink = document.getElementById("export-csv-link");
const sortStatus = document.getElementById("sort-status");

const receiptModal = document.getElementById("receipt-modal");
const receiptModalImage = document.getElementById("receipt-modal-image");
const receiptModalPages = document.getElementById("receipt-modal-pages");
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
const editSourceHelper = document.getElementById("edit-source-helper");
const editSourceList = document.getElementById("edit-source-list");

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

let sortState = { key: "created_at", dir: "desc" };
let currentEditRow = null;

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

function setVisualAccessibility(enabled) {
  document.documentElement.setAttribute("data-visual-accessibility", enabled ? "on" : "off");
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
  const saved = localStorage.getItem("theme:last");
  setTheme(saved || "midnight");
})();

setVisualAccessibility(true);

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
    if (data.theme) setTheme(data.theme);
    localStorage.setItem("theme:last", normalizeTheme(data.theme || "midnight"));
    localStorage.setItem(`theme:user:${data.username}`, normalizeTheme(data.theme || "midnight"));
    defaultCurrency = data.default_currency || "USD";
    setVisualAccessibility(data.visual_accessibility_enabled !== false);
    setSessionLabel();
    setAdminVisibility();
    showAppShell();
    return true;
  } catch {
    showAuthOnly();
    return false;
  }
}



function setFieldInvalid(input, invalid) {
  if (!input) return;
  input.setAttribute("aria-invalid", invalid ? "true" : "false");
}

function bindInvalidClear(input) {
  if (!input) return;
  input.addEventListener("input", () => setFieldInvalid(input, false));
}

[loginUsernameInput, loginPasswordInput].forEach(bindInvalidClear);

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authError.textContent = "";

  setFieldInvalid(loginUsernameInput, false);
  setFieldInvalid(loginPasswordInput, false);

  const payload = {
    username: loginUsernameInput.value.trim(),
    password: loginPasswordInput.value,
  };

  if (!payload.username || !payload.password) {
    setFieldInvalid(loginUsernameInput, !payload.username);
    setFieldInvalid(loginPasswordInput, !payload.password);
    authError.textContent = "Username and password are required.";
    return;
  }

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
  if (uploadStatus) uploadStatus.textContent = message;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

async function pollUploadJob(jobId, statusRow) {
  const startedAt = Date.now();
  const timeoutMs = 15 * 60 * 1000;

  while (true) {
    const response = await apiFetch(`/upload-jobs/${jobId}`);
    if (!response.ok) {
      const details = await response.json().catch(() => ({}));
      throw new Error(details.detail || `Job status failed (${response.status})`);
    }

    const job = await response.json();
    if (job.status === "queued") {
      updateStatusRow(statusRow, "Upload finished. OCR queued...", "");
    } else if (job.status === "processing") {
      updateStatusRow(statusRow, "Upload finished. OCR running...", "");
    } else if (job.status === "completed") {
      return job;
    } else if (job.status === "failed") {
      throw new Error(job.error_message || "OCR failed");
    }

    if (Date.now() - startedAt > timeoutMs) {
      throw new Error("OCR polling timed out");
    }
    await sleep(1200);
  }
}

function appendStatus(message, className = "") {
  const item = document.createElement("li");
  if (className) item.className = className;
  item.textContent = message;
  uploadList.appendChild(item);
  if (uploadStatus) uploadStatus.textContent = message;
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
  uploadList?.setAttribute("aria-busy", "true");

  const queue = [...selectedFiles];
  selectedFiles = [];
  renderSelectedFiles();

  let uploaded = 0;
  let ocrComplete = 0;

  for (const file of queue) {
    const statusRow = createStatusRow(file.name);
    updateStatusRow(statusRow, "Uploading file...", "");

    try {
      const accepted = await uploadOne(file, () => updateStatusRow(statusRow, "Upload transfer complete. Waiting for OCR queue...", ""));
      uploaded += 1;

      const jobId = Number(accepted.id || 0);
      if (!jobId) {
        throw new Error("Upload accepted but no job id was returned");
      }

      await pollUploadJob(jobId, statusRow);
      ocrComplete += 1;
      updateStatusRow(statusRow, "OCR complete", "ok");
    } catch (error) {
      updateStatusRow(statusRow, `Failed (${error.message})`, "err");
    }
  }

  uploadBtn.disabled = false;
  uploadBtn.textContent = "Upload selected files";
  uploadList?.setAttribute("aria-busy", "false");
  appendStatus(`Done: ${uploaded}/${queue.length} uploaded, OCR completed for ${ocrComplete}.`);
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



const dialogFocusState = new WeakMap();

function getFocusableWithin(root) {
  if (!root) return [];
  return Array.from(root.querySelectorAll('a[href], button:not([disabled]), textarea, input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'))
    .filter((el) => !el.hasAttribute('hidden'));
}

function openDialogA11y(dialog, initialFocusEl) {
  if (!dialog || dialog.open) return;

  const previous = document.activeElement;
  const keyHandler = (event) => {
    if (event.key !== 'Tab') return;
    const focusables = getFocusableWithin(dialog);
    if (!focusables.length) return;

    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  dialogFocusState.set(dialog, { previous, keyHandler });
  dialog.addEventListener('keydown', keyHandler);
  dialog.showModal();

  const target = initialFocusEl || getFocusableWithin(dialog)[0];
  if (target) target.focus();
}

function closeDialogA11y(dialog) {
  if (!dialog || !dialog.open) return;
  dialog.close();
}

function cleanupDialogA11y(dialog) {
  const state = dialogFocusState.get(dialog);
  if (!state) return;
  dialog.removeEventListener('keydown', state.keyHandler);
  if (state.previous && typeof state.previous.focus === 'function') {
    state.previous.focus();
  }
  dialogFocusState.delete(dialog);
}
async function viewReceipt(target) {
  receiptModalImage.hidden = true;
  receiptModalImage.src = "";
  if (receiptModalPages) {
    receiptModalPages.hidden = false;
    receiptModalPages.innerHTML = '<p class="muted">Loading receipt preview...</p>';
  }

  openDialogA11y(receiptModal, closeModalBtn);

  if (typeof target !== "number" || Number.isNaN(target)) {
    receiptModalImage.src = String(target || "");
    receiptModalImage.hidden = false;
    if (receiptModalPages) {
      receiptModalPages.hidden = true;
      receiptModalPages.innerHTML = "";
    }
    return;
  }

  try {
    const response = await apiFetch('/receipts/' + target + '/preview');
    if (!response.ok) throw new Error('Failed to load receipt preview');

    const preview = await response.json();
    const pages = Array.isArray(preview.pages) ? preview.pages : [];

    if (preview.kind === 'pdf' && pages.length > 0 && receiptModalPages) {
      receiptModalPages.innerHTML = '';
      pages.forEach((pageUrl, index) => {
        const img = document.createElement('img');
        img.src = pageUrl;
        img.alt = 'Receipt page ' + (index + 1);
        img.loading = 'lazy';
        receiptModalPages.appendChild(img);
      });
      receiptModalPages.hidden = false;
      receiptModalImage.hidden = true;
      return;
    }

    receiptModalImage.src = preview.image_url || ('/receipts/' + target + '/preview-image');
    receiptModalImage.hidden = false;
    if (receiptModalPages) {
      receiptModalPages.hidden = true;
      receiptModalPages.innerHTML = '';
    }
  } catch (error) {
    if (receiptModalPages) {
      receiptModalPages.hidden = false;
      receiptModalPages.innerHTML = '<p class="err-text">' + (error.message || 'Failed to load preview.') + '</p>';
    }
  }
}

closeModalBtn.addEventListener("click", () => {
  closeDialogA11y(receiptModal);
  receiptModalImage.src = "";
  receiptModalImage.hidden = true;
  if (receiptModalPages) {
    receiptModalPages.innerHTML = "";
    receiptModalPages.hidden = true;
  }
});

receiptModal.addEventListener("click", (event) => {
  if (event.target === receiptModal) {
    closeDialogA11y(receiptModal);
    receiptModalImage.src = "";
    receiptModalImage.hidden = true;
    if (receiptModalPages) {
      receiptModalPages.innerHTML = "";
      receiptModalPages.hidden = true;
    }
  }
});
receiptModal.addEventListener("close", () => cleanupDialogA11y(receiptModal));


function clearEditPreview() {
  if (!editModalImage) return;
  editModalImage.src = "";
  editModalImage.hidden = true;
  if (editModalImageHint) editModalImageHint.hidden = true;
}

function clearEditSourceHelper() {
  if (editSourceList) editSourceList.innerHTML = "";
  if (editSourceHelper) editSourceHelper.hidden = true;
}

function _normalizeComparable(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9.]/g, "");
}

function _moneyNeedle(value) {
  if (value === null || value === undefined || value === "") return "";
  const num = Number(value);
  if (!Number.isFinite(num)) return "";
  return num.toFixed(2);
}

function _highlightLine(line, needle) {
  if (!needle) return line;
  const idx = line.toLowerCase().indexOf(String(needle).toLowerCase());
  if (idx < 0) return line;
  return `${line.slice(0, idx)}<mark>${line.slice(idx, idx + needle.length)}</mark>${line.slice(idx + needle.length)}`;
}

function _findLine(lines, predicate) {
  for (const line of lines) {
    if (predicate(line)) return line;
  }
  return "";
}

function renderEditSourceHelper(row) {
  if (!editSourceHelper || !editSourceList) return;
  const raw = String(row?.raw_ocr_text || "").trim();
  if (!raw) {
    clearEditSourceHelper();
    return;
  }

  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const dateValue = editDateInput?.value || toDateInputValue(row?.purchase_date);
  const totalValue = _moneyNeedle(editTotalInput?.value !== "" ? editTotalInput.value : row?.total_amount);
  const taxValue = _moneyNeedle(editTaxInput?.value !== "" ? editTaxInput.value : row?.sales_tax_amount);

  const dateNeedles = [];
  if (dateValue && /^\d{4}-\d{2}-\d{2}$/.test(dateValue)) {
    const [y, m, d] = dateValue.split("-");
    dateNeedles.push(`${m}/${d}/${y}`);
    dateNeedles.push(`${m}-${d}-${y}`);
    dateNeedles.push(`${y}-${m}-${d}`);
    dateNeedles.push(`${m}/${d}/${y.slice(2)}`);
  }

  const dateLine = _findLine(lines, (line) => {
    const low = line.toLowerCase();
    return dateNeedles.some((needle) => low.includes(needle.toLowerCase())) ||
      ((low.includes("date") || low.includes("purchase")) && /\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}/.test(low));
  });

  const totalLine = _findLine(lines, (line) => {
    const low = line.toLowerCase();
    if (!(low.includes("total") || low.includes("amount due") || low.includes("balance due"))) return false;
    if (low.includes("subtotal") || low.includes("tax")) return false;
    if (!totalValue) return true;
    return _normalizeComparable(line).includes(_normalizeComparable(totalValue));
  });

  const taxLine = _findLine(lines, (line) => {
    const low = line.toLowerCase();
    if (!(low.includes("tax") || low.includes("hst") || low.includes("gst") || low.includes("vat"))) return false;
    if (taxValue && !_normalizeComparable(line).includes(_normalizeComparable(taxValue))) return false;
    if (/\d+(?:\.\d+)?\s*%/.test(line) && !/\$\s*\d+\.\d{2}/.test(line)) return false;
    return true;
  });

  const items = [
    { label: "Date", line: dateLine, needle: dateNeedles[0] || "" },
    { label: "Total", line: totalLine, needle: totalValue },
    { label: "Sales tax", line: taxLine, needle: taxValue },
  ];

  editSourceList.innerHTML = "";
  let found = 0;
  for (const item of items) {
    const li = document.createElement("li");
    if (item.line) {
      found += 1;
      li.innerHTML = `<strong>${item.label}:</strong> ${_highlightLine(item.line, item.needle)}`;
    } else {
      li.innerHTML = `<strong>${item.label}:</strong> <span class="muted">No likely source line found.</span>`;
    }
    editSourceList.appendChild(li);
  }

  editSourceHelper.hidden = found === 0;
}

if (editModalImage) {
  editModalImage.addEventListener("click", () => {
    const receiptId = Number(editModalImage.dataset.receiptId || "0");
    if (receiptId) {
      viewReceipt(receiptId);
      return;
    }
    if (editModalImage.src) viewReceipt(editModalImage.src);
  });
}

function openEditModal(receiptId) {
  if (!isAdmin()) return;
  const row = receiptRows.find((item) => item.id === receiptId);
  if (!row) return;
  currentEditRow = row;

  editIdInput.value = String(row.id);
  editDateInput.value = toDateInputValue(row.purchase_date);
  editMerchantInput.value = row.merchant || "";
  editTotalInput.value = row.total_amount ?? "";
  editTaxInput.value = row.sales_tax_amount ?? "";
  if (editModalImage) {
    if (row.image_url) {
      editModalImage.src = row.image_url;
      editModalImage.dataset.receiptId = String(row.id);
      editModalImage.hidden = false;
      if (editModalImageHint) editModalImageHint.hidden = false;
    } else {
      editModalImage.src = "";
      editModalImage.hidden = true;
      if (editModalImageHint) editModalImageHint.hidden = true;
    }
  }
  hideMerchantSuggestions();
  renderEditSourceHelper(row);
  openDialogA11y(editModal, editDateInput);
}

cancelEditBtn.addEventListener("click", () => {
  hideMerchantSuggestions();
  clearEditPreview();
  clearEditSourceHelper();
  currentEditRow = null;
  closeDialogA11y(editModal);
});

editModal.addEventListener("click", (event) => {
  if (event.target === editModal) {
    hideMerchantSuggestions();
    clearEditPreview();
    clearEditSourceHelper();
    currentEditRow = null;
    closeDialogA11y(editModal);
  }
});
editModal.addEventListener("close", () => {
  cleanupDialogA11y(editModal);
  clearEditSourceHelper();
  currentEditRow = null;
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

[editDateInput, editTotalInput, editTaxInput].forEach((el) => {
  if (!el) return;
  el.addEventListener("input", () => {
    if (currentEditRow) renderEditSourceHelper(currentEditRow);
  });
});

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
  clearEditSourceHelper();
  currentEditRow = null;
  closeDialogA11y(editModal);
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


function compareMaybeNull(a, b, dir) {
  const aNull = a === null || a === undefined || a === "";
  const bNull = b === null || b === undefined || b === "";
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;
  return dir === "asc" ? (a > b ? 1 : a < b ? -1 : 0) : (a < b ? 1 : a > b ? -1 : 0);
}

function applySort(rows) {
  const { key, dir } = sortState;
  const factor = dir === "asc" ? 1 : -1;

  const getVal = (row) => {
    if (key === "reviewed") return row.needs_review ? 0 : 1;
    if (key === "purchase_date" || key === "created_at") {
      const v = row[key];
      if (!v) return null;
      const d = new Date(v);
      return Number.isNaN(d.getTime()) ? null : d.getTime();
    }
    if (key === "merchant") return (row.merchant || "").toLowerCase();
    if (["id", "total_amount", "sales_tax_amount", "extraction_confidence"].includes(key)) {
      const v = row[key];
      return v === null || v === undefined || v === "" ? null : Number(v);
    }
    return row[key];
  };

  // Stable sort
  return rows
    .map((row, idx) => ({ row, idx }))
    .sort((a, b) => {
      const av = getVal(a.row);
      const bv = getVal(b.row);

      if (key === "merchant") {
        const c = compareMaybeNull(av, bv, dir);
        return c !== 0 ? c : a.idx - b.idx;
      }

      const c = compareMaybeNull(av, bv, dir);
      return c !== 0 ? c : a.idx - b.idx;
    })
    .map((x) => x.row);
}

function updateSortIndicators() {
  if (!receiptsTable) return;
  let activeSortLabel = "";
  receiptsTable.querySelectorAll("button.th-sort[data-sort]").forEach((btn) => {
    const k = btn.dataset.sort;
    const th = btn.closest("th");
    if (k === sortState.key) {
      btn.dataset.dir = sortState.dir;
      activeSortLabel = btn.textContent || k;
      if (th) th.setAttribute("aria-sort", sortState.dir === "asc" ? "ascending" : "descending");
    } else {
      btn.removeAttribute("data-dir");
      if (th) th.setAttribute("aria-sort", "none");
    }
  });

  if (sortStatus && activeSortLabel) {
    sortStatus.textContent =       `Sorted by ${activeSortLabel} ${sortState.dir === "asc" ? "ascending" : "descending"}.`;
  }
}

function bindTableSorting() {
  if (!receiptsTable) return;

  receiptsTable.querySelectorAll("button.th-sort[data-sort]").forEach((btn) => {
    if (btn.dataset.bound === "true") return;
    btn.dataset.bound = "true";

    btn.addEventListener("click", () => {
      const key = btn.dataset.sort;
      if (!key) return;
      if (sortState.key === key) {
        sortState.dir = sortState.dir === "asc" ? "desc" : "asc";
      } else {
        sortState.key = key;
        sortState.dir = "asc";
      }
      updateSortIndicators();
      renderReceipts();
    });
  });

  updateSortIndicators();
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


function setDefaultYearFilters() {
  if (!filterDateFromInput || !filterDateToInput) return;

  // Only set defaults if the user hasn't already chosen something.
  if (filterDateFromInput.value || filterDateToInput.value) return;

  const now = new Date();
  const year = now.getFullYear();
  filterDateFromInput.value = `${year}-01-01`;
  filterDateToInput.value = `${year}-12-31`;
}


function updateExportCsvLink() {
  if (!exportCsvLink) return;
  exportCsvLink.href = `/receipts/export${buildReceiptFiltersQuery()}`;
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

applyFiltersBtn.addEventListener("click", () => { updateExportCsvLink(); loadReceipts(); });
clearFiltersBtn.addEventListener("click", () => {
  updateExportCsvLink();
  filterDateFromInput.value = "";
  filterDateToInput.value = "";
  filterMerchantInput.value = "";
  filterReviewSelect.value = "all";
  loadReceipts();
});


[filterDateFromInput, filterDateToInput, filterMerchantInput, filterReviewSelect].forEach((el) => {
  if (!el) return;
  el.addEventListener("change", updateExportCsvLink);
});


function renderReceipts() {
  const rows = applySort(receiptRows || []);
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
      ? `<button class="secondary table-btn" type="button" data-receipt-id="${row.id}">View</button>`
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

  receiptsBody.querySelectorAll("button[data-receipt-id]").forEach((button) => {
    button.addEventListener("click", () => viewReceipt(Number(button.dataset.receiptId)));
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

async function loadReceipts() {
  const response = await apiFetch(`/receipts${buildReceiptFiltersQuery()}`);
  if (!response.ok) return;

  receiptRows = await response.json();
  updateExportCsvLink();
  renderReceipts();
  bindTableSorting();
}

refreshBtn.addEventListener("click", loadReceipts);

async function initializeAuthenticatedApp() {
  const ok = await refreshSession();
  if (!ok) return;
  renderSelectedFiles();
  setDefaultYearFilters();
  updateExportCsvLink();
  await loadMerchantFilterOptions();
  await loadReceipts();
}

initializeAuthenticatedApp();

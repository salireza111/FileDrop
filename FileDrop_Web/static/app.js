const state = {
  ws: null,
  sessionId: null,
  deviceId: null,
  connected: false,
  name: "",
  code: "",
  info: null,
  clients: [],
  selectedSessions: new Set(),
  canReceive: true,
  hidden: new Set(),
  isAdmin: false,
};

const shareUrlEl = document.getElementById("shareUrl");
const qrImgEl = document.getElementById("qrImg");
const qrHintEl = document.getElementById("qrHint");
const copyBtn = document.getElementById("copyBtn");
const nameInput = document.getElementById("nameInput");
const codeInput = document.getElementById("codeInput");
const codeField = document.getElementById("codeField");
const connectBtn = document.getElementById("connectBtn");
const statusEl = document.getElementById("status");
const fileInput = document.getElementById("fileInput");
const uploadBtn = document.getElementById("uploadBtn");
const uploadStatus = document.getElementById("uploadStatus");
const uploadFileName = document.getElementById("uploadFileName");
const uploadSpeed = document.getElementById("uploadSpeed");
const uploadBar = document.getElementById("uploadBar");
const noteInput = document.getElementById("noteInput");
const sendNoteBtn = document.getElementById("sendNoteBtn");
const noteStatus = document.getElementById("noteStatus");
const notesEl = document.getElementById("notes");
const fileListEl = document.getElementById("fileList");
const clientListEl = document.getElementById("clientList");
const clientHint = document.getElementById("clientHint");
const themeSelect = document.getElementById("themeSelect");
const saveDirLabel = document.getElementById("saveDirLabel");
const saveHint = document.getElementById("saveHint");
const chooseDirBtn = document.getElementById("chooseDirBtn");
const receiveToggle = document.getElementById("receiveToggle");
const panelMenuBtn = document.getElementById("panelMenuBtn");
const panelMenu = document.getElementById("panelMenu");

const PANEL_KEYS = ["share", "connect", "send", "notes", "files", "clients"];
const PANEL_SIZES = {
  share: 2,
  connect: 1,
  send: 1,
  notes: 2,
  files: 1,
  clients: 1,
};

function setStatus(text, ok = false) {
  statusEl.textContent = text;
  statusEl.style.background = ok ? "#e6f6f0" : "#fff8f0";
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function getDeviceId() {
  const key = "filedrop_device_id";
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    sessionStorage.setItem(key, id);
  }
  return id;
}

function applyTheme(theme) {
  document.body.dataset.theme = theme;
  sessionStorage.setItem("filedrop_theme", theme);
}

function updateAdminUI() {
  chooseDirBtn.disabled = !state.isAdmin;
  if (!state.isAdmin) {
    chooseDirBtn.title = "Only the server can choose the folder";
    if (saveHint) {
      saveHint.textContent = "Server storage path (host only). Downloads save to your device.";
    }
  } else {
    chooseDirBtn.title = "";
    if (saveHint) {
      saveHint.textContent = "Server storage path (host only).";
    }
  }
}

function syncSelections() {
  const valid = new Set(state.clients.map((c) => c.session_id));
  state.selectedSessions.forEach((id) => {
    if (!valid.has(id)) state.selectedSessions.delete(id);
  });
}

async function loadInfo() {
  const res = await fetch("/api/info");
  state.info = await res.json();
  const shareUrl = state.info.lan_url || window.location.origin;
  if (typeof state.info.is_admin === "boolean") {
    state.isAdmin = state.info.is_admin;
    updateAdminUI();
  }
  shareUrlEl.value = shareUrl;
  qrImgEl.src = `/api/qr?url=${encodeURIComponent(shareUrl)}`;
  qrHintEl.textContent = `Scan to open ${shareUrl}`;
  if (state.info.requires_code) {
    codeField.style.display = "flex";
    codeInput.placeholder = "required";
  } else {
    codeField.style.display = "none";
  }
  await loadServerSettings();
  await refreshFiles();
}

async function loadServerSettings() {
  try {
    const query = state.code ? `?code=${encodeURIComponent(state.code)}` : "";
    const res = await fetch(`/api/settings${query}`);
    if (!res.ok) return;
    const data = await res.json();
    saveDirLabel.textContent = data.save_dir || "Not set";
  } catch {}
}

function connect() {
  if (state.connected) {
    disconnect();
    return;
  }
  state.name = nameInput.value.trim() || "Guest";
  state.code = codeInput.value.trim();
  state.canReceive = receiveToggle.checked;
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${protocol}://${window.location.host}/ws`);

  state.ws.onopen = () => {
    state.ws.send(
      JSON.stringify({
        type: "hello",
        name: state.name,
        code: state.code,
        client_id: state.deviceId,
        can_receive: state.canReceive,
      })
    );
  };

  state.ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "welcome") {
      state.connected = true;
      state.sessionId = msg.session_id;
      state.deviceId = msg.client_id;
      state.isAdmin = Boolean(msg.is_admin);
      connectBtn.textContent = "Disconnect";
      setStatus(`Connected as ${msg.name}`, true);
      updateAdminUI();
      return;
    }
    if (msg.type === "error") {
      setStatus("Access denied. Check access code.");
      disconnect();
      return;
    }
    if (msg.type === "clients") {
      state.clients = msg.items || [];
      syncSelections();
      renderClients(state.clients);
      updateTargetLabels();
      return;
    }
    if (msg.type === "note") {
      appendNote(msg);
      return;
    }
    if (msg.type === "file") {
      refreshFiles();
      const from = msg.from ? ` from ${msg.from}` : "";
      uploadStatus.textContent = `New file${from}: ${msg.name}`;
      return;
    }
    if (msg.type === "settings") {
      saveDirLabel.textContent = msg.save_dir || saveDirLabel.textContent;
      if (msg.requires_code) {
        codeField.style.display = "flex";
      }
      return;
    }
  };

  state.ws.onclose = () => {
    disconnect();
  };
}

function disconnect() {
  if (state.ws) {
    state.ws.close();
  }
  state.ws = null;
  state.connected = false;
  state.sessionId = null;
  state.isAdmin = false;
  state.selectedSessions.clear();
  connectBtn.textContent = "Connect";
  setStatus("Disconnected");
  renderClients([]);
  updateTargetLabels();
  updateAdminUI();
}

async function refreshFiles() {
  const params = new URLSearchParams();
  if (state.code) params.set("code", state.code);
  if (state.deviceId) params.set("client_id", state.deviceId);
  const res = await fetch(`/api/files?${params.toString()}`);
  if (!res.ok) {
    fileListEl.innerHTML = '<div class="status muted">Access code required</div>';
    return;
  }
  const data = await res.json();
  renderFiles(data.files || []);
}

function renderFiles(files) {
  if (files.length === 0) {
    fileListEl.innerHTML = '<div class="status muted">No files yet</div>';
    return;
  }
  fileListEl.innerHTML = "";
  files.forEach((file) => {
    const item = document.createElement("div");
    item.className = "file-item";

    const name = document.createElement("div");
    const link = document.createElement("a");
    const params = new URLSearchParams();
    if (state.code) params.set("code", state.code);
    if (state.deviceId) params.set("client_id", state.deviceId);
    link.href = `/api/files/${encodeURIComponent(file.name)}?${params.toString()}`;
    link.textContent = file.name;
    name.appendChild(link);

    const meta = document.createElement("div");
    meta.textContent = formatBytes(file.size);

    const actions = document.createElement("div");
    actions.className = "file-actions";
    actions.appendChild(meta);

    if (state.isAdmin) {
      const removeBtn = document.createElement("button");
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", () => removeFile(file.name));
      actions.appendChild(removeBtn);
    }

    item.appendChild(name);
    item.appendChild(actions);

    // Private badge removed from UI

    fileListEl.appendChild(item);
  });
}

function renderClients(clients) {
  if (!state.connected) {
    clientListEl.innerHTML = '<div class="client-item disabled">Connect to see clients</div>';
    clientHint.textContent = "Connect to select recipients. Gray = send-only.";
    return;
  }
  if (!clients.length) {
    clientListEl.innerHTML = '<div class="status muted">No clients connected</div>';
    clientHint.textContent = "Connect to select recipients. Gray = send-only.";
    return;
  }
  clientListEl.innerHTML = "";
  const canRemove = state.isAdmin;
  clientHint.textContent = "Click clients to target (multi-select). Gray = send-only.";
  clients.forEach((client) => {
    const item = document.createElement("div");
    item.className = "client-item";
    item.dataset.session = client.session_id;
    item.dataset.clientId = client.client_id;

    const isSelf = client.session_id === state.sessionId;

    if (!client.can_receive || isSelf) {
      item.classList.add("disabled");
    }
    if (state.selectedSessions.has(client.session_id)) {
      item.classList.add("selected");
    }

    const label = document.createElement("div");
    label.textContent = client.name + (client.can_receive ? "" : " (send-only)");

    const actions = document.createElement("div");
    actions.className = "client-actions";
    if (!isSelf && canRemove) {
      const kickBtn = document.createElement("button");
      kickBtn.textContent = "Remove";
      kickBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        kickClient(client.session_id);
      });
      actions.appendChild(kickBtn);
    }

    item.appendChild(label);
    if (actions.childNodes.length) item.appendChild(actions);

    item.addEventListener("click", () => toggleTarget(client));
    clientListEl.appendChild(item);
  });
}

function toggleTarget(client) {
  if (!client.can_receive) return;
  if (client.session_id === state.sessionId) return;
  if (state.selectedSessions.has(client.session_id)) {
    state.selectedSessions.delete(client.session_id);
  } else {
    state.selectedSessions.add(client.session_id);
  }
  renderClients(state.clients);
  updateTargetLabels();
}

function updateTargetLabels() {
  const eligible = state.clients.filter(
    (c) => c.can_receive && c.session_id !== state.sessionId
  );
  if (!state.connected) {
    uploadBtn.disabled = true;
    return;
  }
  uploadBtn.disabled = eligible.length === 0;
}

function appendNote(msg) {
  const item = document.createElement("div");
  item.className = "note-item";

  const bubble = document.createElement("div");
  bubble.className = "note-bubble";
  bubble.textContent = msg.text;

  if (msg.session_id === state.sessionId) {
    bubble.classList.add("me");
  }

  const meta = document.createElement("div");
  meta.className = "note-meta";
  meta.textContent = msg.from || "Anon";

  item.appendChild(bubble);
  item.appendChild(meta);
  notesEl.appendChild(item);
  notesEl.scrollTop = notesEl.scrollHeight;
  noteStatus.textContent = `Note from ${msg.from || "Anon"}`;
}

async function uploadSelected() {
  const eligible = state.clients.filter(
    (c) => c.can_receive && c.session_id !== state.sessionId
  );
  if (eligible.length === 0) {
    uploadStatus.textContent = "No receivers connected";
    return;
  }
  const file = fileInput.files[0];
  if (!file) {
    uploadStatus.textContent = "Choose a file first";
    return;
  }
  uploadFileName.textContent = `Sending: ${file.name}`;
  uploadSpeed.textContent = "";
  uploadBar.style.width = "0%";
  const form = new FormData();
  form.append("file", file);
  form.append("name", state.name || nameInput.value || "Guest");
  if (state.deviceId) form.append("client_id", state.deviceId);
  if (state.selectedSessions.size) {
    const targets = [...state.selectedSessions]
      .filter((sid) => state.clients.some((c) => c.session_id === sid))
      .map((sid) => state.clients.find((c) => c.session_id === sid)?.client_id)
      .filter(Boolean);
    if (targets.length) {
      form.append("target_ids", targets.join(","));
    }
  }
  if (state.code) form.append("code", state.code);
  uploadStatus.textContent = "Uploading...";

  const xhr = new XMLHttpRequest();
  const start = performance.now();
  let lastLoaded = 0;
  let lastTime = start;
  xhr.upload.onprogress = (event) => {
    if (!event.lengthComputable) return;
    const percent = Math.round((event.loaded / event.total) * 100);
    uploadBar.style.width = `${percent}%`;
    const now = performance.now();
    const deltaTime = (now - lastTime) / 1000;
    if (deltaTime >= 0.2) {
      const deltaBytes = event.loaded - lastLoaded;
      const speed = deltaBytes / Math.max(deltaTime, 0.001);
      uploadSpeed.textContent = `${(speed / (1024 * 1024)).toFixed(1)} MB/s`;
      lastLoaded = event.loaded;
      lastTime = now;
    }
  };
  xhr.onload = () => {
    if (xhr.status >= 200 && xhr.status < 300) {
      const data = JSON.parse(xhr.responseText || "{}");
      uploadStatus.textContent = `Uploaded ${data.name}`;
      uploadBar.style.width = "100%";
      fileInput.value = "";
      refreshFiles();
    } else {
      let msg = "Upload failed";
      try {
        const err = JSON.parse(xhr.responseText || "{}");
        msg = err.detail || msg;
      } catch {}
      uploadStatus.textContent = msg;
    }
  };
  xhr.onerror = () => {
    uploadStatus.textContent = "Upload failed";
  };
  xhr.open("POST", "/api/upload", true);
  xhr.send(form);
}

function sendNote() {
  const text = noteInput.value.trim();
  if (!text) {
    noteStatus.textContent = "Note is empty";
    return;
  }
  if (!state.ws || !state.connected) {
    noteStatus.textContent = "Connect first to send notes";
    return;
  }
  const targets = [...state.selectedSessions].filter((id) =>
    state.clients.some((c) => c.session_id === id)
  );
  appendNote({
    text,
    from: state.name || "Me",
    session_id: state.sessionId,
  });
  state.ws.send(JSON.stringify({ type: "note", text, to: targets }));
  noteInput.value = "";
  noteStatus.textContent = "Note sent";
}

async function kickClient(sessionId) {
  if (!state.ws || !state.connected) return;
  state.ws.send(JSON.stringify({ type: "kick", target: sessionId, code: state.code }));
}

async function chooseFolder() {
  const headers = {};
  if (state.code) headers["x-filedrop-code"] = state.code;
  if (state.deviceId) headers["x-filedrop-client"] = state.deviceId;
  try {
    const res = await fetch("/api/settings/save-dialog", { method: "POST", headers });
    if (!res.ok) {
      const err = await res.json();
      uploadStatus.textContent = err.detail || "Folder picker failed";
      return;
    }
    const data = await res.json();
    saveDirLabel.textContent = data.save_dir;
  } catch (e) {
    uploadStatus.textContent = "Folder picker not available";
  }
}

function sendReceiveMode() {
  if (!state.ws || !state.connected) return;
  state.canReceive = receiveToggle.checked;
  state.ws.send(JSON.stringify({ type: "mode", can_receive: state.canReceive }));
}

function updatePanels() {
  const isNarrow = window.matchMedia("(max-width: 900px)").matches;
  PANEL_KEYS.forEach((key) => {
    const panel = document.querySelector(`[data-section="${key}"]`) || document.querySelector(`[data-panel="${key}"]`);
    if (!panel) return;
    panel.style.display = state.hidden.has(key) ? "none" : "flex";
    if (!state.hidden.has(key)) {
      const span = isNarrow ? 1 : (PANEL_SIZES[key] || 1);
      panel.style.gridColumn = span === 2 ? "span 2" : "span 1";
    }
  });
  const hero = document.querySelector(".hero");
  if (hero) {
    if (state.hidden.has("share")) {
      hero.classList.add("single");
    } else {
      hero.classList.remove("single");
    }
  }
  Array.from(document.querySelectorAll("[data-panel-toggle]"))
    .forEach((cb) => {
      const key = cb.dataset.panelToggle;
      cb.checked = !state.hidden.has(key);
    });
  const hiddenCount = state.hidden.size;
  panelMenuBtn.textContent = hiddenCount ? `Panels (${hiddenCount} hidden) ▾` : "Panels ▾";
}

function togglePanelFromMenu(key, visible) {
  if (visible) state.hidden.delete(key);
  else state.hidden.add(key);
  updatePanels();
}

async function removeFile(name) {
  const params = new URLSearchParams();
  if (state.code) params.set("code", state.code);
  if (state.deviceId) params.set("client_id", state.deviceId);
  const res = await fetch(`/api/files/${encodeURIComponent(name)}?${params.toString()}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    uploadStatus.textContent = err.detail || "Remove failed";
    return;
  }
  refreshFiles();
}

copyBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(shareUrlEl.value);
  copyBtn.textContent = "Copied";
  setTimeout(() => {
    copyBtn.textContent = "Copy";
  }, 1200);
});

connectBtn.addEventListener("click", connect);
uploadBtn.addEventListener("click", uploadSelected);
sendNoteBtn.addEventListener("click", sendNote);
receiveToggle.addEventListener("change", sendReceiveMode);
chooseDirBtn.addEventListener("click", chooseFolder);

codeInput.addEventListener("input", () => {
  state.code = codeInput.value.trim();
  refreshFiles();
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  uploadFileName.textContent = file ? `Ready: ${file.name}` : "No file selected";
  uploadSpeed.textContent = "";
  uploadBar.style.width = "0%";
});

themeSelect.addEventListener("change", () => {
  applyTheme(themeSelect.value);
});

panelMenuBtn.addEventListener("click", () => {
  panelMenu.classList.toggle("open");
});

Array.from(document.querySelectorAll("[data-panel-toggle]"))
  .forEach((cb) => {
    cb.addEventListener("change", () => {
      togglePanelFromMenu(cb.dataset.panelToggle, cb.checked);
    });
  });

window.addEventListener("click", (e) => {
  if (!panelMenu.contains(e.target) && e.target !== panelMenuBtn) {
    panelMenu.classList.remove("open");
  }
});

window.addEventListener("load", () => {
  state.deviceId = getDeviceId();
  const theme = sessionStorage.getItem("filedrop_theme") || "sand";
  themeSelect.value = theme;
  applyTheme(theme);
  updatePanels();
  loadInfo();
  renderClients([]);
  updateAdminUI();
});

window.addEventListener("resize", () => {
  updatePanels();
});

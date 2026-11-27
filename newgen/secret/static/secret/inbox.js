(() => {
  "use strict";

  const cfg = window.INBOX_CONFIG || {};
  const list = document.getElementById("thread-list");
  const badge = document.getElementById("unread-badge");
  const banner = document.getElementById("inbox-banner");

  const HEARTBEAT_MS = 45000;

  let socket = null;
  let heartbeat = null;
  let reconnectTimer = null;
  let attempts = 0;
  let refreshTimer = null;

  function setBanner(text) {
    if (!banner) return;
    banner.textContent = text || "";
    banner.hidden = !text;
  }

  function currentFilter() {
    return (list && list.dataset.filter) || cfg.filter || "all";
  }

  /* ---------------------------------------------------------------- render */

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[c]);
  }

  function threadNode(item) {
    const link = document.createElement("a");
    link.className = "thread" + (item.needs_attention ? " thread--urgent" : "");
    link.href = "/leader/chat/" + item.id + "/";
    link.dataset.conversationId = item.id;
    link.dataset.status = item.status;
    link.dataset.unread = String(item.unread || 0);
    link.dataset.urgent = item.needs_attention ? "1" : "0";
    link.dataset.search = (
      (item.alias || "") + " " + (item.last_message || "")
    ).toLowerCase();
    link.innerHTML =
      '<div class="avatar ' + escapeHtml(item.avatar_tone) + '">' +
        escapeHtml(item.initials) +
      "</div>" +
      '<div class="thread__body">' +
        '<div class="thread__top">' +
          '<span class="thread__alias">' + escapeHtml(item.alias) + "</span>" +
          '<span class="thread__time">' + escapeHtml(item.time_label || "New") + "</span>" +
        "</div>" +
        '<div class="thread__preview">' +
          escapeHtml(item.last_message || "New anonymous conversation") +
        "</div>" +
        '<div class="thread__meta">' +
          (item.unread
            ? '<span class="badge-count">' + item.unread + "</span>"
            : "") +
          (item.needs_attention
            ? '<span class="urgent-tag">Needs attention</span>'
            : "") +
          (item.status === "resolved"
            ? '<span class="urgent-tag resolved-tag">Resolved</span>'
            : "") +
        "</div>" +
      "</div>" +
      '<div class="thread__tail">' +
        '<span class="tick-icon tick-icon--muted">' +
          (item.status === "resolved" ? "\u2713\u2713" : "\u203a") +
        "</span>" +
      "</div>";
    return link;
  }

  function render(data) {
    if (list && Array.isArray(data.items)) {
      const fragment = document.createDocumentFragment();
      data.items.forEach((item) => fragment.appendChild(threadNode(item)));
      list.replaceChildren(fragment);
      if (!data.items.length) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.innerHTML =
          '<h3>No conversations here yet</h3>' +
          "<p>When an anonymous person chooses you, their message will appear here.</p>";
        list.appendChild(empty);
      }
      // Rows were rebuilt, so re-run ui.js's filter if a search is active.
      const searchInput = document.getElementById("inbox-search-input");
      if (searchInput && searchInput.value.trim()) {
        searchInput.dispatchEvent(new Event("input"));
      }
    }
    if (badge) {
      badge.textContent = data.unread_total || 0;
      badge.hidden = !data.unread_total;
    }
  }

  /* ----------------------------------------------------------------- fetch */

  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, 400);
  }

  function refresh() {
    if (!cfg.dataUrl) return;
    const url = cfg.dataUrl + "?filter=" + encodeURIComponent(currentFilter());
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((response) => {
        if (!response.ok) throw new Error("inbox " + response.status);
        return response.json();
      })
      .then((data) => {
        render(data);
        setBanner("");
      })
      .catch(() => setBanner("Could not refresh the inbox. Retrying…"));
  }

  /* --------------------------------------------------------------- socket  */

  function connect() {
    clearTimeout(reconnectTimer);
    if (!cfg.wsUrl) return;
    try {
      socket = new WebSocket(cfg.wsUrl);
    } catch (error) {
      scheduleReconnect();
      return;
    }

    socket.addEventListener("open", () => {
      attempts = 0;
      setBanner("");
      clearInterval(heartbeat);
      // Refreshing the presence key keeps "online now" honest while the socket
      // is open; it expires on its own if this tab disappears.
      heartbeat = setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        }
      }, HEARTBEAT_MS);
    });

    socket.addEventListener("message", (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (data.type === "inbox_update" || data.type === "conversation_event") {
        scheduleRefresh();
      }
    });

    socket.addEventListener("close", () => {
      socket = null;
      clearInterval(heartbeat);
      scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      if (socket) socket.close();
    });
  }

  function scheduleReconnect() {
    attempts += 1;
    const delay = Math.min(1000 * Math.pow(1.6, attempts), 15000);
    reconnectTimer = setTimeout(connect, delay);
  }

  /* ------------------------------------------------------------------ boot */

  connect();
})();

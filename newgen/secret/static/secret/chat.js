(() => {
  "use strict";

  const configEl = document.getElementById("chat-config");
  if (!configEl) return;
  const cfg = JSON.parse(configEl.textContent);

  const list = document.getElementById("message-list");
  const input = document.getElementById("message-input");
  const composer = document.getElementById("composer");
  const sendBtn = document.getElementById("send-btn");
  const loadOlderBtn = document.getElementById("load-older");
  const jumpBtn = document.getElementById("jump-latest");
  const typingRow = document.getElementById("typing-row");
  const typingLabel = document.getElementById("typing-label");
  const connectionBanner = document.getElementById("connection-banner");
  const menuToggle = document.getElementById("menu-toggle");
  const sheet = document.getElementById(cfg.isLeaderView ? "leader-menu" : "anon-menu");
  const noteToggle = document.getElementById("note-toggle");
  const leaveForm = document.getElementById("leave-form");

  const state = {
    socket: null,
    reconnectAttempts: 0,
    reconnectTimer: null,
    pollingTimer: null,
    lastAt: cfg.initialLastAt || "",
    oldestAt: cfg.oldestCreatedAt || "",
    hasMore: !!cfg.hasMore,
    lastDate: "",
    pending: new Map(),
    typingActive: false,
    typingTimer: null,
    remoteTypingTimer: null,
    presenceTimer: null,
    noteMode: false,
    loadingOlder: false,
    canSend: !!cfg.canSend,
  };

  // ---------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------
  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      credentials: "same-origin",
      body: JSON.stringify(payload || {}),
    });
    let data = {};
    try {
      data = await response.json();
    } catch (err) {
      data = {};
    }
    if (!response.ok) {
      throw new Error(data.error || "Something went wrong.");
    }
    return data;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(String(value));
    return String(value).replace(/[\\"]/g, "\\$&");
  }

  function findById(id) {
    return list.querySelector(`[data-message-id="${cssEscape(id)}"]`);
  }

  function findByClientId(clientId) {
    return list.querySelector(`[data-client-id="${cssEscape(clientId)}"]`);
  }

  function dateKeyFromIso(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function timeLabel(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return (
      String(d.getHours()).padStart(2, "0") +
      ":" +
      String(d.getMinutes()).padStart(2, "0")
    );
  }

  function toast(text) {
    if (!text) return;
    let node = document.querySelector(".toast");
    if (!node) {
      node = document.createElement("div");
      node.className = "toast";
      node.setAttribute("role", "status");
      document.body.appendChild(node);
    }
    node.textContent = text;
    node.classList.add("is-visible");
    clearTimeout(node._hideTimer);
    node._hideTimer = setTimeout(() => node.classList.remove("is-visible"), 2600);
  }

  function humanDay(dateStr) {
    if (!dateStr) return "";
    const today = new Date();
    const todayKey = dateKeyFromIso(today.toISOString());
    const yesterday = new Date(today.getTime() - 86400000);
    const yesterdayKey = dateKeyFromIso(yesterday.toISOString());
    if (dateStr === todayKey) return "Today";
    if (dateStr === yesterdayKey) return "Yesterday";
    const d = new Date(dateStr + "T12:00:00");
    if (Number.isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }

  function randomId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, "");
    return "c" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  function nearBottom() {
    return list.scrollHeight - list.scrollTop - list.clientHeight < 140;
  }

  function scrollToBottom() {
    list.scrollTop = list.scrollHeight;
  }

  function updateJumpButton() {
    if (!jumpBtn) return;
    jumpBtn.hidden = nearBottom();
  }

  // ---------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------
  function isMine(message) {
    return message.is_mine === true || message.sender_type === cfg.role;
  }

  function tickSvg(message) {
    const stroke =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
    if (message.is_read || message.delivered) {
      return (
        stroke +
        '<path d="M18 6 7 17l-5-5"/><path d="m22 10-7.5 7.5L13 16"/></svg>'
      );
    }
    return stroke + '<path d="M20 6 9 17l-5-5"/></svg>';
  }

  function tickClass(message) {
    if (message.is_read) return "read";
    if (message.delivered) return "delivered";
    return "sent";
  }

  function renderMessage(message, options) {
    const opts = options || {};
    const mine = isMine(message);

    if (message.is_system) {
      const row = el("div", "system-row");
      row.dataset.messageId = message.id || "";
      row.dataset.created = message.created_at || "";
      row.dataset.date = message.date || dateKeyFromIso(message.created_at);
      row.appendChild(el("span", "system-note", message.body));
      return row;
    }

    const row = el(
      "div",
      "msg-row " +
        (mine ? "msg-row--mine" : "msg-row--theirs") +
        (message.is_internal ? " msg-row--note" : "") +
        (opts.pending ? " msg-row--pending" : "") +
        (opts.failed ? " msg-row--failed" : "")
    );
    row.dataset.messageId = message.id || "";
    row.dataset.created = message.created_at || "";
    row.dataset.date = message.date || dateKeyFromIso(message.created_at);
    row.dataset.sender = message.sender_type || "";
    row.dataset.clientId = message.client_id || "";

    if (message.is_internal) {
      const author = el(
        "div",
        "msg-author msg-author--note",
        "Private note · " + (message.sender_name || cfg.leaderName || "You")
      );
      row.appendChild(author);
    } else if (cfg.isLeaderView && message.sender_type === "anon") {
      row.appendChild(el("div", "msg-author", message.sender_name || cfg.alias));
    } else if (!cfg.isLeaderView && message.sender_type === "leader") {
      const author = el("div", "msg-author");
      if (message.role_label) {
        author.appendChild(
          el(
            "span",
            "role-badge role-badge--" + (message.sender_type === "leader" ? "leader" : "counsellor"),
            message.role_label
          )
        );
      }
      author.appendChild(document.createTextNode(message.sender_name || "Support team"));
      row.appendChild(author);
    }

    const bubble = el(
      "div",
      "bubble " + (mine ? "bubble--out" : "bubble--in") + (message.is_internal ? " bubble--note" : "")
    );
    const body = el("div", "bubble__body", message.body || "");
    bubble.appendChild(body);

    const meta = el("div", "bubble__meta");
    meta.appendChild(el("span", "msg-time", message.time_label || timeLabel(message.created_at)));
    if (message.is_internal) {
      meta.appendChild(el("span", "note-tag", "Only leaders can see this"));
    } else if (mine) {
      const ticks = el("span", "ticks ticks--" + tickClass(message));
      ticks.innerHTML = tickSvg(message);
      ticks.dataset.ticks = message.id || "";
      meta.appendChild(ticks);
    }
    bubble.appendChild(meta);
    row.appendChild(bubble);

    if (opts.failed) {
      const retry = el("button", "retry-btn", "Tap to retry");
      retry.type = "button";
      retry.addEventListener("click", () => retryMessage(message.client_id));
      row.appendChild(retry);
    }
    return row;
  }

  function ensureDateSeparator(date, beforeNode) {
    if (!date || date === state.lastDate) return;
    const sep = el("div", "date-sep");
    sep.dataset.date = date;
    sep.appendChild(el("span", "", humanDay(date)));
    list.insertBefore(sep, beforeNode || typingRow);
    state.lastDate = date;
  }

  function appendMessage(message, options) {
    const opts = options || {};
    if (!message) return null;
    if (message.id && findById(message.id)) return findById(message.id);
    if (message.client_id && findByClientId(message.client_id)) {
      return replacePending(message.client_id, message);
    }

    const shouldScroll = opts.scroll !== false && (nearBottom() || isMine(message));
    const date = message.date || dateKeyFromIso(message.created_at);
    if (opts.withSeparator !== false) {
      ensureDateSeparator(date, typingRow);
    }
    const row = renderMessage(message, opts);
    list.insertBefore(row, typingRow);
    if (message.created_at) state.lastAt = message.created_at;
    if (!state.oldestAt && message.created_at) state.oldestAt = message.created_at;
    if (shouldScroll) scrollToBottom();
    updateJumpButton();
    return row;
  }

  function replacePending(clientId, message) {
    const pending = state.pending.get(clientId);
    if (pending && pending.timer) clearTimeout(pending.timer);
    const old = findByClientId(clientId);
    const row = renderMessage(message, {});
    if (old) {
      old.replaceWith(row);
    } else {
      appendMessage(message, { scroll: true });
    }
    state.pending.delete(clientId);
    if (message.created_at) state.lastAt = message.created_at;
    if (nearBottom()) scrollToBottom();
    updateJumpButton();
    return row;
  }

  function markTicks(ids, status) {
    (ids || []).forEach((id) => {
      const ticks = list.querySelector(`[data-ticks="${cssEscape(id)}"]`);
      if (!ticks) return;
      if (status === "read" || ticks.classList.contains("ticks--read")) {
        ticks.innerHTML = tickSvg({ is_read: true });
        ticks.classList.remove("ticks--sent", "ticks--delivered");
        ticks.classList.add("ticks--read");
      } else if (status === "delivered") {
        ticks.innerHTML = tickSvg({ delivered: true });
        ticks.classList.remove("ticks--sent");
        ticks.classList.add("ticks--delivered");
      }
    });
  }

  // ---------------------------------------------------------------------
  // Sending
  // ---------------------------------------------------------------------
  function autoGrow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 132) + "px";
  }

  function socketOpen() {
    return state.socket && state.socket.readyState === WebSocket.OPEN;
  }

  function sendTyping(isTyping) {
    if (!state.canSend) return;
    if (socketOpen()) {
      state.socket.send(JSON.stringify({ type: "typing", is_typing: isTyping }));
    } else if (cfg.typingUrl) {
      postJson(cfg.typingUrl, { is_typing: isTyping }).catch(() => {});
    }
  }

  function sendRead() {
    if (!state.canSend) return;
    if (socketOpen()) {
      state.socket.send(JSON.stringify({ type: "read" }));
    } else if (cfg.readUrl) {
      postJson(cfg.readUrl, {}).catch(() => {});
    }
  }

  function sendMessage() {
    const body = input.value.trim();
    if (!body || !state.canSend) return;

    if (state.noteMode && cfg.noteUrl) {
      sendNote(body);
      return;
    }

    const clientId = randomId();
    const now = new Date().toISOString();
    const optimistic = {
      id: "temp-" + clientId,
      client_id: clientId,
      body: body,
      sender_type: cfg.role,
      sender_name: "You",
      role_label: cfg.myRoleLabel,
      is_mine: true,
      is_system: false,
      is_internal: false,
      is_read: false,
      delivered: false,
      created_at: now,
      date: dateKeyFromIso(now),
      time_label: timeLabel(now),
    };
    const row = appendMessage(optimistic, { pending: true, scroll: true });
    state.pending.set(clientId, { body: body, row: row, timer: null });

    input.value = "";
    autoGrow();
    stopTyping();

    if (socketOpen()) {
      state.socket.send(
        JSON.stringify({ type: "message", message: body, client_id: clientId })
      );
      const pending = state.pending.get(clientId);
      if (pending) {
        pending.timer = setTimeout(() => markFailed(clientId), 12000);
      }
    } else {
      sendViaHttp(clientId, body);
    }
  }

  async function sendViaHttp(clientId, body) {
    try {
      const data = await postJson(cfg.sendUrl, {
        body: body,
        client_id: clientId,
      });
      if (data.message) replacePending(clientId, data.message);
      if (data.safety) showSafety(data.safety);
      if (data.conversation && data.conversation.needs_attention) {
        if (cfg.isLeaderView) showAttention(data.conversation.attention_reason);
      }
    } catch (err) {
      markFailed(clientId, err.message);
    }
  }

  function markFailed(clientId) {
    const pending = state.pending.get(clientId);
    if (!pending) return;
    if (pending.timer) clearTimeout(pending.timer);
    const row = findByClientId(clientId);
    if (!row) return;
    row.classList.add("msg-row--failed");
    if (!row.querySelector(".retry-btn")) {
      const retry = el("button", "retry-btn", "Tap to retry");
      retry.type = "button";
      retry.addEventListener("click", () => retryMessage(clientId));
      row.appendChild(retry);
    }
  }

  function retryMessage(clientId) {
    const pending = state.pending.get(clientId);
    if (!pending) return;
    const row = findByClientId(clientId);
    if (row) {
      row.classList.remove("msg-row--failed");
      const btn = row.querySelector(".retry-btn");
      if (btn) btn.remove();
    }
    if (socketOpen()) {
      state.socket.send(
        JSON.stringify({
          type: "message",
          message: pending.body,
          client_id: clientId,
        })
      );
      pending.timer = setTimeout(() => markFailed(clientId), 12000);
    } else {
      sendViaHttp(clientId, pending.body);
    }
  }

  async function sendNote(body) {
    try {
      const data = await postJson(cfg.noteUrl, {
        body: body,
        client_id: randomId(),
      });
      if (data.message) appendMessage(data.message, { scroll: true });
      input.value = "";
      autoGrow();
    } catch (err) {
      alert(err.message);
    }
  }

  function stopTyping() {
    if (!state.typingActive) return;
    state.typingActive = false;
    clearTimeout(state.typingTimer);
    sendTyping(false);
  }

  // ---------------------------------------------------------------------
  // Incoming
  // ---------------------------------------------------------------------
  function handleIncoming(message) {
    if (!message) return;
    if (message.id && findById(message.id)) {
      updateTicksFromMessage(message);
      return;
    }
    if (message.client_id && findByClientId(message.client_id)) {
      replacePending(message.client_id, message);
      return;
    }
    appendMessage(message, { scroll: true });
    if (!isMine(message) && document.visibilityState === "visible" && nearBottom()) {
      sendRead();
    }
    if (message.is_internal) return;
  }

  function updateTicksFromMessage(message) {
    if (!isMine(message)) return;
    const ticks = list.querySelector(`[data-ticks="${cssEscape(message.id)}"]`);
    if (!ticks) return;
    ticks.innerHTML = tickSvg(message);
    ticks.className = "ticks ticks--" + tickClass(message);
  }

  function showTyping(label) {
    if (!typingRow) return;
    if (typingLabel) typingLabel.textContent = label;
    typingRow.hidden = false;
    clearTimeout(state.remoteTypingTimer);
    state.remoteTypingTimer = setTimeout(() => {
      typingRow.hidden = true;
    }, 6000);
    if (nearBottom()) scrollToBottom();
  }

  function hideTyping() {
    if (typingRow) typingRow.hidden = true;
    clearTimeout(state.remoteTypingTimer);
  }

  function showAttention(reason) {
    let banner = document.getElementById("attention-banner");
    if (!banner) {
      banner = el("div", "attention-banner");
      banner.id = "attention-banner";
      const title = el("strong", "", "Needs urgent attention");
      const text = el("span", "", reason || "Safety concern detected");
      text.id = "attention-reason";
      banner.appendChild(title);
      banner.appendChild(text);
      const header = document.querySelector(".chat-header");
      header.insertAdjacentElement("afterend", banner);
    } else {
      const text = document.getElementById("attention-reason");
      if (text) text.textContent = reason || "Safety concern detected";
    }
  }

  function showSafety(payload) {
    if (!payload) return;
    let banner = document.getElementById("safety-banner");
    if (!banner) {
      banner = el("div", "safety-banner");
      banner.id = "safety-banner";
      const header = document.querySelector(".chat-header");
      header.insertAdjacentElement("afterend", banner);
    }
    banner.textContent = "";
    banner.appendChild(el("strong", "", "You are not alone."));
    banner.appendChild(el("p", "", payload.note || ""));
    const links = el("div", "helplines");
    (payload.numbers || []).forEach((h) => {
      const a = document.createElement("a");
      a.href = "tel:" + (h.tel || h.number);
      a.textContent = h.label + ": " + h.number;
      links.appendChild(a);
    });
    banner.appendChild(links);
  }

  function handleEvent(data) {
    const event = data.event;
    const payload = data.payload || {};
    if (event === "typing") {
      const fromLeader = !!payload.is_leader;
      const fromMe = fromLeader === (cfg.role === "leader");
      if (fromMe) return;
      if (payload.is_typing) {
        const label = cfg.isLeaderView ? cfg.alias + " is typing…" : cfg.leaderName + " is typing…";
        showTyping(label);
      } else {
        hideTyping();
      }
    } else if (event === "read_receipt") {
      markTicks(payload.message_ids, "read");
    } else if (event === "delivered_receipt") {
      markTicks(payload.message_ids, "delivered");
    } else if (event === "attention") {
      if (cfg.isLeaderView) showAttention(payload.reason);
    } else if (event === "safety_alert") {
      if (!cfg.isLeaderView) showSafety(payload);
    } else if (event === "presence") {
      // Show peer online/offline status
      const who = payload.who;
      const online = payload.online;
      setPeerPresence(online);
    }
  }

  // ---------------------------------------------------------------------
  // WebSocket + polling fallback
  // ---------------------------------------------------------------------
  function showConnection(isDown) {
    if (connectionBanner) connectionBanner.hidden = !isDown;
  }

  function connectSocket() {
    clearTimeout(state.reconnectTimer);
    try {
      state.socket = new WebSocket(cfg.wsUrl);
    } catch (err) {
      showConnection(true);
      startPolling();
      scheduleReconnect();
      return;
    }

    state.socket.addEventListener("open", () => {
      state.reconnectAttempts = 0;
      showConnection(false);
      stopPolling();
      sendRead();
      clearInterval(state.presenceTimer);
    });

    state.socket.addEventListener("message", (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (data.type === "message") {
        handleIncoming(data.message);
      } else if (data.type === "message_ack") {
        if (data.message) replacePending(data.client_id, data.message);
      } else if (data.type === "event") {
        handleEvent(data);
      } else if (data.type === "error") {
        if (data.error) console.warn(data.error);
      }
    });

    state.socket.addEventListener("close", () => {
      state.socket = null;
      showConnection(true);
      clearInterval(state.presenceTimer);
      startPolling();
      scheduleReconnect();
    });

    state.socket.addEventListener("error", () => {
      if (state.socket) state.socket.close();
    });
  }

  function scheduleReconnect() {
    state.reconnectAttempts += 1;
    const delay = Math.min(1000 * Math.pow(1.6, state.reconnectAttempts), 15000);
    state.reconnectTimer = setTimeout(connectSocket, delay);
  }

  function startPolling() {
    if (state.pollingTimer) return;
    state.pollingTimer = setInterval(pollMessages, 4000);
    pollMessages();
  }

  function stopPolling() {
    if (state.pollingTimer) {
      clearInterval(state.pollingTimer);
      state.pollingTimer = null;
    }
  }

  async function pollMessages() {
    if (socketOpen()) return;
    try {
      const url = cfg.messagesUrl + (state.lastAt ? "?after=" + encodeURIComponent(state.lastAt) : "");
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();
      (data.messages || []).forEach((message) => handleIncoming(message));
      if (data.typing) {
        const remoteTyping = cfg.isLeaderView ? data.typing.anon : data.typing.leader;
        if (remoteTyping) {
          const label = cfg.isLeaderView ? cfg.alias + " is typing…" : cfg.leaderName + " is typing…";
          showTyping(label);
        }
      }
      if (data.blocked || data.room_enabled === false) {
        state.canSend = false;
        input.disabled = true;
        sendBtn.disabled = true;
      }
      if (data.helplines && !cfg.isLeaderView) {
        showSafety(data.helplines);
      }
      if (data.conversation && data.conversation.needs_attention && cfg.isLeaderView) {
        showAttention(data.conversation.attention_reason);
      }
      // Presence ping reply
      if (data.presence !== undefined) {
        setPeerPresence(data.presence);
      }
    } catch (err) {
      showConnection(true);
    }
  }

  function setPeerPresence(online) {
    const dot = document.getElementById("peer-presence");
    const label = document.getElementById("presence-label");
    if (dot) dot.classList.toggle("presence-dot--off", !online);
    if (label) label.textContent = online ? "Online" : "Offline";
  }

  // ---------------------------------------------------------------------
  // Older messages
  // ---------------------------------------------------------------------
  async function loadOlder() {
    if (!state.hasMore || state.loadingOlder || !state.oldestAt) return;
    state.loadingOlder = true;
    if (loadOlderBtn) loadOlderBtn.textContent = "Loading…";
    try {
      const url = cfg.messagesUrl + "?before=" + encodeURIComponent(state.oldestAt);
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();
      const messages = data.messages || [];
      if (messages.length) {
        const prevHeight = list.scrollHeight;
        const prevTop = list.scrollTop;
        const firstExisting = list.querySelector(".msg-row, .system-row");
        const firstExistingDate = firstExisting ? firstExisting.dataset.date : "";
        const fragment = document.createDocumentFragment();
        let localDate = "";
        messages.forEach((message, index) => {
          const date = message.date || dateKeyFromIso(message.created_at);
          if (date !== localDate) {
            if (!(index === 0 && date === firstExistingDate)) {
              const sep = el("div", "date-sep");
              sep.dataset.date = date;
              sep.appendChild(el("span", "", humanDay(date)));
              fragment.appendChild(sep);
            }
            localDate = date;
          }
          fragment.appendChild(renderMessage(message, {}));
        });
        list.insertBefore(fragment, loadOlderBtn ? loadOlderBtn.nextSibling : list.firstChild);
        state.oldestAt = data.oldest_created_at || messages[0].created_at || state.oldestAt;
        state.hasMore = !!data.has_more;
        if (loadOlderBtn) loadOlderBtn.hidden = !state.hasMore;
        list.scrollTop = prevTop + (list.scrollHeight - prevHeight);
      } else {
        state.hasMore = false;
        if (loadOlderBtn) loadOlderBtn.hidden = true;
      }
    } catch (err) {
      // Keep the button so the person can try again.
    } finally {
      state.loadingOlder = false;
      if (loadOlderBtn) loadOlderBtn.textContent = "Load older messages";
    }
  }

  // ---------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------
  if (input) {
    input.addEventListener("input", () => {
      autoGrow();
      if (!state.typingActive) {
        state.typingActive = true;
        sendTyping(true);
      }
      clearTimeout(state.typingTimer);
      state.typingTimer = setTimeout(stopTyping, 1600);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendMessage();
      }
    });
  }

  if (composer) {
    composer.addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage();
    });
  }

  if (sendBtn) {
    sendBtn.addEventListener("click", (event) => {
      if (event) event.preventDefault();
      sendMessage();
    });
  }

  if (jumpBtn) {
    jumpBtn.addEventListener("click", () => {
      scrollToBottom();
      jumpBtn.hidden = true;
      if (document.visibilityState === "visible") sendRead();
    });
  }

  if (loadOlderBtn) {
    loadOlderBtn.addEventListener("click", loadOlder);
  }

  list.addEventListener("scroll", () => {
    updateJumpButton();
    if (list.scrollTop < 90 && state.hasMore && !state.loadingOlder) {
      loadOlder();
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      sendRead();
      if (!socketOpen()) pollMessages();
    }
  });

  if (menuToggle && sheet) {
    menuToggle.addEventListener("click", () => {
      sheet.hidden = false;
    });
    sheet.addEventListener("click", (event) => {
      if (event.target === sheet || event.target.hasAttribute("data-close-sheet")) {
        sheet.hidden = true;
      }
    });
  }

  if (noteToggle) {
    noteToggle.addEventListener("click", () => {
      state.noteMode = !state.noteMode;
      noteToggle.classList.toggle("composer__note--active", state.noteMode);
      noteToggle.textContent = state.noteMode ? "Note on" : "Note";
      input.placeholder = state.noteMode
        ? "Private note for leaders only…"
        : "Reply as " + (cfg.myRoleLabel || "leader").toLowerCase() + "…";
      input.focus();
    });
  }

  document.querySelectorAll("[data-quick-reply]").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.getAttribute("data-quick-reply") || "";
      autoGrow();
      input.focus();
    });
  });

  if (leaveForm) {
    leaveForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!window.confirm("Delete this conversation and all its messages? This cannot be undone.")) return;
      try {
        await postJson(cfg.leaveUrl, {});
        const back = document.querySelector(".chat-header a");
        window.location.href = back ? back.href : "/";
      } catch (err) {
        alert(err.message);
      }
    });
  }

  // Initial state
  const lastRow = list.querySelector(".msg-row, .system-row:last-of-type");
  const allRows = list.querySelectorAll(".msg-row, .system-row");
  if (allRows.length) {
    const last = allRows[allRows.length - 1];
    state.lastDate = last.dataset.date || "";
    if (last.dataset.created) state.lastAt = last.dataset.created;
    if (!state.oldestAt) state.oldestAt = allRows[0].dataset.created || "";
  }
  if (loadOlderBtn) loadOlderBtn.hidden = !state.hasMore;
  requestAnimationFrame(() => {
    scrollToBottom();
    updateJumpButton();
  });

  connectSocket();
})();
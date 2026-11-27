/* Shared UI behaviour: search filters, sheets, clipboard, password reveal.
   Loaded by every page that renders interactive chrome. */
(() => {
  "use strict";

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  let toastTimer = null;

  function toast(message) {
    if (!message) return;
    let node = $(".toast");
    if (!node) {
      node = document.createElement("div");
      node.className = "toast";
      node.setAttribute("role", "status");
      document.body.appendChild(node);
    }
    node.textContent = message;
    node.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove("is-visible"), 2400);
  }

  // -------------------------------------------------------------------------
  // Search filters — any input with data-filter-target filters its container.
  // -------------------------------------------------------------------------
  function filterRows(input) {
    const target = document.getElementById(input.getAttribute("data-filter-target"));
    if (!target) return;
    const query = input.value.trim().toLowerCase();
    let visible = 0;
    $$("[data-search]", target).forEach((row) => {
      const haystack = (row.getAttribute("data-search") || "").toLowerCase();
      const match = !query || haystack.indexOf(query) !== -1;
      row.hidden = !match;
      if (match) visible += 1;
    });
    const empty = $("[data-empty]", target);
    if (empty) empty.hidden = visible !== 0;
  }

  $$("[data-filter-target]").forEach((input) => {
    ["input", "search"].forEach((eventName) => {
      input.addEventListener(eventName, () => filterRows(input));
    });
  });

  // The leader inbox hides its search field behind an icon.
  const searchToggle = $("#inbox-search-toggle");
  const inboxSearch = $("#inbox-search");
  const inboxSearchInput = $("#inbox-search-input");
  if (searchToggle && inboxSearch && inboxSearchInput) {
    searchToggle.addEventListener("click", () => {
      inboxSearch.hidden = !inboxSearch.hidden;
      if (!inboxSearch.hidden) {
        inboxSearchInput.focus();
      } else {
        inboxSearchInput.value = "";
        filterRows(inboxSearchInput);
      }
    });
  }

  // -------------------------------------------------------------------------
  // Bottom sheets
  // -------------------------------------------------------------------------
  function openSheet(sheet) {
    if (!sheet) return;
    sheet.hidden = false;
    document.body.classList.add("sheet-open");
  }

  function closeSheets() {
    $$(".sheet").forEach((sheet) => {
      sheet.hidden = true;
    });
    document.body.classList.remove("sheet-open");
  }

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (target.closest("[data-open-share]")) {
      openSheet($("#share-sheet"));
      return;
    }
    if (target.closest("[data-close-sheet]")) {
      closeSheets();
      return;
    }
    if (target.classList && target.classList.contains("sheet")) {
      closeSheets();
    }
  });

  const shareToggle = $("#share-room-toggle");
  if (shareToggle) {
    shareToggle.addEventListener("click", () => openSheet($("#share-sheet")));
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSheets();
  });

  // -------------------------------------------------------------------------
  // Clipboard
  // -------------------------------------------------------------------------
  function legacyCopy(text, done) {
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    try {
      document.execCommand("copy");
      done();
    } catch (err) {
      toast("Copy failed — select the text manually.");
    } finally {
      document.body.removeChild(field);
    }
  }

  function copyText(text, label) {
    if (!text) return;
    const done = () => toast((label || "Text") + " copied");
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done).catch(() => legacyCopy(text, done));
    } else {
      legacyCopy(text, done);
    }
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-copy-target]");
    if (!trigger) return;
    const source = document.getElementById(trigger.getAttribute("data-copy-target"));
    if (source) copyText(source.textContent.trim(), trigger.getAttribute("data-copy-label") || "Room code");
  });

  const copyCode = $("#copy-code");
  if (copyCode) {
    copyCode.addEventListener("click", () => {
      const code = $("#room-code");
      if (code) copyText(code.textContent.trim(), "Room code");
    });
  }

  const copyLink = $("#copy-link");
  if (copyLink) {
    copyLink.addEventListener("click", () => {
      const link = $("#share-url");
      if (link) copyText(link.textContent.trim(), "Invitation link");
    });
  }

  // -------------------------------------------------------------------------
  // Liquid-glass dock: a spring indicator that glides under the active tab.
  // -------------------------------------------------------------------------
  const dock = document.querySelector(".bottom-nav");
  if (dock) {
    const activeItem = dock.querySelector(".nav-item--active");
    if (activeItem) {
      const glide = document.createElement("span");
      glide.className = "nav-glide";
      glide.setAttribute("aria-hidden", "true");
      dock.insertBefore(glide, dock.firstChild);

      const placeGlide = () => {
        const dockBox = dock.getBoundingClientRect();
        const itemBox = activeItem.getBoundingClientRect();
        glide.style.width = itemBox.width + "px";
        glide.style.transform =
          "translateX(" + (itemBox.left - dockBox.left) + "px)";
      };

      requestAnimationFrame(placeGlide);
      window.addEventListener("resize", placeGlide);
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(placeGlide).catch(() => {});
      }
    }
  }

  // -------------------------------------------------------------------------
  // Password reveal
  // -------------------------------------------------------------------------
  $$("[data-reveal]").forEach((button) => {
    button.addEventListener("click", () => {
      const field = document.getElementById(button.getAttribute("data-reveal"));
      if (!field) return;
      const show = field.type === "password";
      field.type = show ? "text" : "password";
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      button.setAttribute("aria-pressed", show ? "true" : "false");
    });
  });
})();

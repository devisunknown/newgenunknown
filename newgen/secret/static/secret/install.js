/* Add-to-home-screen.
 *
 * Android and desktop Chrome hand us a real install prompt through
 * beforeinstallprompt, so the button triggers it. iOS has no such API: the
 * sheet shows the Share -> Add to Home Screen steps instead.
 */
(() => {
  "use strict";

  const DISMISS_KEY = "anylink-install-dismissed";
  const QUIET_DAYS = 30;
  const SHOW_DELAY = 1400;

  const sheet = document.getElementById("install-sheet");
  if (!sheet) return;

  const accept = document.getElementById("install-accept");
  const dismiss = document.getElementById("install-dismiss");
  const steps = document.getElementById("install-steps");

  let deferredPrompt = null;
  let shown = false;

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.matchMedia("(display-mode: fullscreen)").matches ||
      window.navigator.standalone === true
    );
  }

  function isIos() {
    const ua = window.navigator.userAgent || "";
    if (/iPad|iPhone|iPod/.test(ua)) return true;
    // iPadOS reports itself as a Mac; touch points give it away.
    return window.navigator.platform === "MacIntel" &&
      window.navigator.maxTouchPoints > 1;
  }

  function recentlyDeclined() {
    try {
      const raw = window.localStorage.getItem(DISMISS_KEY);
      if (!raw) return false;
      const when = Number(raw);
      if (!when) return true;
      return Date.now() - when < QUIET_DAYS * 86400000;
    } catch (error) {
      return false;
    }
  }

  function remember() {
    try {
      window.localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch (error) {
      /* Private mode: the sheet simply shows again next visit. */
    }
  }

  function open() {
    if (shown || isStandalone()) return;
    shown = true;
    sheet.hidden = false;
    document.body.classList.add("sheet-open");
  }

  function close() {
    sheet.hidden = true;
    document.body.classList.remove("sheet-open");
  }

  accept.addEventListener("click", () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    deferredPrompt.userChoice.then(() => {
      deferredPrompt = null;
      remember();
      close();
    });
  });

  dismiss.addEventListener("click", () => {
    remember();
    close();
  });

  // ui.js closes every sheet on Escape or a backdrop tap.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !sheet.hidden) remember();
  });
  sheet.addEventListener("click", (event) => {
    if (event.target === sheet) remember();
  });

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    if (steps) steps.hidden = true;
    accept.hidden = false;
    setTimeout(open, SHOW_DELAY);
  });

  window.addEventListener("appinstalled", () => {
    remember();
    close();
  });

  if (isIos()) {
    // No event to wait for: show the instructions on their own.
    if (steps) steps.hidden = false;
    accept.hidden = true;
    if (!recentlyDeclined()) setTimeout(open, SHOW_DELAY);
  }

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    });
  }
})();

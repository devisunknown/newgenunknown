/* anylink — one-time room code entry.
   Auto-advances between digits, supports paste, validates through fetch so the
   success state can animate before navigation. The form still posts normally
   when JavaScript is unavailable. */
(() => {
  "use strict";

  const form = document.querySelector("[data-otp-form]");
  if (!form) return;

  const box = form.querySelector("[data-otp]");
  const digits = Array.from(form.querySelectorAll(".otp__digit"));
  const message = form.querySelector("[data-otp-message]");
  const button = form.querySelector("[data-otp-submit]");
  const ghost = document.querySelector("[data-entry-ghost]");
  const check = document.querySelector("[data-entry-check]");
  const overlay = document.querySelector("[data-entry-success]");
  const length = digits.length;
  let busy = false;

  const value = () => digits.map((digit) => digit.value).join("");
  const paint = () =>
    digits.forEach((digit) => digit.classList.toggle("is-filled", Boolean(digit.value)));

  function clearError() {
    box.classList.remove("is-error");
    message.textContent = "";
    message.classList.remove("is-visible");
    digits.forEach((digit) => digit.removeAttribute("aria-invalid"));
  }

  function showError(text) {
    void box.offsetWidth;
    box.classList.add("is-error");
    message.textContent = text;
    message.classList.add("is-visible");
    digits.forEach((digit) => digit.setAttribute("aria-invalid", "true"));
  }

  function fill(text) {
    const chars = text.slice(0, length).split("");
    digits.forEach((digit, index) => {
      digit.value = chars[index] || "";
    });
    paint();
    clearError();
    const next = Math.min(chars.length, length - 1);
    digits[next].focus();
    button.classList.toggle("is-ready", value().length === length);
  }

  digits.forEach((input, index) => {
    input.addEventListener("input", () => {
      const cleaned = input.value.replace(/\D/g, "");
      input.value = cleaned.slice(-1);
      paint();
      clearError();
      if (input.value && index < length - 1) {
        digits[index + 1].focus();
      }
      button.classList.toggle("is-ready", value().length === length);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Backspace" && !input.value && index > 0) {
        event.preventDefault();
        digits[index - 1].value = "";
        digits[index - 1].focus();
        paint();
        button.classList.remove("is-ready");
      } else if (event.key === "ArrowLeft" && index > 0) {
        event.preventDefault();
        digits[index - 1].focus();
      } else if (event.key === "ArrowRight" && index < length - 1) {
        event.preventDefault();
        digits[index + 1].focus();
      }
    });

    input.addEventListener("focus", () => input.select());
  });

  box.addEventListener("paste", (event) => {
    const pasted = (event.clipboardData && event.clipboardData.getData("text")) || "";
    const text = pasted.replace(/\D/g, "");
    if (!text) return;
    event.preventDefault();
    fill(text);
  });

  form.addEventListener("submit", (event) => {
    if (busy) {
      event.preventDefault();
      return;
    }
    if (value().length !== length) {
      event.preventDefault();
      showError("Enter all " + length + " digits.");
      if (digits[value().length]) digits[value().length].focus();
      return;
    }
    if (!window.fetch) return;

    event.preventDefault();
    busy = true;
    button.classList.add("is-loading");
    button.disabled = true;
    clearError();

    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "fetch", Accept: "application/json" },
      credentials: "same-origin",
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.ok && data.redirect) {
          succeed(data.redirect);
        } else {
          fail(data.error || "That code didn't work. Please check it and try again.");
        }
      })
      .catch(() => {
        busy = false;
        button.disabled = false;
        button.classList.remove("is-loading");
        form.submit();
      });
  });

  function fail(text) {
    busy = false;
    button.disabled = false;
    button.classList.remove("is-loading", "is-ready");
    digits.forEach((digit) => {
      digit.value = "";
      digit.disabled = false;
    });
    paint();
    showError(text);
    digits[0].focus();
    if (ghost) {
      ghost.classList.remove("is-happy");
      void ghost.offsetWidth;
      ghost.classList.add("is-happy");
    }
  }

  function succeed(redirect) {
    box.classList.remove("is-error");
    box.classList.add("is-success");
    digits.forEach((digit) => {
      digit.disabled = true;
    });
    clearError();
    if (ghost) {
      ghost.classList.remove("is-happy");
      void ghost.offsetWidth;
      ghost.classList.add("is-happy");
    }
    if (check) check.hidden = false;
    button.classList.remove("is-loading");
    button.classList.add("is-done");
    const label = button.querySelector("span");
    if (label) label.textContent = "You're in";
    if (overlay) {
      overlay.hidden = false;
      requestAnimationFrame(() => overlay.classList.add("is-visible"));
    }
    window.setTimeout(() => window.location.assign(redirect), 1000);
  }
})();

/* anylink — lazily loaded leader directory.
   Skeleton rows render immediately; the real rows are fetched only when the
   list is near the viewport, then the active search filter is re-applied. */
(() => {
  "use strict";

  const list = document.querySelector("[data-people-lazy]");
  if (!list) return;

  const url = list.getAttribute("data-src");
  const search = document.querySelector('[data-filter-target="people-list"]');

  function applyFilter() {
    if (search && search.value.trim()) {
      search.dispatchEvent(new Event("input"));
    }
  }

  function showError() {
    list.removeAttribute("aria-busy");
    list.textContent = "";
    const card = document.createElement("div");
    card.className = "load-error";
    const text = document.createElement("p");
    text.textContent = "We couldn't load the leader directory.";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--secondary btn--sm";
    button.textContent = "Try again";
    button.addEventListener("click", load);
    card.appendChild(text);
    card.appendChild(button);
    list.appendChild(card);
  }

  function load() {
    list.setAttribute("aria-busy", "true");
    fetch(url, {
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
    })
      .then((response) => {
        if (!response.ok) throw new Error("Directory unavailable");
        return response.text();
      })
      .then((html) => {
        list.innerHTML = html;
        list.removeAttribute("aria-busy");
        applyFilter();
      })
      .catch(showError);
  }

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          load();
        }
      },
      { rootMargin: "160px" }
    );
    observer.observe(list);
  } else {
    load();
  }
})();

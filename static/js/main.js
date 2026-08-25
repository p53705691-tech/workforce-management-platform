/*
  Application shell — mobile/tablet drawer behavior (Phase 2).

  Scope kept deliberately small: this only toggles the sidebar drawer
  open/closed for the tablet/mobile off-canvas layout defined in
  static/css/layout.css, plus dismissal for the topbar's native
  <details> user menu. No business logic lives here (frontend.md:
  "keep business rules on the server").

  Focus handling: rather than hand-rolling a full focus trap, `inert` is
  applied to whichever side is not the current interactive surface below
  1024px — the sidebar while the drawer is closed (its off-canvas links
  must never receive keyboard focus), and the page content (#main-content
  + footer + the user menu, all dimmed behind the overlay) while the
  drawer is open, so Tab can't walk a keyboard user out of the open
  drawer into obscured background content. The topbar's drawer-toggle
  itself is deliberately left outside that inert scope — it must stay
  operable to close the drawer, and `inert` has no way to "opt a
  descendant back in" once applied to an ancestor.

  Only the sidebar/toggle/overlay are treated as required for the drawer
  to function; #main-content, the footer, and the user menu are handled
  defensively (null-checked) so a future markup change to any of those
  doesn't silently disable navigation.
*/
(function () {
  "use strict";

  var shell = document.querySelector(".shell");
  if (!shell) {
    return; // unauthenticated pages (login, error pages) render no shell chrome
  }

  var sidebar = document.getElementById("primary-sidebar");
  var sidebarWrap = shell.querySelector(".shell-sidebar");
  var toggle = document.getElementById("drawer-toggle");
  var overlay = shell.querySelector("[data-drawer-overlay]");

  if (!sidebar || !sidebarWrap || !toggle || !overlay) {
    return;
  }

  var mainContent = document.getElementById("main-content");
  var footer = shell.querySelector(".shell-main > footer");
  var userMenu = shell.querySelector(".user-menu");

  function setInert(el, value) {
    if (!el) {
      return;
    }
    if (value) {
      el.setAttribute("inert", "");
    } else {
      el.removeAttribute("inert");
    }
  }

  function setContentInert(value) {
    setInert(mainContent, value);
    setInert(footer, value);
    setInert(userMenu, value);
    if (value && userMenu && userMenu.hasAttribute("open")) {
      userMenu.removeAttribute("open");
    }
  }

  var desktopQuery = window.matchMedia("(min-width: 1024px)");

  function isDesktop() {
    return desktopQuery.matches;
  }

  function isOpen() {
    return shell.hasAttribute("data-drawer-open");
  }

  function firstNavLink() {
    return sidebar.querySelector(".nav-link");
  }

  // Shared by closeDrawer() and the narrow-viewport branch of
  // syncForViewport() — the only difference between "drawer closed by the
  // user" and "drawer reset by a viewport change" is where focus ends up
  // afterwards, which callers handle themselves.
  function applyClosedState() {
    shell.removeAttribute("data-drawer-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open navigation");
    overlay.hidden = true;
    document.body.classList.remove("drawer-locked");
    setContentInert(false);
    sidebarWrap.removeAttribute("inert");
    if (!isDesktop()) {
      sidebarWrap.setAttribute("inert", "");
    }
  }

  function openDrawer() {
    shell.setAttribute("data-drawer-open", "");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close navigation");
    overlay.hidden = false;
    document.body.classList.add("drawer-locked");
    sidebarWrap.removeAttribute("inert");
    if (!isDesktop()) {
      setContentInert(true);
    }

    var link = firstNavLink();
    if (link) {
      link.focus();
    }
  }

  function closeDrawer() {
    applyClosedState();
    toggle.focus();
  }

  // Keep drawer state consistent when the viewport crosses the desktop
  // breakpoint (e.g. rotating a tablet, resizing a browser window).
  function syncForViewport() {
    if (isDesktop()) {
      applyClosedState();
      return;
    }

    if (isOpen()) {
      setContentInert(true);
      return;
    }

    // Moving from desktop (persistent, focusable sidebar) to a narrow
    // viewport (closed, about-to-be-inert sidebar): if focus was inside
    // the sidebar, `inert` would otherwise silently drop it to <body>,
    // stranding a keyboard user at the top of the document.
    if (sidebarWrap.contains(document.activeElement)) {
      toggle.focus();
    }
    sidebarWrap.setAttribute("inert", "");
  }

  toggle.addEventListener("click", function () {
    if (isOpen()) {
      closeDrawer();
    } else {
      openDrawer();
    }
  });

  overlay.addEventListener("click", function () {
    closeDrawer();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") {
      return;
    }
    if (isOpen()) {
      closeDrawer();
    } else if (userMenu && userMenu.hasAttribute("open")) {
      userMenu.removeAttribute("open");
    }
  });

  // Native <details> stays open on outside click; close it like any other
  // dismissible menu.
  if (userMenu) {
    document.addEventListener("click", function (event) {
      if (userMenu.hasAttribute("open") && !userMenu.contains(event.target)) {
        userMenu.removeAttribute("open");
      }
    });
  }

  if (typeof desktopQuery.addEventListener === "function") {
    desktopQuery.addEventListener("change", syncForViewport);
  } else if (typeof desktopQuery.addListener === "function") {
    // Safari < 14 fallback.
    desktopQuery.addListener(syncForViewport);
  }

  syncForViewport();
})();

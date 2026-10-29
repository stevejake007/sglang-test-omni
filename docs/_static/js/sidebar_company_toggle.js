// Sidebar company-group toggle for the SGLang-Omni Cookbook.
//
// Goal (mirrors the SGLang docs / Mintlify model sidebar): clicking an H2
// company heading in the sidebar must ONLY expand/collapse its H3 model
// sub-items in place -- it must not navigate, and must not change the main
// content area. Sub-item links (models) keep their normal navigation.
//
// Rendered DOM (sphinx-book-theme, with collapse_navbar: False):
//   <li class="toctree-l1 has-children">
//     <a class="reference internal" href="companies/qwen.html">Qwen</a>
//     <details open="open"><summary>...</summary><ul> ...models... </ul></details>
//   </li>
// Company groups are the only nested toctree items in the sidebar, so
// `li.toctree-l1.has-children` identifies them reliably.
(function () {
  "use strict";
  try {
    var COMPANY_GROUP_SELECTOR =
      "nav.bd-links li.toctree-l1.has-children > a";
    var EXPAND_MS = 250;
    var COLLAPSE_MS = 200;

    function findDetails(link) {
      var li = link && link.parentElement;
      return li ? li.querySelector(":scope > details") : null;
    }

    function setTransitionStyle(ul, value) {
      ul.style.transition =
        "max-height " + value + "ms ease-in-out, visibility " + value + "ms";
    }

    function expand(details) {
      var ul = details.querySelector(":scope > ul");
      if (!ul) {
        details.setAttribute("open", "open");
        return;
      }
      details.setAttribute("open", "open");
      setTransitionStyle(ul, EXPAND_MS);
      ul.style.maxHeight = "0px";
      ul.style.visibility = "visible";
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          ul.style.maxHeight = ul.scrollHeight + "px";
        });
      });
      ul.addEventListener(
        "transitionend",
        function onEnd() {
          ul.removeEventListener("transitionend", onEnd);
          ul.style.maxHeight = "";
          ul.style.transition = "";
          ul.style.visibility = "";
        },
        false
      );
    }

    function collapse(details) {
      var ul = details.querySelector(":scope > ul");
      if (!ul) {
        details.removeAttribute("open");
        return;
      }
      setTransitionStyle(ul, COLLAPSE_MS);
      ul.style.maxHeight = ul.scrollHeight + "px";
      requestAnimationFrame(function () {
        ul.style.maxHeight = "0px";
      });
      window.setTimeout(function () {
        ul.style.transition = "";
        ul.style.maxHeight = "";
        ul.style.visibility = "";
        details.removeAttribute("open");
      }, COLLAPSE_MS + 40);
    }

    function toggle(details) {
      if (details.hasAttribute("open")) {
        collapse(details);
      } else {
        expand(details);
      }
    }

    function init() {
      var links = document.querySelectorAll(COMPANY_GROUP_SELECTOR);
      if (!links.length) {
        return;
      }
      for (var i = 0; i < links.length; i++) {
        var link = links[i];
        var details = findDetails(link);
        if (!details) {
          continue;
        }
        // Keep only the active group expanded on first paint; collapse the rest.
        var li = link.parentElement;
        if (!li.classList.contains("active") && li.classList.contains("has-children")) {
          details.removeAttribute("open");
        }
        link.addEventListener(
          "click",
          function (evt) {
            evt.preventDefault();
            evt.stopPropagation();
            var d = findDetails(this);
            if (d) {
              toggle(d);
            }
          },
          false
        );
      }
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init, false);
    } else {
      init();
    }
  } catch (err) {
    // Never break the docs page if this enhancement fails.
    if (window.console && console.warn) {
      console.warn("sidebar company toggle unavailable:", err);
    }
  }
})();

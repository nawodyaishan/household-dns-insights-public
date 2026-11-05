/* Local-only progressive enhancement: no remote requests, no data collection. */
(function () {
  "use strict";

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("form[data-single-submit]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var button = form.querySelector("button[type=submit]");
      if (!button || button.disabled) {
        return;
      }
      button.disabled = true;
      button.textContent = "Working…";
    });
  });

  var panel = document.querySelector("[data-analysis-id]");
  if (panel) {
    var analysisId = panel.getAttribute("data-analysis-id");
    var terminal = { completed: true, partial: true, failed: true, cancelled: true };
    var timer = window.setInterval(function () {
      fetch("/api/analysis/" + encodeURIComponent(analysisId), {
        headers: { Accept: "application/json" },
        credentials: "same-origin"
      })
        .then(function (response) {
          return response.ok ? response.json() : null;
        })
        .then(function (data) {
          if (data && terminal[data.state]) {
            window.clearInterval(timer);
            window.location.reload();
          }
        })
        .catch(function () {
          /* A transient local failure is not an analysis failure. */
        });
    }, 5000);
  }
})();

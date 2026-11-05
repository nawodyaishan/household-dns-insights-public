"use strict";

const householdForm = document.querySelector("#household-generate");
if (householdForm) {
  const status = document.querySelector("#household-status");
  householdForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = householdForm.querySelector("button");
    button.disabled = true;
    try {
      const response = await fetch(householdForm.action, {
        method: "POST", body: new FormData(householdForm), credentials: "same-origin",
        headers: { "Accept": "application/json" },
      });
      if (!response.ok) throw new Error("Report request unavailable. Try again later.");
      const job = await response.json();
      status.textContent = "Report " + job.state + ". Waiting for the local worker…";
      for (let i = 0; i < 120; i++) {
        await new Promise((resolve) => setTimeout(resolve, 5000));
        const result = await fetch("/household/jobs/" + encodeURIComponent(job.job_id),
          { credentials: "same-origin" });
        if (!result.ok) throw new Error("Report status unavailable.");
        const current = await result.json();
        status.textContent = "Report " + current.state + ".";
        if (current.state === "ready" && current.report_id) {
          window.location.assign("/household/reports/" + encodeURIComponent(current.report_id));
          return;
        }
        if (current.state === "failed") throw new Error("Report failed. Request a new revision.");
      }
      throw new Error("Still pending; refresh and request the same window to check again.");
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    }
  });
}

(() => {
  "use strict";

  const installButton = document.querySelector("[data-install-app]");
  const connectionBanner = document.querySelector("[data-connection-banner]");
  const ideaField = document.querySelector("#idea");
  const ideaCount = document.querySelector("[data-idea-count]");
  const ideaSubmit = document.querySelector("[data-idea-submit]");
  const fileStatus = document.querySelector("[data-file-status]");
  const preflightPanel = document.querySelector("[data-idea-preflight]");
  const preflightTrigger = document.querySelector("[data-idea-preflight-trigger]");
  const preflightSummary = document.querySelector("[data-idea-preflight-summary]");
  const preflightNext = document.querySelector("[data-idea-preflight-next]");
  const minIdeaLength = 10;
  const maxIdeaLength = 8000;
  let deferredInstallPrompt = null;
  let preflightShown = false;

  // This is deliberately a transparent writing aid, not an AI assessment or a
  // demand score. It only spots cues in the user's local draft so founders can
  // make the hypothesis that Killgate will test more specific before saving it.
  const IDEA_PREFLIGHT_CHECKS = {
    buyer: {
      label: "named buyer",
      found: "A likely buyer or organization is stated.",
      missing: "Name one kind of person, team, or organization that has this problem.",
      matches: [
        /\b(?:owners?|managers?|operators?|founders?|teams?|shops?|companies|businesses|restaurants?|clinics?|contractors?|technicians?|agencies|practices|parents?|students?|drivers?|homeowners?|landlords?|accountants?|bookkeepers?|lawyers?|attorneys?|engineers?|designers?|developers?|marketers?|sales(?:people|\s+reps?)?|realtors?|brokers?|groomers?|mechanics?|plumbers?|electricians?|dentists?|doctors?|patients?|caregivers?|teachers?|educators?|nurses?|freelancers?|creators?|vendors?|retailers?|walkers?|gyms?|hotels?|smbs?)\b/i,
      ],
    },
    problem: {
      label: "costly or repeated problem",
      found: "A concrete problem, cost, risk, or recurring job is stated.",
      missing: "Describe a recent recurring job, cost, risk, delay, or frustration they face.",
      matches: [
        /\b(?:miss(?:ed|ing)?|lose|losing|lost|struggle|struggling|waste|wasting|delay(?:ed|s|ing)?|slow|slower|expensive|costly|risk(?:y)?|manual|busy|churn|error(?:s)?|late|failure|fail(?:s|ing)?|friction|urgent|overwhelm(?:ed|ing)?|backlog|bottleneck|no-?show(?:s)?|cancel(?:s|led|ing)?)\b/i,
        /\b(?:cannot|can(?:not|'t)|unable to|too (?:much|long|slow|expensive))\b/i,
      ],
    },
    offer: {
      label: "offer or change",
      found: "A proposed offer, tool, service, or workflow change is stated.",
      missing: "Say what you would sell, build, or change for that buyer.",
      matches: [
        /\b(?:i\s+(?:want|will|plan|hope)\s+to\s+(?:build|sell|offer|create|make)|(?:build|sell|offer|create|make|provide|launch)\s+(?:an?\s+)?(?:app|tool|service|platform|system|assistant|workflow|product|software|marketplace|program))\b/i,
        /\b(?:ai|app|software|saas|service|platform|assistant|automation|tool|marketplace|consulting|subscription)\b/i,
      ],
    },
    economics: {
      label: "economics or outcome",
      found: "A price, current cost, time, revenue, or measurable outcome is stated.",
      missing: "Add a price, current workaround cost, time saved, or measurable outcome that matters.",
      matches: [
        /\$\s*\d+/,
        /\b(?:pay|price|pricing|budget|revenue|costs?|spend|saving|save|roi|margin|profit|per\s+(?:month|year|user|job)|hours?|minutes?|book(?:ed|ing)?|conversion|retention|reduce|increase)\b/i,
      ],
    },
  };

  const draftMatches = (draft, checks) => checks.some((pattern) => pattern.test(draft));

  const updateIdeaPreflight = () => {
    if (!ideaField || !preflightPanel || !preflightShown) return;

    const draft = ideaField.value.trim();
    const charactersNeeded = Math.max(0, minIdeaLength - draft.length);
    preflightPanel.hidden = false;
    preflightTrigger?.setAttribute("aria-expanded", "true");

    if (charactersNeeded) {
      Object.entries(IDEA_PREFLIGHT_CHECKS).forEach(([key, check]) => {
        const row = preflightPanel.querySelector(`[data-idea-preflight-check="${key}"]`);
        const marker = row?.querySelector("[data-idea-preflight-marker]");
        const detail = row?.querySelector("[data-idea-preflight-detail]");
        row?.classList.remove("is-present");
        if (marker) marker.textContent = "○";
        if (detail) detail.textContent = check.missing;
      });
      if (preflightSummary) {
        preflightSummary.textContent = `Add ${charactersNeeded} more character${charactersNeeded === 1 ? "" : "s"} to check this draft.`;
      }
      if (preflightNext) {
        preflightNext.textContent = "Start with: For [specific buyer], who [repeated problem], I would sell [offer] so they can [outcome] for/about [price or current cost].";
      }
      return;
    }

    const missing = [];
    let presentCount = 0;
    Object.entries(IDEA_PREFLIGHT_CHECKS).forEach(([key, check]) => {
      const present = draftMatches(draft, check.matches);
      const row = preflightPanel.querySelector(`[data-idea-preflight-check="${key}"]`);
      const marker = row?.querySelector("[data-idea-preflight-marker]");
      const detail = row?.querySelector("[data-idea-preflight-detail]");
      row?.classList.toggle("is-present", present);
      if (marker) marker.textContent = present ? "✓" : "○";
      if (detail) detail.textContent = present ? check.found : check.missing;
      if (present) {
        presentCount += 1;
      } else {
        missing.push(check);
      }
    });

    if (preflightSummary) {
      preflightSummary.textContent = presentCount === 4
        ? "Your draft appears to state all four ingredients Killgate needs to target the brief. It is still an untested hypothesis."
        : `Your draft appears to state ${presentCount} of 4 ingredients. This is not a demand score; it shows what would make the test more specific.`;
    }
    if (preflightNext) {
      const next = missing[0];
      preflightNext.textContent = next
        ? `Next: ${next.missing} A useful shape is: For [buyer], who [problem], I would sell [offer] so they can [outcome] for/about [price or current cost].`
        : "Next: show the research brief when you are ready. Killgate will lock the question before any research runs.";
    }
  };

  const updateIdeaInputState = () => {
    if (!ideaField) return;

    const length = ideaField.value.length;
    if (ideaCount) {
      ideaCount.textContent = `${length.toLocaleString()} / ${maxIdeaLength.toLocaleString()} characters`;
    }
    if (ideaSubmit) {
      ideaSubmit.disabled = ideaField.value.trim().length < minIdeaLength;
    }
    updateIdeaPreflight();
  };

  ideaField?.addEventListener("input", updateIdeaInputState);
  preflightTrigger?.addEventListener("click", () => {
    preflightShown = true;
    updateIdeaPreflight();
    preflightPanel?.focus();
  });
  updateIdeaInputState();

  const updateConnectionState = () => {
    if (!connectionBanner) return;
    connectionBanner.hidden = navigator.onLine;
  };

  window.addEventListener("online", updateConnectionState);
  window.addEventListener("offline", updateConnectionState);
  updateConnectionState();

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    if (installButton) installButton.hidden = false;
  });

  installButton?.addEventListener("click", async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    installButton.hidden = true;
  });

  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    if (installButton) installButton.hidden = true;
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {
        // Killgate remains fully usable as a normal website if registration fails.
      });
    });
  }

  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    const targetId = button.getAttribute("aria-controls");
    const input = targetId
      ? document.getElementById(targetId)
      : button.closest(".password-field")?.querySelector("[data-password-input]");
    if (!input) return;

    button.addEventListener("click", () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      button.setAttribute("aria-pressed", String(show));
    });
  });

  document.querySelectorAll("[data-confirm-void]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const confirmed = window.confirm(
        "Void this mistaken evidence entry? The original will stay in the audit trail and stop counting toward the gate.",
      );
      if (!confirmed) event.preventDefault();
    });
  });

  if ("launchQueue" in window && "LaunchParams" in window) {
    window.launchQueue.setConsumer(async (launchParams) => {
      const handle = launchParams.files?.[0];
      if (!handle || !ideaField) return;

      try {
        const file = await handle.getFile();
        if (file.size > 1024 * 1024) {
          if (fileStatus) fileStatus.textContent = "That file is over the 1 MB import limit.";
          return;
        }

        const contents = (await file.text()).trim().slice(0, 8000);
        ideaField.value = contents;
        updateIdeaInputState();
        ideaField.focus();
        ideaField.scrollIntoView({ behavior: "smooth", block: "center" });
        if (fileStatus) fileStatus.textContent = `Loaded ${file.name}. Review it before testing.`;
      } catch {
        if (fileStatus) fileStatus.textContent = "Killgate could not read that idea brief.";
      }
    });
  }
})();

// Google Play Billing for the Play Store Trusted Web Activity. The client only
// obtains purchase tokens; entitlement is granted exclusively after backend verification.
(async () => {
  "use strict";
  const panels = Array.from(document.querySelectorAll("[data-play-billing]"));
  if (!panels.length) return;
  const storeId = "https://play.google.com/billing";

  const verifyOnBackend = async (purchaseToken, itemId, familyId = "") => {
    const response = await fetch("/billing/google-play/verify", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({purchase_token: purchaseToken, product_id: itemId, family_id: familyId}),
    });
    const result = await response.json().catch(() => ({ok: false, error: "Verification failed."}));
    if (!response.ok || !result.ok) throw new Error(result.error || "Verification failed.");
    return result;
  };

  const bindPanel = async (panel, service) => {
    const button = panel.querySelector("[data-play-subscribe]");
    const status = panel.querySelector("[data-billing-status]");
    const detail = panel.querySelector("[data-billing-detail]");
    const price = panel.querySelector("[data-billing-price]");
    const productId = panel.dataset.productId;
    const familyId = panel.dataset.familyId || "";
    if (!productId) return;

    if (!service) {
      if (button) button.hidden = true;
      if (detail) detail.textContent = "Google Play checkout is available inside the Killgate app installed from Google Play.";
      return;
    }

    try {
      const items = await service.getDetails([productId]);
      const item = items.find((candidate) => candidate.itemId === productId) || items[0];
      if (item?.price?.currency && item?.price?.value && price) {
        const numericValue = Number(item.price.value);
        const formatted = Number.isFinite(numericValue)
          ? new Intl.NumberFormat(navigator.language, {style: "currency", currency: item.price.currency}).format(numericValue)
          : `${item.price.value} ${item.price.currency}`;
        const period = item.subscriptionPeriod === "P1M" ? " / month" : "";
        price.textContent = `${formatted}${period}`;
      }
    } catch {
      // Never hard-code a fallback price. Google Play remains the localized price source of truth.
    }

    try {
      const existing = await service.listPurchases();
      const purchase = existing.find((item) => item.itemId === productId);
      if (purchase?.purchaseToken) {
        const verified = await verifyOnBackend(purchase.purchaseToken, productId, familyId);
        if (verified.active && status) status.textContent = "Google Play purchase verified";
      }
    } catch {
      // Do not invent entitlement from a local list failure. The server remains authoritative.
    }

    button?.addEventListener("click", async () => {
      button.disabled = true;
      if (detail) detail.textContent = "Opening Google Play…";
      let paymentResponse = null;
      try {
        const methods = [{supportedMethods: storeId, data: {sku: productId}}];
        const paymentDetails = {total: {label: "Total", amount: {currency: "USD", value: "0"}}};
        const request = new PaymentRequest(methods, paymentDetails);
        paymentResponse = await request.show();
        const purchaseToken = paymentResponse?.details?.purchaseToken;
        if (!purchaseToken) throw new Error("Google Play did not return a purchase token.");
        const verified = await verifyOnBackend(purchaseToken, productId, familyId);
        await paymentResponse.complete(verified.active || verified.ok ? "success" : "fail");
        if (detail) detail.textContent = "Purchase verified by Google Play.";
        window.location.reload();
      } catch (error) {
        if (paymentResponse) {
          try { await paymentResponse.complete("fail"); } catch { /* already completed */ }
        }
        if (detail) detail.textContent = error?.name === "AbortError" ? "Purchase canceled." : (error?.message || "Google Play checkout failed.");
      } finally {
        button.disabled = false;
      }
    });
  };

  let service = null;
  if ("getDigitalGoodsService" in window && "PaymentRequest" in window) {
    try {
      service = await window.getDigitalGoodsService(storeId);
    } catch {
      service = null;
    }
  }
  for (const panel of panels) {
    await bindPanel(panel, service);
  }
})();

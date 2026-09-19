// Granum website: fills in what the server knows (version, contact, downloads) and runs the
// download form. No framework; every page works without it except the form itself.

(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  $$("[data-year]").forEach((el) => { el.textContent = String(new Date().getFullYear()); });

  // -- header: a hairline once the page scrolls, and the menu on small screens ------------

  const header = $(".site-header");
  if (header) {
    const onScroll = () => header.classList.toggle("scrolled", window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    const menu = $(".menu-button", header);
    if (menu) {
      const setOpen = (open) => {
        header.classList.toggle("open", open);
        menu.setAttribute("aria-expanded", String(open));
      };
      menu.addEventListener("click", () => setOpen(!header.classList.contains("open")));
      $$(".nav a", header).forEach((a) => a.addEventListener("click", () => setOpen(false)));
      document.addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });
    }
  }

  // -- product tour tabs (without the script every panel shows, stacked) ------------------

  const tabs = $$('[role="tab"]');
  if (tabs.length) {
    const select = (tab, focus) => {
      for (const t of tabs) {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        const panel = document.getElementById(t.getAttribute("aria-controls"));
        panel.hidden = !on;
        panel.classList.toggle("show", on);
      }
      if (focus) tab.focus();
    };
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => select(tab, false));
      tab.addEventListener("keydown", (e) => {
        const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
        if (step) { e.preventDefault(); select(tabs[(i + step + tabs.length) % tabs.length], true); }
        if (e.key === "Home") { e.preventDefault(); select(tabs[0], true); }
        if (e.key === "End") { e.preventDefault(); select(tabs[tabs.length - 1], true); }
      });
    });
    select(tabs.find((t) => t.getAttribute("aria-selected") === "true") || tabs[0], false);
  }

  // -- illustration charts: inline the SVG so it can animate in when it comes into view ---

  const charts = $$("[data-chart]");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (charts.length && "IntersectionObserver" in window && !reduced) {
    const seen = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("in");
        seen.unobserve(entry.target);
      }
    }, { threshold: 0.35 });
    charts.forEach((holder) => {
      const img = $("img", holder);
      fetch(holder.dataset.chart)
        .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
        .then((text) => {
          const svg = new DOMParser().parseFromString(text, "image/svg+xml").documentElement;
          if (svg.nodeName !== "svg") return; // keep the <img>
          holder.classList.add("pre");
          img.replaceWith(document.importNode(svg, true));
          seen.observe(holder);
        })
        .catch(() => { /* the <img> stays, drawn complete */ });
    });
  }

  // -- what the server says ------------------------------------------------------------

  fetch("/v1/site", { headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : null))
    .then((site) => {
      if (!site) return;
      if (site.version) $$("[data-version]").forEach((el) => { el.textContent = `Version ${site.version}`; });
      if (site.contact) {
        $$("[data-contact-sentence]").forEach((el) => { el.textContent = ` by writing to ${site.contact}`; });
        $$("[data-contact]").forEach((el) => {
          el.href = `mailto:${site.contact}?subject=${encodeURIComponent(el.dataset.contact || "Granum")}`;
          el.hidden = false;
        });
      }
    })
    .catch(() => { /* the page stands on its own */ });

  // -- pricing: monthly or yearly -------------------------------------------------------

  const billing = $$("[data-billing]");
  const showBilling = (period) => {
    billing.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.billing === period)));
    $$(`[data-${period}]`).forEach((el) => { el.textContent = el.dataset[period]; });
    $$('a[href^="/quote?plan="]').forEach((a) => {
      const url = new URL(a.href, location.href);
      if (url.searchParams.get("plan") !== "Enterprise") url.searchParams.set("billing", period);
      a.href = url.pathname + url.search;
    });
  };
  billing.forEach((b) => b.addEventListener("click", () => showBilling(b.dataset.billing)));
  if (billing.length) showBilling("yearly");

  // -- buy / request a quote -------------------------------------------------------------

  const quote = $("#quote-form");
  if (quote) {
    const params = new URLSearchParams(location.search);
    const plan = $("#q-plan");
    const billingSelect = $("#q-billing");
    const computers = $("#q-computers");
    const quoteError = $("#quote-error");
    const quoteSubmit = $("#quote-submit");
    const COPY = {
      Single: ["Buy Granum Single.", "Send your details and we will email you an invoice with a payment link.", "Buy Single", 1],
      Team: ["Buy Granum Team.", "Send your details and we will email you an invoice with a payment link.", "Buy Team", 5],
      Enterprise: ["Granum Enterprise for your company.", "Tell us about your team and we will reply by email with a quote, usually within one business day.", "Request a quote", 10],
    };
    const showPlan = (name, initial) => {
      const [title, lead, action, seats] = COPY[name] || COPY.Enterprise;
      $("#quote-title").textContent = title;
      $("#quote-lead").textContent = lead;
      $("#quote-form-title").textContent = action;
      quoteSubmit.textContent = name === "Enterprise" ? "Send request" : action;
      document.title = name === "Enterprise" ? "Request a quote: Granum" : `${action}: Granum`;
      $$(".plan-summary").forEach((el) => { el.hidden = el.dataset.for !== name; });
      const fixed = name !== "Enterprise";
      if (fixed || initial) computers.value = String(seats);
      $("#q-billing-field").hidden = !fixed;
      $("#q-computers-field").hidden = fixed;
    };
    const wanted = params.get("plan");
    if (wanted && COPY[wanted]) plan.value = wanted;
    if (params.get("billing") === "monthly") billingSelect.value = "monthly";
    showPlan(plan.value, true);
    plan.addEventListener("change", () => showPlan(plan.value, false));

    const fail = (message, field) => {
      quoteError.textContent = message;
      quoteError.hidden = false;
      if (field) { field.setAttribute("aria-invalid", "true"); field.focus(); }
    };
    quote.addEventListener("submit", async (event) => {
      event.preventDefault();
      $$("[aria-invalid]", quote).forEach((el) => el.removeAttribute("aria-invalid"));
      quoteError.hidden = true;
      const email = $("#q-email");
      const name = $("#q-name");
      const company = $("#q-company");
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim())) return fail("Enter a valid email address.", email);
      if (!name.value.trim()) return fail("Enter your name.", name);
      if (!company.value.trim()) return fail("Enter your company.", company);
      const seats = parseInt(computers.value, 10);
      if (!(seats >= 1)) return fail("Enter how many computers you need.", computers);
      const fixed = plan.value !== "Enterprise";
      const note = $("#q-message").value.trim();
      const body = {
        plan: plan.value,
        email: email.value.trim(),
        name: name.value.trim(),
        company: company.value.trim(),
        computers: seats,
        message: (fixed ? `Billing: ${billingSelect.value}\n\n` : "") + note,
        website: $("#q-website").value,
      };
      quoteSubmit.disabled = true;
      const label = quoteSubmit.textContent;
      quoteSubmit.textContent = "Sending";
      try {
        const response = await fetch("/v1/quote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const answer = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof answer.detail === "string" ? answer.detail : "The request did not go through. Try again in a moment.");
        $("#quote-done-email").textContent = body.email;
        quote.hidden = true;
        $("#quote-done").hidden = false;
      } catch (e) {
        fail(e instanceof Error ? e.message : String(e));
      } finally {
        quoteSubmit.disabled = false;
        quoteSubmit.textContent = label;
      }
    });
  }

  // -- the download form ------------------------------------------------------------------

  const form = $("#download-form");
  if (!form) return;

  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent || "";
  if (/linux/i.test(platform) && !/android/i.test(navigator.userAgent)) {
    const linux = $('input[name="os"][value="linux"]', form);
    if (linux) linux.checked = true;
  }

  const email = $("#email");
  const error = $("#form-error");
  const submit = $("#submit");
  const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

  const showError = (message) => {
    error.textContent = message;
    error.hidden = !message;
  };

  const LABEL = { windows: "Windows", linux: "Linux" };
  const STEPS = {
    windows: [
      "Run the downloaded installer. It installs for your user only; no administrator rights needed.",
      "If Windows shows <em>Windows protected your PC</em>, choose <strong>More info</strong>, then <strong>Run anyway</strong>.",
      "Open Granum from the Start menu.",
    ],
    linux: [
      "Make the file executable: <code>chmod +x Granum-*.AppImage</code>",
      "Run it: <code>./Granum-*.AppImage</code>. It adds Granum to your applications menu.",
    ],
  };

  const fileName = (url) => {
    try {
      return decodeURIComponent(new URL(url).pathname.split("/").pop() || url);
    } catch {
      return url;
    }
  };

  const renderDone = (chosen, downloads, address) => {
    const files = $("#files");
    files.textContent = "";
    const order = [chosen, ...Object.keys(downloads).filter((os) => os !== chosen)];
    let any = false;
    for (const os of order) {
      const url = downloads[os];
      if (!url) continue;
      any = true;
      const row = document.createElement("div");
      row.className = "file";
      const text = document.createElement("div");
      const name = document.createElement("div");
      name.className = "name";
      name.textContent = fileName(url);
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = LABEL[os] || os;
      text.append(name, meta);
      const link = document.createElement("a");
      link.className = os === chosen ? "btn primary small" : "btn small";
      link.href = url;
      link.textContent = `Download for ${LABEL[os] || os}`;
      link.rel = "noopener";
      row.append(text, link);
      files.append(row);
    }
    if (!any) {
      const note = document.createElement("p");
      note.className = "muted";
      note.textContent = "Downloads open very soon. We have saved your email and will write when they are up.";
      files.append(note);
    }
    const steps = $("#steps");
    steps.textContent = "";
    if (any && downloads[chosen]) {
      const list = document.createElement("ol");
      list.className = "install";
      for (const step of STEPS[chosen] || []) {
        const item = document.createElement("li");
        item.innerHTML = step; // fixed text from above, never user input
        list.append(item);
      }
      steps.append(list);
    }
    $("#done-email").textContent = address;
    form.hidden = true;
    $("#done").hidden = false;
    const first = $("#files a");
    if (first) first.focus();
  };

  const verify = $("#verify-form");
  const code = $("#code");
  const verifyError = $("#verify-error");
  const verifySubmit = $("#verify-submit");
  let pending = null; // what step one collected

  const post = async (path, body) => {
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const answer = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof answer.detail === "string" ? answer.detail : "Something went wrong. Try again in a moment.";
      throw new Error(detail);
    }
    return answer;
  };

  const sendCode = async () => {
    const sent = await post("/v1/download/code", { email: pending.email });
    const dev = $("#dev-code");
    dev.hidden = !sent.dev_code;
    dev.textContent = sent.dev_code ? `Development server: the code is ${sent.dev_code}` : "";
  };

  // Step one: details, then a code to the inbox.
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const address = email.value.trim();
    if (!EMAIL.test(address)) {
      email.setAttribute("aria-invalid", "true");
      showError("Enter a valid email address.");
      email.focus();
      return;
    }
    email.removeAttribute("aria-invalid");
    showError("");
    pending = {
      email: address,
      os: ($('input[name="os"]:checked', form) || {}).value || "windows",
      name: $("#name").value.trim(),
      company: $("#company").value.trim(),
    };
    submit.disabled = true;
    submit.textContent = "Sending the code";
    try {
      await sendCode();
      $("#verify-email").textContent = address;
      code.value = "";
      verifyError.hidden = true;
      form.hidden = true;
      verify.hidden = false;
      code.focus();
    } catch (e) {
      showError(e instanceof Error ? e.message : String(e));
    } finally {
      submit.disabled = false;
      submit.textContent = "Email me a download code";
    }
  });

  code.addEventListener("input", () => { code.value = code.value.replace(/\D/g, "").slice(0, 6); });

  // Step two: the code proves the address; then the links.
  verify.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (code.value.length !== 6) {
      verifyError.textContent = "Enter the 6-digit code from the email.";
      verifyError.hidden = false;
      return;
    }
    verifySubmit.disabled = true;
    verifySubmit.textContent = "Checking";
    try {
      const body = await post("/v1/download", { ...pending, code: code.value });
      verify.hidden = true;
      renderDone(pending.os, body.downloads || {}, pending.email);
    } catch (e) {
      verifyError.textContent = e instanceof Error ? e.message : String(e);
      verifyError.hidden = false;
    } finally {
      verifySubmit.disabled = false;
      verifySubmit.textContent = "Verify and download";
    }
  });

  $("#resend").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await sendCode();
      verifyError.textContent = "A new code is on its way.";
      verifyError.hidden = false;
    } catch (e) {
      verifyError.textContent = e instanceof Error ? e.message : String(e);
      verifyError.hidden = false;
    } finally {
      window.setTimeout(() => { button.disabled = false; }, 15000);
    }
  });

  $("#change").addEventListener("click", () => {
    verify.hidden = true;
    form.hidden = false;
    email.focus();
  });
})();

/* Operator Wall: charter review overlay. Answer questions, edit the draft, save / approve. Same-origin POST with the CSRF token.
   Rows are reconciled (never rebuilt) while the overlay is open, so the 60 s wall refresh cannot wipe typed input. */
const WallReview = (() => {
  const APPROVE_URL = "/api/mc/charters/approve";
  const UPDATE_URL = "/api/mc/charters/update";
  const MAX_TEXT = 600;
  const PERSON_RE = /^[a-z][a-z0-9_-]{1,31}$/;
  const TYPES = [["client-delivery", "Klient"], ["product", "Produkt"], ["platform", "Infrastruktura"], ["experiment", "Eksperyment"], ["dormant", "Uśpiony"]];
  const CADENCES = [["daily", "Codziennie"], ["weekly", "Co tydzień"], ["monthly", "Co miesiąc"], ["none", "Brak"]];
  const $ = (id) => document.getElementById(id);
  const csrf = () => document.querySelector('meta[name="jit-hub-csrf"]')?.content || "";
  const rootOf = (slug) => document.querySelector(`.draft[data-slug="${CSS.escape(slug)}"]`);
  const clock = () => new Date().toLocaleTimeString("pl-PL", {hour: "2-digit", minute: "2-digit"});

  async function post(url, payload) {
    try {
      const res = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-Jit-Hub-Csrf": csrf()}, body: JSON.stringify(payload)});
      const body = await res.json();
      return {ok: res.ok, body, error: body.error || `HTTP ${res.status}`};
    } catch (err) {
      return {ok: false, body: {}, error: err.message};
    }
  }

  function answerOf(c, question) {
    return ((c.answers || []).find((a) => a.question === question) || {}).answer || "";
  }

  function unansweredCount(c) {
    return (c.questions || []).filter((q) => !answerOf(c, q)).length;
  }

  function plQuestions(n) {
    return n === 1 ? "1 pytanie bez odpowiedzi" : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) ? `${n} pytania bez odpowiedzi` : `${n} pytań bez odpowiedzi`;
  }

  function select(options, current, cls) {
    const sel = h("select", {class: cls});
    for (const [value, label] of options) sel.append(h("option", {value, selected: value === current ? "" : null}, label));
    return sel;
  }

  function area(cls, value) {
    const el = h("textarea", {class: cls, maxlength: MAX_TEXT, rows: 3});
    el.value = value || "";
    return el;
  }

  const labeled = (text, control) => h("label", {class: "fld"}, h("span", {}, text), control);

  function personBox(who, checked) {
    const box = h("input", {type: "checkbox", "data-who": who, "aria-label": `Odbiorca ${who}`});
    box.checked = checked;
    return h("label", {}, box, who);
  }

  function audienceBlock(c) {
    const current = (c.audience || []).filter((w) => w !== "me");
    const names = [...new Set([...(c.audience_candidates || []).map((x) => x.who), ...current])];
    const only = h("span", {class: "only"}, "tylko ja");
    const who = h("div", {class: "who"}, names.map((n) => personBox(n, current.includes(n))));
    const input = h("input", {type: "text", class: "add-name", placeholder: "np. dominik", "aria-label": "Dodaj osobę"});
    const msg = h("span", {class: "res err"});
    const add = h("button", {type: "button", class: "btn"}, "Dodaj osobę");
    const refresh = () => { only.hidden = who.querySelectorAll("input:checked").length > 0; };
    add.addEventListener("click", () => {
      const name = input.value.trim();
      if (!PERSON_RE.test(name)) { msg.textContent = "Mała litera na początku, potem litery, cyfry, _ lub -, 2-32 znaki."; return; }
      msg.textContent = "";
      const existing = who.querySelector(`input[data-who="${CSS.escape(name)}"]`);
      if (existing) existing.checked = true; else who.append(personBox(name, true));
      input.value = ""; refresh();
    });
    who.addEventListener("change", refresh);
    refresh();
    return h("div", {class: "fld"}, h("span", {}, "Odbiorcy (oprócz mnie)"), who, h("div", {class: "who add"}, input, add, msg), only);
  }

  function questionsBlock(c) {
    return (c.questions || []).map((q, i) => {
      const box = area("q", answerOf(c, q));
      box.dataset.question = q;
      box.setAttribute("aria-label", `Twoja odpowiedź na pytanie ${i + 1}`);
      box.addEventListener("input", () => refreshCount(c.slug));
      return labeled(q, box);
    });
  }

  function evidenceBlock(c) {
    const items = (c.evidence || []).map((v) => (typeof v === "string" ? v : `${v.who || ""} ${v.why || ""}`.trim()));
    return items.length ? h("ul", {class: "ev"}, items.map((t) => h("li", {}, t))) : null;
  }

  function body(c, one, save) {
    const res = h("span", {class: "res", role: "status"});
    return h("div", {class: "d-body"},
      h("div", {class: "pair"}, labeled("Typ", select(TYPES, c.type, "f-type")), labeled("Częstotliwość", select(CADENCES, c.cadence || "none", "f-cadence"))),
      labeled("Cel", area("f-goal", c.goal)), labeled("Sukces", area("f-success", c.success)),
      audienceBlock(c), evidenceBlock(c),
      (c.questions || []).length ? h("h2", {style: "margin-top:18px"}, "Pytania") : null, ...questionsBlock(c),
      h("div", {class: "d-actions"}, save, one, res));
  }

  function row(c) {
    const include = h("input", {type: "checkbox", class: "inc", "data-slug": c.slug, "aria-label": `Zaznacz ${c.slug}`});
    const save = h("button", {type: "button", class: "btn"}, "Zapisz");
    const one = h("button", {type: "button", class: "btn primary"}, "Zatwierdź");
    save.addEventListener("click", () => saveOne(c.slug));
    one.addEventListener("click", () => approve([c.slug]));
    const tog = h("button", {type: "button", class: "tog", "aria-expanded": "false"}, chevron(), h("span", {class: "name"}, c.slug),
      h("span", {class: "meta"}, TYPE_LABEL[c.type] || c.type || ""), h("span", {class: "pend"}));
    const root = h("div", {class: "draft", "data-slug": c.slug}, h("div", {class: "d-head"}, include, tog), body(c, one, save));
    tog.addEventListener("click", () => { const open = root.classList.toggle("open"); tog.setAttribute("aria-expanded", String(open)); });
    root.dataset.pending = String(unansweredCount(c));
    root.querySelector(".pend").textContent = unansweredCount(c) ? plQuestions(unansweredCount(c)) : "";
    return root;
  }

  function refreshCount(slug) {
    const root = rootOf(slug);
    const empty = [...root.querySelectorAll("textarea.q")].filter((t) => !t.value.trim()).length;
    root.querySelector(".pend").textContent = empty ? plQuestions(empty) : "";
  }

  function collect(slug) {
    const root = rootOf(slug);
    const val = (sel) => root.querySelector(sel).value;
    return {slug,
      answers: [...root.querySelectorAll("textarea.q")].map((t) => ({question: t.dataset.question, answer: t.value})),
      fields: {type: val(".f-type"), goal: val(".f-goal"), success: val(".f-success"), cadence: val(".f-cadence")},
      audience: [...root.querySelectorAll("input[data-who]:checked")].map((i) => i.dataset.who)};
  }

  function setResult(slug, text, kind) {
    const el = rootOf(slug)?.querySelector(".d-actions .res");
    if (!el) return;
    el.textContent = text; el.className = `res ${kind || ""}`;
  }

  async function saveRow(slug) {
    setResult(slug, "Zapisuję...");
    const out = await post(UPDATE_URL, collect(slug));
    setResult(slug, out.ok ? `Zapisano ${clock()}` : `Błąd: ${out.error}`, out.ok ? "ok" : "err");
    return out.ok;
  }

  async function saveOne(slug) { await saveRow(slug); }

  async function approve(slugs) {
    if (!slugs.length) { $("ov-msg").textContent = "Nic nie zaznaczono."; return; }
    const saved = [];
    for (const slug of slugs) if (await saveRow(slug)) saved.push(slug);
    if (!saved.length) { $("ov-msg").textContent = "Nic nie zatwierdzono: popraw błędy przy wierszach."; return; }
    const audience = Object.fromEntries(saved.map((s) => [s, ["me", ...collect(s).audience]]));
    const out = await post(APPROVE_URL, {slugs: saved, audience});
    if (!out.ok) { saved.forEach((s) => setResult(s, `Błąd zatwierdzenia: ${out.error}`, "err")); $("ov-msg").textContent = `Błąd: ${out.error}`; return; }
    out.body.approved.forEach((s) => setResult(s, `Zatwierdzono ${clock()}`, "ok"));
    $("ov-msg").textContent = `Zatwierdzono: ${out.body.approved.length}` + (saved.length < slugs.length ? `, błędy: ${slugs.length - saved.length}` : "");
    await load();
  }

  /* Reconcile instead of rebuild: drop rows that are no longer drafts, add new ones, never touch rows being edited. */
  function update(list) {
    const list_el = $("ov-list");
    const wanted = [...list].sort((a, b) => unansweredCount(b) - unansweredCount(a));
    const slugs = new Set(wanted.map((c) => c.slug));
    list_el.querySelectorAll(".draft").forEach((r) => { if (!slugs.has(r.dataset.slug)) r.remove(); });
    const have = new Set([...list_el.querySelectorAll(".draft")].map((r) => r.dataset.slug));
    for (const c of wanted) if (!have.has(c.slug)) list_el.append(row(c));
  }

  $("charters-open").addEventListener("click", () => { $("overlay").hidden = false; $("ov-msg").textContent = ""; });
  $("ov-close").addEventListener("click", () => { $("overlay").hidden = true; });
  $("ov-bulk").addEventListener("click", () => approve([...document.querySelectorAll(".inc:checked")].map((i) => i.dataset.slug)));
  return {update};
})();
window.WallReview = WallReview;

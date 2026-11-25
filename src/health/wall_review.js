/* Operator Wall: charter review overlay (approve one / approve checked). Same-origin POST with the CSRF token. */
const WallReview = (() => {
  const APPROVE_URL = "/api/mc/charters/approve";
  let drafts = [];
  const $ = (id) => document.getElementById(id);
  const csrf = () => document.querySelector('meta[name="jit-hub-csrf"]')?.content || "";

  function field(label, value) {
    const dd = h("dd", {});
    if (value instanceof Node) dd.append(value);
    else if (Array.isArray(value)) dd.append(h("ul", {}, value.map((v) => h("li", {}, typeof v === "string" ? v : `${v.who}: ${v.why || ""}`))));
    else dd.append(typeof value === "string" ? value : "brak");
    return [h("dt", {}, label), dd];
  }

  function row(c) {
    const picks = (c.audience_candidates || []).map((cand) => h("label", {},
      h("input", {type: "checkbox", "data-who": cand.who, "aria-label": `Odbiorca ${cand.who}`}), cand.who));
    const include = h("input", {type: "checkbox", class: "inc", "data-slug": c.slug, "aria-label": `Zaznacz ${c.slug}`});
    const one = h("button", {type: "button", class: "btn primary"}, "Zatwierdź");
    one.addEventListener("click", () => approve([c.slug]));
    const who = picks.length ? h("div", {class: "who"}, picks) : "tylko ja";
    return h("div", {class: "draft", "data-slug": c.slug}, include,
      h("dl", {}, field("Projekt", c.slug), field("Typ", c.type), field("Cel", c.goal), field("Sukces", c.success),
        field("Odbiorcy (oprócz mnie)", who), field("Dowody", c.evidence), field("Pytania", c.questions)), one);
  }

  function audienceFor(slug) {
    const root = document.querySelector(`.draft[data-slug="${CSS.escape(slug)}"]`);
    const chosen = [...root.querySelectorAll("input[data-who]:checked")].map((i) => i.dataset.who);
    return ["me", ...chosen];
  }

  async function approve(slugs) {
    if (!slugs.length) { $("ov-msg").textContent = "Nic nie zaznaczono."; return; }
    const audience = Object.fromEntries(slugs.map((s) => [s, audienceFor(s)]));
    const res = await fetch(APPROVE_URL, {method: "POST", headers: {"Content-Type": "application/json", "X-Jit-Hub-Csrf": csrf()},
      body: JSON.stringify({slugs, audience})});
    const body = await res.json();
    $("ov-msg").textContent = res.ok ? `Zatwierdzono: ${body.approved.length}` : `Błąd: ${body.error}`;
    if (res.ok) await load();
  }

  function update(list) {
    drafts = list;
    $("ov-list").replaceChildren(...drafts.map(row));
  }

  $("charters-open").addEventListener("click", () => { $("overlay").hidden = false; $("ov-msg").textContent = ""; });
  $("ov-close").addEventListener("click", () => { $("overlay").hidden = true; });
  $("ov-bulk").addEventListener("click", () => approve([...document.querySelectorAll(".inc:checked")].map((i) => i.dataset.slug)));
  return {update};
})();
window.WallReview = WallReview;

/* Operator Wall insights: one plain-Polish sentence per tile, computed only from the numbers in the payload (no model, no guessing). */
const DAY_S = 86400;
const HOUR_S = 3600;

function plural(n, one, few, many) {
  if (n === 1) return one;
  const last = n % 10, tens = n % 100;
  return last >= 2 && last <= 4 && (tens < 10 || tens >= 20) ? few : many;
}

function span(seconds) {
  const days = Math.floor(seconds / DAY_S);
  if (days >= 1) return `${days} ${plural(days, "dzień", "dni", "dni")}`;
  const hours = Math.max(1, Math.round(seconds / HOUR_S));
  return `${hours} ${plural(hours, "godzinę", "godziny", "godzin")}`;
}

const sessions = (n) => `${n} ${plural(n, "sesja", "sesje", "sesji")}`;

function projectInsight(p, now, topReview) {
  const waiting = p.review_count
    ? `${p.review_count} ${plural(p.review_count, "sesja czeka", "sesje czekają", "sesji czeka")} na przegląd od ${span(now - p.oldest_review)}` : "";
  if (p.autocheck && p.autocheck !== "ok") return `Przepływy: ${FLOW_LABEL[p.autocheck] || "do sprawdzenia"}${waiting ? `; ${waiting}` : ""}.`;
  if (waiting) return `${waiting}${topReview ? ": tu tracisz najwięcej" : ""}.`;
  if (p.blockers) return `${p.blockers} ${plural(p.blockers, "zablokowana karta", "zablokowane karty", "zablokowanych kart")}, zmiana ${span(now - p.last_activity)} temu.`;
  if (p.charter && p.charter.status === "draft") return "Charter czeka na zatwierdzenie.";
  if (p.charter_known && !p.charter) return "Brak chartera: cel i sukces niezdefiniowane.";
  return `Bez zmian od ${span(now - p.last_activity)}, nic nie wymaga Ciebie.`;
}

function machineInsights(m, now) {
  const s = m.sessions;
  const out = {};
  if (s) {
    const running = Object.entries(m.running_by_node || {}).filter(([, n]) => n > 0).map(([node, n]) => `${node || "?"}: ${n}`).join(", ");
    out.running = s.running ? `Działa ${sessions(s.running)}${running ? ` (${running})` : ""}.` : "Żadna sesja nie działa teraz.";
    out.review = s.review && m.oldest_review ? `Najstarsza czeka od ${span(now - m.oldest_review)}.` : "Kolejka przeglądu jest pusta.";
    const bad = s.failed + s.lost;
    out.failed = bad ? `${s.failed} nieudanych i ${s.lost} zgubionych: do sprawdzenia.` : "Brak nieudanych sesji.";
  }
  out.cron = m.cron_failed_24h === null ? "Brak danych z crona." : m.cron_failed_24h ? `${m.cron_failed_24h} ${plural(m.cron_failed_24h, "cron", "crony", "cronów")} z błędem w ostatniej dobie.` : "Żaden cron nie miał błędu w ostatniej dobie.";
  out.cards = m.blocked_cards === null ? "Brak danych z kanbana." : m.blocked_cards ? `${m.blocked_cards} ${plural(m.blocked_cards, "karta czeka", "karty czekają", "kart czeka")} na odblokowanie.` : "Nic nie jest zablokowane.";
  return out;
}

function nodeInsight(n, m) {
  const count = (m.running_by_node || {})[n.name] || 0;
  if (!n.online) return n.detail ? `Offline: ${n.detail}.` : "Offline: nie odpowiada.";
  return count ? `Online, ${sessions(count)} w toku.` : "Online, bez sesji w toku.";
}

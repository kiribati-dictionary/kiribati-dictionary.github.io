// Site script, loaded on every page:
// - search: the big box on the home page, and the header box (with a drop-down) everywhere else
// - the back button
// - offline: registers the service worker, and fills in offline.html when it stands in for a page
//
// Search data is fetched on first use: headwords.json first (Kiribati results show as soon as
// it arrives), then english.json; fulltext.json only when someone asks to search the full
// text of every definition.

const ROOT = new URL("./", document.currentScript.src);
const at = path => new URL(path, ROOT).href;
const LIMIT = 30;

// ---------- data

const data = {};  // headwords, then english and byEnglish once english.json is in
let headwordsLoaded = null;
let englishLoaded = null;
let fulltext = null;

// resolves when headwords are in; starts fetching the English index too
function load() {
  headwordsLoaded ??= fetch(at("headwords.json")).then(r => r.json()).then(hw => {
    data.headwords = hw.map(([id, word, forms, gloss]) => ({ id, word, gloss, keys: [key(word), ...forms] }));
    return data;
  });
  englishLoaded ??= fetch(at("english.json")).then(r => r.json()).then(en => {
    // entries: [[headword index, the definition line that uses the English word], ...], best first
    data.english = en.map(([word, slug, entries]) => ({ word, slug, entries, k: word.toLowerCase() }));
    data.byEnglish = new Map(data.english.map(x => [x.k, x]));
    return data;
  });
  return headwordsLoaded;
}

// once the English index arrives, redraw if the query hasn't changed
function whenEnglish(input, q, redraw) {
  if (!data.english) englishLoaded.then(() => { if (input.value.trim() === q) redraw(); });
}

function loadFulltext() {
  fulltext ??= fetch(at("fulltext.json")).then(r => r.json());
  return fulltext;
}

function key(s) {
  return s.toLowerCase().replace(/æ/g, "ae").normalize("NFKD")
    .replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/g, "");
}

function esc(s) {
  return s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// ---------- search

// Kiribati: exact, then starts-with, then contains, against the headword and other spellings.
function searchKiribati(d, q) {
  const k = key(q);
  if (!k) return [];
  const hits = [];
  d.headwords.forEach((h, i) => {
    let rank = 9;
    for (const hk of h.keys) {
      if (hk === k) rank = 0;
      else if (hk.startsWith(k)) rank = Math.min(rank, 1);
      else if (k.length > 2 && hk.includes(k)) rank = Math.min(rank, 2);
    }
    if (rank < 9) hits.push({ i, rank, len: h.keys[0].length });
  });
  hits.sort((a, b) => a.rank - b.rank || a.len - b.len || a.i - b.i);
  return hits.map(h => h.i);
}

// English, from Trussel's index: the exact word (or its singular), and other words starting with it.
function searchEnglish(d, q) {
  const k = q.toLowerCase().trim().replace(/\s+/g, " ");
  if (!k || !d.english) return { exact: null, others: [] };
  const exact = d.byEnglish.get(k) || (k.endsWith("s") && d.byEnglish.get(k.slice(0, -1))) || null;
  const others = d.english.filter(x => x !== exact && x.k.startsWith(k))
    .sort((a, b) => a.k.length - b.k.length || b.entries.length - a.entries.length).slice(0, 12);
  return { exact, others };
}

// Full text: whole words anywhere in an entry.
function searchFulltext(texts, q, exclude) {
  const words = q.toLowerCase().match(/[\p{L}\p{N}']+/gu);
  if (!words) return [];
  const res = words.map(w => new RegExp(`(^|[^\\p{L}])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^\\p{L}])`, "u"));
  const hits = [];
  texts.forEach((t, i) => { if (!exclude.has(i) && res.every(re => re.test(t))) hits.push(i); });
  return hits;
}

// rows: headword indexes, or [index, text to show instead of the gloss]
function list(d, rows, limit) {
  const items = rows.slice(0, limit).map(row => {
    const [i, text] = Array.isArray(row) ? row : [row, null];
    const h = d.headwords[i];
    return `<li><a href="${at(`word/${h.id}/`)}" lang="gil">${esc(h.word)}</a> <span class="gloss">${esc(text ?? h.gloss)}</span></li>`;
  }).join("");
  return `<ul class="wordlist">${items}</ul>`;
}

function render(d, q, compact) {
  const limit = compact ? 6 : LIMIT;
  const kir = searchKiribati(d, q);
  const { exact, others } = searchEnglish(d, q);
  const parts = [];

  let kirHtml = "";
  if (kir.length) {
    kirHtml = `<h2 class="results-title">Kiribati words</h2>${list(d, kir, limit)}`;
    if (kir.length > limit) kirHtml += `<p class="more">${limit} of ${kir.length.toLocaleString()} shown. Type more to narrow it down.</p>`;
  }

  let enHtml = "";
  if (exact) {
    const n = exact.entries.length;
    enHtml = `<h2 class="results-title">English “${esc(exact.word)}”</h2>${list(d, exact.entries, limit)}`
      + `<p class="more"><a href="${at(`en/${exact.slug}/`)}">${n > limit ? `All ${n} Kiribati words` : "Kiribati words"} for “${esc(exact.word)}”, with definitions →</a></p>`;
  }
  if (others.length) {
    enHtml += `<p class="also"><span>${exact ? "Related English words" : "English words"}:</span> `
      + others.map(x => `<a href="${at(`en/${x.slug}/`)}">${esc(x.word)}</a>`).join(" · ") + `</p>`;
  }

  // show English first when the query is an English word and not also a Kiribati headword
  const kirExact = kir.length && d.headwords[kir[0]].keys[0] === key(q);
  if (exact && !kirExact) parts.push(enHtml, kirHtml); else parts.push(kirHtml, enHtml);

  const shown = new Set([...kir.slice(0, limit), ...(exact ? exact.entries.slice(0, limit).map(([i]) => i) : [])]);
  let html = parts.join("");
  if (!d.english) html += `<p class="more">Loading English words…</p>`;
  else if (!html) html = `<p class="none">No Kiribati or English word matches “${esc(q)}”.</p>`;
  if (compact) {
    html += `<p class="more"><a href="${at(`?q=${encodeURIComponent(q)}`)}">Search everything for “${esc(q)}” →</a></p>`;
  } else {
    html += `<div class="fulltext"><button type="button" class="link-button" data-fulltext>Search the full text of every definition for “${esc(q)}”</button></div>`;
    if (!kirExact) html += `<p class="more">Know a Kiribati word that's missing? <a href="${at(`add/?word=${encodeURIComponent(exact ? "" : q)}`)}">Add it to the dictionary →</a></p>`;
  }
  return { html, shown };
}

// ---------- home page: big search box with results below

function homeSearch(input, out) {
  let last = null;
  async function run() {
    const q = input.value.trim();
    const url = new URL(location);
    q ? url.searchParams.set("q", q) : url.searchParams.delete("q");
    history.replaceState(null, "", url);
    if (!q) { out.innerHTML = ""; return; }
    const d = await load();
    if (input.value.trim() !== q) return;
    last = render(d, q, false);
    out.innerHTML = last.html;
    whenEnglish(input, q, run);
  }
  out.addEventListener("click", async ev => {
    const btn = ev.target.closest("[data-fulltext]");
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = "Searching…";
    const q = input.value.trim();
    const [d, texts] = await Promise.all([load(), loadFulltext()]);
    const hits = searchFulltext(texts, q, last.shown);
    btn.parentElement.innerHTML = hits.length
      ? `<h2 class="results-title">Mentioned in definitions</h2>${list(d, hits, 200)}`
        + (hits.length > 200 ? `<p class="more">200 of ${hits.length.toLocaleString()} shown.</p>` : "")
      : `<p class="none">“${esc(q)}” doesn't appear in any other definition.</p>`;
  });
  let timer;
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 120); });
  input.form.addEventListener("submit", ev => { ev.preventDefault(); run(); });
  input.addEventListener("focus", load, { once: true });
  const initial = new URLSearchParams(location.search).get("q");
  if (initial) { input.value = initial; run(); }
}

// ---------- header search on every other page: a drop-down of the best matches

function headerSearch(input, panel) {
  async function run() {
    const q = input.value.trim();
    if (!q) { panel.hidden = true; return; }
    const d = await load();
    if (input.value.trim() !== q) return;
    panel.innerHTML = `<div class="top-results-inner">${render(d, q, true).html}</div>`;
    panel.hidden = false;
    whenEnglish(input, q, run);
  }
  let timer;
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 120); });
  input.addEventListener("focus", () => { load(); if (input.value.trim()) run(); });
  input.addEventListener("keydown", ev => {
    if (ev.key === "Escape") { panel.hidden = true; input.blur(); }
    if (ev.key === "ArrowDown") { const a = panel.querySelector("a"); if (a) { ev.preventDefault(); a.focus(); } }
  });
  panel.addEventListener("keydown", ev => {
    const links = [...panel.querySelectorAll("a")];
    const i = links.indexOf(document.activeElement);
    if (ev.key === "ArrowDown" && i < links.length - 1) { ev.preventDefault(); links[i + 1].focus(); }
    if (ev.key === "ArrowUp") { ev.preventDefault(); i > 0 ? links[i - 1].focus() : input.focus(); }
    if (ev.key === "Escape") { panel.hidden = true; input.focus(); }
  });
  document.addEventListener("click", ev => {
    if (!panel.contains(ev.target) && ev.target !== input) panel.hidden = true;
  });
}

// ---------- back button: go back if we came from this site, otherwise to the home page

function backButton(a) {
  a.addEventListener("click", ev => {
    let internal = false;
    try { internal = document.referrer && new URL(document.referrer).origin === location.origin; } catch {}
    if (internal && history.length > 1) { ev.preventDefault(); history.back(); }
  });
}

// ---------- offline: offline.html standing in for a page that isn't cached

async function offlinePage(holder) {
  const main = document.getElementById("main");
  const path = decodeURIComponent(location.pathname.slice(new URL(ROOT).pathname.length));
  let m;
  try {
    if ((m = path.match(/^word\/([^/]+)\/?$/))) {
      const bundle = await (await fetch(at(`bundle/${m[1][0]}.json`))).json();
      const entry = bundle[m[1]];
      if (entry) {
        document.title = `${entry[0]} — Kiribati–English Dictionary`;
        main.innerHTML = entry[1];
        return;
      }
    } else if ((m = path.match(/^en\/([^/]+)\/?$/))) {
      await load();
      const d = await englishLoaded;
      const item = d.english.find(x => x.slug === m[1]);
      if (item) {
        document.title = `${item.word} in Kiribati — Kiribati–English Dictionary`;
        main.innerHTML = `<p class="crumbs"><a href="${at("english/")}">English index</a></p>`
          + `<h1 class="headword">${esc(item.word)}</h1>`
          + `<p class="count">${item.entries.length} Kiribati words</p>${list(d, item.entries, 1000)}`;
        return;
      }
    }
  } catch {}
  holder.innerHTML = `You're offline, and this page hasn't been saved yet. <a href="${at("")}">Search the dictionary</a>.`;
}

// ---------- correction form: drawn when "Suggest a correction" is opened, sent by Web3Forms.
// Without a key (see CORRECTIONS_KEY in build_site.py) entries just show the GitHub link.
// Offline, a suggestion is kept in this browser and sent when the connection is back.

const FORM_KEY = document.querySelector('meta[name="corrections-key"]')?.content;
const QUEUE = "kd-corrections";
const SOURCE_NAMES = { "bingham": "Bingham", "sabatier": "Sabatier", "goo-banner": "Goo & Banner", "luomala": "Luomala", "community": "Community" };

function correctionForm(details) {
  const { entry, headword, sources } = details.dataset;
  const options = [...sources.split(",").map(s => SOURCE_NAMES[s] || s), "The page itself (layout, links, search)", "Not sure"]
    .map(o => `<option>${esc(o)}</option>`).join("");
  const form = document.createElement("form");
  form.className = "correct-form";
  form.innerHTML = `
    <p class="hint">Tell us what's wrong with <b lang="gil">${esc(headword)}</b>. No account needed.</p>
    <label><span class="t">Which source?</span><select name="source">${options}</select></label>
    <label><span class="t">What kind of mistake?</span><select name="kind">
      <option>The site doesn't match the original dictionary</option>
      <option>The original dictionary is wrong or out of date</option>
      <option>Something else</option></select></label>
    <label><span class="t">What's wrong?</span><textarea name="problem" rows="3" required></textarea></label>
    <label><span class="t">Suggested correction <span>(optional)</span></span><textarea name="suggestion" rows="2"></textarea></label>
    <label><span class="t">Your name <span>(optional)</span></span><input name="name" autocomplete="name"></label>
    <label class="check"><input type="checkbox" name="credit"> Credit me by name on the About page</label>
    <label><span class="t">Your email <span>(optional, only used to ask about your suggestion)</span></span><input type="email" name="email" autocomplete="email"></label>
    <input type="checkbox" name="botcheck" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">
    <button type="submit">Send suggestion</button>
    <p class="status" role="status"></p>`;
  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = new FormData(form);
    const status = form.querySelector(".status");
    if (f.get("botcheck")) { form.innerHTML = `<p class="status">Thank you!</p>`; return; }
    const message = {
      access_key: FORM_KEY,
      subject: `Correction: ${headword}`,
      from_name: f.get("name") || "Dictionary visitor",
      entry, headword,
      page: at(`word/${entry}/`),
      source: f.get("source"), kind: f.get("kind"),
      problem: f.get("problem"), suggestion: f.get("suggestion"),
      name: f.get("name"), credit: f.get("credit") ? "Yes, credit me by name" : "No",
      email: f.get("email"),
    };
    form.querySelector("button").disabled = true;
    status.textContent = "Sending…";
    const result = await send(message);
    if (result === "sent") {
      form.innerHTML = `<p class="status">Thank you! Your suggestion was sent and will be checked against the original sources.</p>`;
    } else if (result === "offline") {
      form.innerHTML = `<p class="status">You're offline, so your suggestion is saved on this device. It will be sent automatically when you're back online.</p>`;
    } else if (result === "retry") {
      form.innerHTML = `<p class="status">Your suggestion couldn't be sent just now, so it's saved on this device. It will be sent automatically the next time you visit the dictionary.</p>`;
    } else {
      form.querySelector("button").disabled = false;
      status.innerHTML = `Sorry, that didn't go through. Please try again, or <a href="${details.querySelector(".correct-github a").href}">report it on GitHub</a>.`;
    }
  });
  details.insertBefore(form, details.querySelector(".correct-github"));
}

// true if Web3Forms accepted it; throws if there's no connection.
// Sent as form data rather than JSON: that needs no CORS preflight, which Web3Forms' bot filter can block.
async function post(message) {
  const body = new FormData();
  for (const [k, v] of Object.entries(message)) if (v) body.append(k, v);
  const res = await fetch("https://api.web3forms.com/submit", { method: "POST", headers: { Accept: "application/json" }, body });
  return (await res.json()).success === true;
}

// "sent", "offline" or "retry" (kept to send later), or "failed"
async function send(message) {
  if (!navigator.onLine) return queue(message) && "offline";
  try {
    return (await post(message)) ? "sent" : "failed";
  } catch {
    return queue(message) && "retry";  // couldn't reach Web3Forms (no connection, or it's refusing for now)
  }
}

// true if kept for later
function queue(message) {
  try {
    const waiting = JSON.parse(localStorage.getItem(QUEUE) || "[]");
    waiting.push(message);
    localStorage.setItem(QUEUE, JSON.stringify(waiting));
    return true;
  } catch {
    return false;
  }
}

async function flushQueue() {
  let waiting;
  try { waiting = JSON.parse(localStorage.getItem(QUEUE) || "[]"); } catch { return; }
  if (!waiting.length || !navigator.onLine) return;
  const left = [];
  for (const message of waiting) {
    try {
      await post(message);  // a rejected message won't succeed later either, so it isn't kept
    } catch {
      left.push(message);
    }
  }
  try { left.length ? localStorage.setItem(QUEUE, JSON.stringify(left)) : localStorage.removeItem(QUEUE); } catch {}
}

if (FORM_KEY) {
  // toggle doesn't bubble, so listen while it travels down; covers entries drawn offline too
  document.addEventListener("toggle", ev => {
    const d = ev.target;
    if (d.matches?.("details.correct") && d.open && !d.querySelector("form")) correctionForm(d);
  }, true);
}
flushQueue();
addEventListener("online", flushQueue);

// ---------- plain forms sent to the dictionary's inbox: "Add a word" and the About page's
// ideas form. They work without JavaScript (Web3Forms then shows the thanks/ page); here they're
// sent in place, and kept for later when offline. The form says what it is:
//   data-thing="word"        used in the messages ("Your word was sent")
//   data-subject="New word"  email subject; ": <word>" is added when the form has a word field
//   data-sent="..."          extra sentence after "Thank you!"
// Links like add/?word=kai&slang=1 fill in the Add-a-word form.

function messageForm(form) {
  const { thing, subject, sent } = form.dataset;
  const params = new URLSearchParams(location.search);
  if (form.elements.word && params.get("word")) form.elements.word.value = params.get("word");
  if (form.elements.slang && params.get("slang")) form.elements.slang.checked = true;
  const original = form.innerHTML;
  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = new FormData(form);
    if (f.get("botcheck")) { form.innerHTML = `<p class="status">Thank you!</p>`; return; }
    const message = Object.fromEntries(f);
    delete message.redirect;
    message.subject = f.get("word") ? `${subject}: ${f.get("word")}` : subject;
    message.from_name = f.get("name") || "Dictionary visitor";
    const status = form.querySelector(".status");
    form.querySelector("button").disabled = true;
    status.textContent = "Sending…";
    const result = await send(message);
    const done = {
      sent: `Thank you! Your ${thing} was sent. ${sent}`,
      offline: `You're offline, so your ${thing} is saved on this device. It will be sent automatically when you're back online.`,
      retry: `Your ${thing} couldn't be sent just now, so it's saved on this device. It will be sent automatically the next time you visit the dictionary.`,
    }[result];
    if (done) {
      form.innerHTML = `<p class="status">${done}</p><p><button type="button" class="link-button" data-again>Send another ${thing}</button></p>`;
      form.querySelector("[data-again]").addEventListener("click", () => { form.innerHTML = original; });
    } else {
      form.querySelector("button").disabled = false;
      status.textContent = "Sorry, that didn't go through. Please try again.";
    }
  });
}

// ---------- day / night: the button flips between light and dark; the choice is remembered

function themeToggle(button) {
  const root = document.documentElement;
  const dark = () => root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const label = () => button.setAttribute("aria-label", dark() ? "Switch to day mode" : "Switch to night mode");
  label();
  button.addEventListener("click", () => {
    root.dataset.theme = dark() ? "light" : "dark";
    try { localStorage.setItem("kd-theme", root.dataset.theme); } catch {}
    label();
  });
}

// ---------- start

const homeInput = document.getElementById("q");
if (homeInput) homeSearch(homeInput, document.getElementById("results"));

const topInput = document.querySelector(".top-search input");
if (topInput) headerSearch(topInput, document.getElementById("top-results"));

document.querySelectorAll("[data-back]").forEach(backButton);
document.querySelectorAll("[data-theme-toggle]").forEach(themeToggle);
document.querySelectorAll("[data-message-form]").forEach(messageForm);

const offline = document.querySelector("[data-offline]");
if (offline) offlinePage(offline);

if ("serviceWorker" in navigator && location.protocol !== "file:") {
  navigator.serviceWorker.register(at("sw.js")).catch(() => {});
}

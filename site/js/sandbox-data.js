// The world engine's sandbox, read for the site: the Codex (/codex/?world=sandbox), the 3D island's
// character panel (/world/?world=sandbox) and anything else that shows the sandbox.
//
// READ-ONLY. Everything comes from the sandbox_* tables in Supabase with the publishable key, which may only
// read them; the engine (world/publish.py) is the only writer. Nothing private is ever in these tables:
// no private memories, no sealed facts, no sealed events, and the absent have no place.
//
//   const W = await loadWorld();          // every table, plus indexes and helpers
//   W.person(12), W.house(3), W.family(12), W.actionsOf(12), W.crest(house), W.portraitUrl(person) ...

export const SUPABASE_URL = "https://dbrtvwhslxkdpmuawrgd.supabase.co";
export const SUPABASE_KEY = "sb_publishable_NVNYh69hEq2uJKfWOvlAkg_9RCInRey";
export const STORAGE = `${SUPABASE_URL}/storage/v1/object/public/arcadia/`;

export async function table(name, query = "select=*") {
  const out = [];
  for (let from = 0; ; from += 1000) {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/${name}?${query}`, {
      headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}`, Range: `${from}-${from + 999}` } });
    if (!r.ok) throw new Error(`${name}: ${r.status}`);
    const page = await r.json();
    out.push(...page);
    if (page.length < 1000) return out;
  }
}

export const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const SEASONS = ["spring", "summer", "autumn", "winter"];
const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : "");

export async function loadWorld() {
  const names = ["sandbox_world", "sandbox_houses", "sandbox_people", "sandbox_places", "sandbox_events", "sandbox_beliefs",
                 "sandbox_dreams", "sandbox_house_clients", "sandbox_house_feelings", "sandbox_lineage", "sandbox_relationships",
                 "sandbox_legends", "sandbox_symbols", "sandbox_chronicles", "sandbox_previews"];
  const queries = { sandbox_events: "select=*&order=id", sandbox_beliefs: "select=*&order=id", sandbox_dreams: "select=*&order=id",
                    sandbox_house_clients: "select=*&order=id", sandbox_chronicles: "select=*&order=id", sandbox_previews: "select=*&order=id" };
  const got = await Promise.all(names.map(n => table(n, queries[n]).catch(() => [])));
  const T = Object.fromEntries(names.map((n, i) => [n.replace("sandbox_", ""), got[i]]));
  return makeWorld(T);
}

export function makeWorld(T) {
  const W = { ...T, now: T.world[0] || { year: 0, season: "winter", tick: 0 } };
  const by = (list, key) => new Map(list.map(x => [x[key], x]));
  const group = (list, key) => { const m = new Map(); for (const x of list) { const k = x[key]; if (!m.has(k)) m.set(k, []); m.get(k).push(x); } return m; };
  const P = by(T.people, "id"), H = by(T.houses, "id"), PL = by(T.places, "id");
  const beliefsOf = group(T.beliefs, "holder_id"), dreamsOf = group(T.dreams, "dreamer_id");
  const previewOf = new Map(T.previews.filter(p => p.image && p.status === "done").map(p => [p.dream_id, p]));
  const flight = T.events.find(e => e.kind === "departure");

  W.person = id => P.get(Number(id));
  W.house = id => H.get(Number(id));
  W.place = id => PL.get(Number(id));
  W.flight = flight;
  W.age = p => (p && p.born_year != null ? W.now.year - p.born_year : null);
  W.membersOf = hid => T.people.filter(p => p.house_id === Number(hid));
  W.houseColor = hid => H.get(hid)?.color || "#c9b48a";
  W.portraitUrl = p => (p?.portrait ? STORAGE + p.portrait : null);
  W.codexLink = p => `/codex/?world=sandbox#p${p.id}`;
  W.houseLink = h => `/codex/?world=sandbox#h${h.id}`;

  // family: parents and children (lineage), spouses and other public ties (relationships)
  W.parents = id => T.lineage.filter(l => l.child_id === id).map(l => ({ p: P.get(l.parent_id), kind: l.kind })).filter(x => x.p);
  W.children = id => T.lineage.filter(l => l.parent_id === id).map(l => ({ p: P.get(l.child_id), kind: l.kind })).filter(x => x.p);
  W.ties = id => T.relationships.filter(r => r.person_a === id || r.person_b === id)
    .map(r => ({ p: P.get(r.person_a === id ? r.person_b : r.person_a), kind: r.kind, strength: r.strength })).filter(x => x.p);
  W.family = id => ({ parents: W.parents(id), children: W.children(id), ties: W.ties(id) });
  // a patron, for those who serve a house (retainers and servants): its head
  W.patron = p => (p && ["retainer", "servant"].includes(p.role) ? P.get(H.get(p.house_id)?.head_id) : null);

  W.actionsOf = id => T.events.filter(e => (e.actors || []).includes(id)).slice().reverse();
  W.eventsAt = pid => T.events.filter(e => e.place_id === pid).slice().reverse();
  W.peopleAt = pid => T.people.filter(p => p.place_id === pid && !p.absent);
  W.beliefsOf = id => (beliefsOf.get(id) || []).slice().sort((a, b) => b.confidence - a.confidence);
  W.flightBeliefsOf = id => W.beliefsOf(id).filter(b => flight && b.subject_type === "event" && String(b.subject_id) === String(flight.id));
  W.dreamsOf = id => (dreamsOf.get(id) || []).slice().reverse();
  W.paintingOf = d => { const pv = previewOf.get(d.id); return pv ? STORAGE + pv.image : null; };
  W.dream = id => T.dreams.find(d => d.id === id);
  W.clientsOf = hid => T.house_clients.filter(c => c.house_id === hid).at(-1) || null;
  W.feelingsOf = hid => T.house_feelings.filter(f => f.from_house === hid);
  W.when = x => `${cap(x.season)}, year ${x.year}`;
  W.nowLabel = () => `${cap(W.now.season)}, year ${W.now.year}`;
  W.seasonOrder = s => SEASONS.indexOf(s);
  W.personName = id => P.get(id)?.name || "someone";

  // a crest (placeholder): a shield in the house's colour with its initial and a band by its kind of land
  W.crest = (h, size = 44) => {
    if (!h) return "";
    const band = { city: "M8 18h32v6H8z", ships: "M8 30q16 8 32 0v4q-16 8-32 0z", groves: "M24 10v30M16 20q8-6 8 4M32 20q-8-6-8 4",
                   temple: "M12 16h24M14 18v16M20 18v16M28 18v16M34 18v16", trade: "M10 24h28M24 12v24", quarries: "M10 34l14-20 14 20z",
                   law: "M12 20h24M24 12v24M14 20l-4 8h8zM34 20l-4 8h8z", healing: "M24 12v24M16 24h16", herds: "M8 36l12-18 6 8 6-6 8 16z",
                   faded: "M24 14q8 8 0 22q-8-14 0-22z" }[h.land_kind] || "M8 24h32";
    return `<svg width="${size}" height="${Math.round(size * 1.17)}" viewBox="0 0 48 56" aria-label="crest of House ${esc(h.name)}">
      <path d="M4 4h40v22c0 16-10 24-20 28C14 50 4 42 4 26z" fill="${esc(h.color || "#a98")}" stroke="rgba(0,0,0,.45)" stroke-width="2"/>
      <path d="${band}" fill="rgba(0,0,0,.18)" stroke="rgba(0,0,0,.4)" stroke-width="2" stroke-linecap="round"/>
      <text x="24" y="31" text-anchor="middle" font-family="Georgia, serif" font-size="17" font-weight="700" fill="rgba(255,255,255,.92)"
            stroke="rgba(0,0,0,.35)" stroke-width=".6">${esc(h.name[0])}</text></svg>`;
  };
  // a portrait, or a placeholder silhouette in the house's colour
  W.portrait = (p, size = 96) => {
    const url = W.portraitUrl(p);
    if (url) return `<img class="portrait" src="${url}" alt="Portrait of ${esc(p.name)}" width="${size}" height="${Math.round(size * 1.23)}" loading="lazy">`;
    const c = W.houseColor(p?.house_id);
    return `<svg class="portrait" width="${size}" height="${Math.round(size * 1.23)}" viewBox="0 0 80 98" aria-label="no portrait yet">
      <rect width="80" height="98" rx="6" fill="#2b2219"/><circle cx="40" cy="38" r="17" fill="${esc(c)}" opacity=".55"/>
      <path d="M10 98c2-24 14-34 30-34s28 10 30 34z" fill="${esc(c)}" opacity=".55"/></svg>`;
  };
  return W;
}

// One person, in full: portrait, house, family links, patron, recent actions, public beliefs, dream gallery.
// Shared by the Codex entry and the 3D island's character panel (same words, same data).
export function personHtml(W, p, { codexLink = true, maxDreams = 12 } = {}) {
  const h = W.house(p.house_id), place = W.place(p.place_id), age = W.age(p);
  const fam = W.family(p.id), patron = W.patron(p);
  const link = q => `<a href="${W.codexLink(q)}" data-person="${q.id}">${esc(q.name)}</a>`;
  // spouses first, then parents and children; "kin" only for those not already named
  const named = new Set([...fam.parents, ...fam.children].map(x => x.p.id));
  const ties = fam.ties.filter(x => !(x.kind === "kin" && named.has(x.p.id))).sort((a, b) => (a.kind !== "spouse") - (b.kind !== "spouse"));
  const famItems = [
    ...ties.filter(x => x.kind === "spouse").map(x => `spouse: ${link(x.p)}`),
    ...fam.parents.map(x => `${x.kind === "fostered" ? "foster-parent" : "parent"}: ${link(x.p)}`),
    ...fam.children.map(x => `${x.kind === "fostered" ? "fosterling" : "child"}: ${link(x.p)}`),
    ...ties.filter(x => x.kind !== "spouse").map(x => `${esc({ spouse: "spouse", betrothed: "was betrothed to", kin: "kin", friend: "friend", rival: "rival", teacher: "teacher/pupil" }[x.kind] || x.kind)}: ${link(x.p)}`),
  ];
  // what they did (the event's text starts with them: the engine writes the actor first) and what was done to them
  const involved = W.actionsOf(p.id);
  const did = involved.filter(e => e.text.startsWith(p.name)).slice(0, 8);
  const doneTo = involved.filter(e => !e.text.startsWith(p.name)).slice(0, 5);
  const beliefs = W.beliefsOf(p.id).filter(b => b.confidence >= 0.2).slice(0, 8);
  const dreams = W.dreamsOf(p.id).slice(0, maxDreams);
  return `
    <div class="person">
      <div class="person-head">${W.portrait(p, 96)}
        <div><p class="who"><span class="dot" style="background:${esc(h?.color)}"></span>${esc(p.name)}</p>
          <p class="sub">${h ? `<a href="${W.houseLink(h)}">House ${esc(h.name)}</a>` : "no house"}${p.role ? " · " + esc(p.role) : ""}${age != null ? ` · ${age} years` : ""}</p>
          ${p.note ? `<p class="sub"><em>${esc(p.note)}</em></p>` : ""}
          <p class="sub">${p.absent ? "Missing from Corva since the autumn of year 0" : place ? "Now at " + esc(place.name) : ""}</p>
          ${p.proposed ? `<p class="sub"><em>a placeholder character (proposed)</em></p>` : ""}
          ${codexLink ? `<p class="sub"><a href="${W.codexLink(p)}">Codex entry ↗</a></p>` : ""}</div></div>
      ${p.appearance && p.appearance.build ? `<h4>Appearance <small>${p.appearance.status === "proposed" ? "a draft (proposed)" : ""}</small></h4>
        <p class="sub" style="font-size:14px">${esc(["build", "face", "hair", "eyes", "marks", "clothing"].map(k => p.appearance[k]).filter(Boolean).join("; "))}.</p>` : ""}
      ${famItems.length ? `<h4>Family and ties</h4><ul class="links">${famItems.map(x => `<li>${x}</li>`).join("")}</ul>` : ""}
      ${patron ? `<h4>Patron</h4><p>${link(patron)}, head of House ${esc(h?.name)}</p>` : ""}
      <h4>Recent actions</h4>
      ${did.length ? `<ul class="links">${did.map(e => `<li>${esc(e.text)} <small>${esc(W.when(e))}</small></li>`).join("")}</ul>` : `<p class="sub">Nothing they have done is recorded yet.</p>`}
      ${doneTo.length ? `<h4>Done to them</h4><ul class="links">${doneTo.map(e => `<li>${esc(e.text)} <small>${esc(W.when(e))}</small></li>`).join("")}</ul>` : ""}
      <h4>What they believe</h4>
      ${beliefs.length ? beliefs.map(b => `<p class="belief"><span>${Math.round(b.confidence * 100)}%</span>${esc(b.interpretation)}</p>`).join("") : `<p class="sub">Nothing they hold to.</p>`}
      <h4>Dreams <small>${W.dreamsOf(p.id).length} in all</small></h4>
      ${dreams.length ? `<div class="dreams">${dreams.map(d => { const img = W.paintingOf(d);
        return `<figure class="dream-card">${img ? `<img src="${img}" alt="painting of the dream" loading="lazy">` : ""}
          <figcaption><small>${esc(W.when(d))}${d.recalled ? (d.discussed ? ` · told, talked about ${d.discussed}×` : " · remembered") : " · forgotten on waking"}</small>
          <span>${esc(d.retelling || (d.text.length > 260 ? d.text.slice(0, 260) + "…" : d.text))}</span></figcaption></figure>`; }).join("")}</div>`
              : `<p class="sub">No dreams yet.</p>`}
    </div>`;
}

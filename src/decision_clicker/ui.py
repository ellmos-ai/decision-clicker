# SPDX-License-Identifier: MIT
"""HTML-Oberflaeche — bewusst ohne Framework, damit START.bat immer laeuft."""
from __future__ import annotations

import itertools
import re
from html import escape

from .intake import collect_question_blocks

CSS = """
:root{--bg:#f6f7f9;--fg:#1b1f24;--mut:#5b6673;--card:#fff;--line:#dfe3e8;
--acc:#2f6f4f;--acc2:#e8f2ec;--warn:#8a5a00;--warnbg:#fdf3e0}
@media(prefers-color-scheme:dark){:root{--bg:#14171a;--fg:#e8eaed;--mut:#98a2ad;
--card:#1c2025;--line:#2c3238;--acc:#6fbf8f;--acc2:#1d2a23;--warn:#e0b062;--warnbg:#2a2317}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;font:16px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--fg);
min-width:320px;overflow-x:hidden}
header{background:var(--card);border-bottom:1px solid var(--line);padding:.7rem 1.2rem;
display:flex;gap:1.2rem;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:5}
header b{font-size:1.05rem}
nav a{color:var(--fg);text-decoration:none;padding:.3rem .6rem;border-radius:6px}
nav a:hover{background:var(--acc2)}
nav a.on{background:var(--acc);color:#fff}
main{max-width:920px;width:100%;margin:0 auto;padding:1.4rem 1.2rem 4rem;min-width:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:1.1rem 1.3rem;margin-bottom:1rem;max-width:100%;overflow-wrap:anywhere;word-break:break-word;hyphens:auto}
.subcard{background:var(--bg);border:1px solid var(--line);border-radius:8px;
padding:.9rem 1.1rem;margin:.8rem 0;max-width:100%;overflow-wrap:anywhere;word-break:break-word;hyphens:auto}
.subcard h3{font-size:1.02rem;margin:0 0 .55rem;color:var(--fg);overflow-wrap:anywhere;word-break:break-word}
.subcard .submeta{color:var(--mut);font-size:.82rem;margin-bottom:.5rem}
.zahlen{display:flex;gap:.7rem;flex-wrap:wrap;margin-bottom:1.2rem}
.zahl{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:.7rem 1rem;min-width:7.5rem}
.zahl .n{font-size:1.7rem;font-weight:700;display:block;line-height:1.1}
.zahl .l{color:var(--mut);font-size:.8rem}
h1{font-size:1.35rem;margin:.2rem 0 1rem;overflow-wrap:anywhere;word-break:break-word}
h2{font-size:1.1rem;margin:0 0 .6rem;overflow-wrap:anywhere;word-break:break-word}
.meta{color:var(--mut);font-size:.85rem;margin-bottom:.9rem;overflow-wrap:anywhere;word-break:break-word}
.kontext{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);
border-radius:8px;padding:.8rem 1rem;font-size:.92rem;max-height:24rem;overflow:auto;
overflow-wrap:anywhere;word-break:break-word;hyphens:auto}
button,.btn{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);
border-radius:8px;padding:.6rem 1rem;cursor:pointer;text-decoration:none;display:inline-block;max-width:100%}
button:hover,.btn:hover{border-color:var(--acc)}
button.wahl{display:block;width:100%;max-width:100%;text-align:left;margin:.45rem 0;padding:.8rem 1rem;
white-space:normal;overflow-wrap:anywhere;word-break:break-word;hyphens:auto;line-height:1.45}
button.wahl:hover{background:var(--acc2);border-color:var(--acc)}
button.wahl b{color:var(--acc)}
button.prim{background:var(--acc);color:#fff;border-color:var(--acc)}
.empf{background:var(--acc2);border-left:4px solid var(--acc);padding:.6rem .9rem;
border-radius:0 8px 8px 0;margin:.9rem 0;max-width:100%;overflow-wrap:anywhere;word-break:break-word;hyphens:auto}
.warn{background:var(--warnbg);border-left:4px solid var(--warn);padding:.6rem .9rem;
border-radius:0 8px 8px 0;margin:.9rem 0;color:var(--warn);max-width:100%;overflow-wrap:anywhere;
word-break:break-word;hyphens:auto}
input,textarea,select{font:inherit;width:100%;max-width:100%;padding:.55rem .7rem;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--fg)}
label{display:block;margin:.8rem 0 .25rem;font-weight:600;font-size:.9rem}
.hint{color:var(--mut);font-size:.82rem;font-weight:400}
.table-wrap{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:.5rem 0}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top;
overflow-wrap:anywhere;word-break:break-word}
th{color:var(--mut);font-weight:600}
.tag{font-size:.72rem;padding:.15rem .5rem;border-radius:99px;background:var(--acc2);
color:var(--acc);white-space:nowrap}
.leer{color:var(--mut);text-align:center;padding:2.5rem 1rem}
code{background:var(--bg);padding:.1rem .35rem;border-radius:4px;font-size:.85em;
overflow-wrap:anywhere;word-break:break-all}
pre code{word-break:normal}
.reihe{display:flex;gap:.6rem;flex-wrap:wrap;margin-top:1rem}
.opt-radio-row{display:flex;align-items:flex-start;gap:.6rem;margin:.4rem 0;padding:.5rem .7rem;
border-radius:6px;background:var(--card);border:1px solid var(--line)}
.opt-radio-row input[type=radio]{width:auto;margin-top:.3rem;flex-shrink:0}
.opt-radio-label{flex:1;cursor:pointer;overflow-wrap:anywhere;word-break:break-word}
"""

# In der Kette existieren beide Schreibweisen nebeneinander:
#   "- A — Text - B — Text"   (Teil 1/2, Liste zu einer Zeile zusammengezogen)
#   "Option A: Text | Option B: Text"  (Teil 3/4)
# Der Trenner ist also entweder Zeilenanfang, "|" oder ein freistehender Strich.
OPTION_RE = re.compile(
    r"(?:^|\|\s*|\s[-–—•]\s)\s*(?:[-–—•]\s*)?(?i:Option\s+)?([A-Z])\s*[:—–-]\s+"
)
RECOMMENDED_RE = re.compile(r"^\[?\s*(?i:Option\s+)?([A-Z])\b")


def parse_options(raw: str) -> list[tuple[str, str]]:
    """`OPTIONEN`-Text in (Buchstabe, Text) zerlegen — tolerant gegen Stile."""
    if not raw:
        return []
    parts: list[tuple[str, str]] = []
    hits = list(OPTION_RE.finditer(raw))
    for number, hit in enumerate(hits):
        end = hits[number + 1].start() if number + 1 < len(hits) else len(raw)
        text = raw[hit.end():end].strip(" |—–-\t")
        parts.append((hit.group(1).upper(), " ".join(text.split())))
    return [(letter, text) for letter, text in parts if text]


def layout(title: str, body: str, active: str = "") -> bytes:
    def link(href: str, label: str, name: str) -> str:
        return f'<a href="{href}" class="{"on" if name == active else ""}">{label}</a>'

    html = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Decision-Clicker</title><style>{CSS}</style></head><body>
<header><b>Decision-Clicker</b><nav>
{link('/', 'Übersicht', 'home')}
{link('/klick', 'Durchklicken', 'klick')}
{link('/verlauf', 'Verlauf', 'verlauf')}
{link('/neu', 'Einstellen', 'neu')}
{link('/register', 'Register', 'register')}
</nav></header><main>{body}</main></body></html>"""
    return html.encode("utf-8")


def numbers(data: dict[str, int]) -> str:
    felder = [
        ("offen", "offen — zu klicken"),
        ("entschieden_offen", "entschieden, Umsetzung offen"),
        ("done", "erledigt"),
        ("archiviert", "archiviert"),
    ]
    zellen = "".join(
        f'<div class="zahl"><span class="n">{data.get(key, 0)}</span>'
        f'<span class="l">{escape(label)}</span></div>'
        for key, label in felder
    )
    return f'<div class="zahlen">{zellen}</div>'


def intake_banner(offene: list[dict], confirmation: str = "") -> str:
    """Postfach-Hinweis mit Übernahme-Knopf — GET schreibt nie von selbst."""
    if not offene:
        return ""
    zeilen = "".join(
        f"<li><code>{escape(e['id'])}</code> — {escape(e['titel'])} "
        f"<span class=\"tag\">→ {escape(e['ziel'])}</span></li>" for e in offene)
    return (f'<div class="card"><h2>Desktop-Postfach: {len(offene)} neue Einträge</h2>'
            "<p>Automationen schreiben weiterhin nach "
            "<code>Desktop\\TO-DECIDE-USER.txt</code>. Die Einträge werden in die Kette "
            "übernommen und dort vermerkt — im Postfach wird nichts gelöscht.</p>"
            f"<ul>{zeilen}</ul>"
            '<form method="post" action="/api/intake">'
            f'<input type="hidden" name="confirmation" value="{escape(confirmation)}">'
            '<div class="reihe">'
            '<button class="prim" type="submit">Jetzt übernehmen</button>'
            "</div></form></div>")


def home(data: dict[str, int], offen: list[dict], hinweis: str = "",
         postfach: list[dict] | None = None, intake_confirmation: str = "") -> bytes:
    kopf = f'<div class="warn">{escape(hinweis)}</div>' if hinweis else ""
    kopf += intake_banner(postfach or [], intake_confirmation)
    if offen:
        zeilen = "".join(
            f'<tr><td><a href="/klick?key={escape(e["key"])}"><code>{escape(e["key"])}</code></a></td>'
            f'<td>{escape(e["title"])}</td>'
            f'<td><span class="tag">{escape(e["scope"])}</span></td></tr>'
            for e in offen
        )
        tabelle = (
            '<div class="table-wrap"><table><tr><th>ID</th><th>Titel</th><th>Geltung</th></tr>'
            f"{zeilen}</table></div>"
            '<div class="reihe"><a class="btn prim" href="/klick">Durchklicken starten</a></div>'
        )
    else:
        tabelle = '<div class="leer">Keine offene Entscheidung. Nichts zu tun.</div>'
    body = (
        f"{kopf}<h1>Übersicht</h1>{numbers(data)}"
        f'<div class="card"><h2>Offene Entscheidungen</h2>{tabelle}</div>'
    )
    return layout("Übersicht", body, "home")


def klick(entry: dict | None, rest: int, hinweis: str = "", confirmation: str = "") -> bytes:
    if entry is None:
        body = (
            "<h1>Durchklicken</h1>"
            '<div class="card"><div class="leer">Alle Entscheidungen sind getroffen.<br>'
            '<a class="btn" href="/" style="margin-top:1rem">Zur Übersicht</a></div></div>'
        )
        return layout("Durchklicken", body, "klick")

    kontext = entry.get("_raw") or entry.get("question") or ""
    warn = f'<div class="warn">{escape(hinweis)}</div>' if hinweis else ""
    empfehlung = (entry.get("recommendation_excerpt") or "").strip()

    # Prüfe auf gebündelte Teilfragen ("eine Kachel = genau eine entscheidbare Frage")
    q_blocks = collect_question_blocks(kontext.splitlines())
    actionable_q = [b for b in q_blocks if b.options]

    if len(actionable_q) > 1:
        # Gebündelter Eintrag: Sub-Kacheln je Frage mit exakter Passung der Optionen
        sub_kacheln = []
        for idx, qb in enumerate(actionable_q, start=1):
            sub_empf = qb.empfehlung or ""
            sub_empf_block = (
                f'<div class="empf" style="margin:.6rem 0"><b>Empfehlung zu {escape(qb.label)}:</b> '
                f'{escape(sub_empf)}</div>' if sub_empf else ""
            )
            opt_rows = "".join(
                f'<div class="opt-radio-row">'
                f'<input type="radio" name="sub_choice_{idx}" id="opt_{idx}_{escape(opt.partition(" — ")[0].strip())}" '
                f'value="{escape(opt.partition(" — ")[0].strip())}">'
                f'<label for="opt_{idx}_{escape(opt.partition(" — ")[0].strip())}" class="opt-radio-label">'
                f'<b>[{escape(opt.partition(" — ")[0].strip())}]</b> — {escape(opt.partition(" — ")[2].strip())}'
                f'</label></div>'
                for opt in qb.options
            )
            sub_kacheln.append(
                f'<div class="subcard"><h3>{escape(qb.label)}: {escape(qb.question)}</h3>'
                f'<div class="submeta">{len(qb.options)} Optionen · Passung zu dieser Einzelfrage</div>'
                f'{opt_rows}{sub_empf_block}</div>'
            )

        parsed_per_q: list[list[tuple[str, str]]] = []
        for qb in actionable_q:
            opts = []
            for opt_str in qb.options:
                b, _, t = opt_str.partition(" — ")
                opts.append((b.strip().upper(), t.strip()))
            parsed_per_q.append(opts)

        kombos: list[str] = []
        if len(parsed_per_q) <= 3 and (len(parsed_per_q[0]) * len(parsed_per_q[1])) <= 16:
            for combo in itertools.product(*parsed_per_q):
                val_parts = [f"({i}) {b}" for i, (b, _) in enumerate(combo, start=1)]
                val = " / ".join(val_parts)
                lbl_parts = [f"({i}) [{b}]" for i, (b, _) in enumerate(combo, start=1)]
                lbl = " + ".join(lbl_parts)
                desc_parts = [
                    f"({i}) {t[:40]}…" if len(t) > 40 else f"({i}) {t}"
                    for i, (_, t) in enumerate(combo, start=1)
                ]
                desc = " · ".join(desc_parts)

                is_empf = True
                for qb, (b, _) in zip(actionable_q, combo, strict=True):
                    if qb.empfehlung:
                        m = RECOMMENDED_RE.match(qb.empfehlung)
                        if m and m.group(1).upper() != b:
                            is_empf = False
                    else:
                        is_empf = False

                kombos.append(
                    f'<button class="wahl" type="submit" name="choice" value="{escape(val)}">'
                    f'<b>{escape(lbl)}</b> — {escape(desc)}'
                    + (' <span class="tag">empfohlen</span>' if is_empf else "")
                    + '</button>'
                )

        knoepfe_html = "".join(kombos)
        js_sync = (
            "<script>"
            "function syncChoice(){"
            f"var n={len(actionable_q)},p=[];"
            "for(var i=1;i<=n;i++){"
            "var sel=document.querySelector('input[name=\"sub_choice_\"+i+\"]:checked');"
            "if(sel)p.push('('+i+') '+sel.value);"
            "}"
            "if(p.length>0)document.getElementById('combo_input').value=p.join(' / ');"
            "}"
            "document.addEventListener('change',function(e){if(e.target&&e.target.name&&e.target.name.startsWith('sub_choice_'))syncChoice();});"
            "</script>"
        )

        form_inhalt = (
            '<h2>Entscheidung (Passung und Auswahl der Items)</h2>'
            '<p class="hint">'
            'Wähle eine Kombination aller Teilfragen oder markiere die Optionen in den Kacheln oben:</p>'
            f'{knoepfe_html}'
            '<div class="reihe" style="margin-top:.8rem">'
            '<label style="width:100%">Kombinierte Auswahl '
            '<span class="hint">(wird per Klick oben befüllt oder frei eingetragen)</span></label>'
            '<input id="combo_input" name="choice" placeholder="z. B. (1) A / (2) B" required>'
            '<button class="prim" type="submit" style="margin-top:.4rem">'
            'Entscheidung für alle Teilfragen eintragen</button>'
            '</div>'
            f'{js_sync}'
        )

        body = f"""{warn}<h1>{escape(entry["title"])}</h1>
<div class="meta"><code>{escape(entry["key"])}</code> · {escape(entry["date"])} ·
Quelle: <code>{escape(entry["source_file"])}</code>, Zeile {entry["source_line"]} ·
noch {rest} offen</div>
<div class="card"><h2>Kontext (gebündelte Vorlage)</h2><div class="kontext">{escape(kontext)}</div></div>
{"".join(sub_kacheln)}
<form method="post" action="/api/decide" class="card">
<input type="hidden" name="key" value="{escape(entry["key"])}">
<input type="hidden" name="confirmation" value="{escape(confirmation)}">
{form_inhalt}
<label>Anmerkung <span class="hint">(optional, wird mit eingetragen)</span></label>
<textarea name="note" rows="2" placeholder="Begründung, Einschränkung, Auflage …"></textarea>
</form>
<div class="reihe"><a class="btn" href="/klick?skip={escape(entry["key"])}">Später entscheiden</a>
<a class="btn" href="/">Abbrechen</a></div>"""
        return layout("Durchklicken", body, "klick")

    # Standard-Pfad: Genau eine Einzelfrage
    optionen = entry.get("_optionen") or parse_options(entry.get("options_excerpt", ""))
    treffer = RECOMMENDED_RE.match(empfehlung)
    empf_buchstabe = treffer.group(1).upper() if treffer else ""

    knoepfe = "".join(
        f'<button class="wahl" type="submit" name="choice" value="{escape(letter)}">'
        f"<b>{escape(letter)}</b> — {escape(text)}"
        + (' <span class="tag">empfohlen</span>' if letter == empf_buchstabe else "")
        + "</button>"
        for letter, text in optionen
    )
    if not knoepfe:
        knoepfe = (
            '<label>Freie Entscheidung <span class="hint">(keine Optionen im Eintrag erkannt)'
            '</span></label><input name="choice" required placeholder="z. B. A oder JA">'
            '<div class="reihe"><button class="prim" type="submit">Entscheidung eintragen</button></div>'
        )

    empf_block = f'<div class="empf"><b>Empfehlung:</b> {escape(empfehlung)}</div>' if empfehlung else ""

    body = f"""{warn}<h1>{escape(entry["title"])}</h1>
<div class="meta"><code>{escape(entry["key"])}</code> · {escape(entry["date"])} ·
Quelle: <code>{escape(entry["source_file"])}</code>, Zeile {entry["source_line"]} ·
noch {rest} offen</div>
<div class="card"><h2>Kontext</h2><div class="kontext">{escape(kontext)}</div></div>
{empf_block}
<form method="post" action="/api/decide" class="card">
<input type="hidden" name="key" value="{escape(entry["key"])}">
<input type="hidden" name="confirmation" value="{escape(confirmation)}">
<h2>Entscheidung</h2>{knoepfe}
<label>Anmerkung <span class="hint">(optional, wird mit eingetragen)</span></label>
<textarea name="note" rows="2" placeholder="Begründung, Einschränkung, Auflage …"></textarea>
</form>
<div class="reihe"><a class="btn" href="/klick?skip={escape(entry["key"])}">Später entscheiden</a>
<a class="btn" href="/">Abbrechen</a></div>"""
    return layout("Durchklicken", body, "klick")


def bestaetigung(entry_id: str, title: str, choice: str, note: str = "", rest: int = 0,
                 undo_confirmation: str = "") -> bytes:
    """Deutliche Rueckmeldung nach dem Klick — keine stille Weiterleitung mehr.

    Der Nutzer sieht explizit, WAS gerade geschrieben wurde, und bekommt einen
    direkten Weg, es sofort wieder zurueckzunehmen, statt erst im Verlauf
    danach suchen zu muessen.
    """
    anmerkung = f' <span class="hint">— {escape(note)}</span>' if note else ""
    weiter = (f'<a class="btn prim" href="/klick">Weiter zur nächsten Entscheidung '
              f'({rest} offen)</a>' if rest else
              '<a class="btn prim" href="/klick">Zur Durchklick-Ansicht</a>')
    body = f"""<div class="card" style="border-left:4px solid var(--acc)">
<h1>✅ Entschieden: {escape(entry_id)} — Option {escape(choice)}</h1>
<p>{escape(title)}</p>
<p>Gewählt: <b>{escape(choice)}</b>{anmerkung}</p>
<div class="reihe">
<form method="post" action="/api/undo/{escape(entry_id)}">
<input type="hidden" name="confirmation" value="{escape(undo_confirmation)}">
<button class="btn" type="submit">Rückgängig machen</button></form>
{weiter}
<a class="btn" href="/verlauf">Verlauf</a>
<a class="btn" href="/">Übersicht</a>
</div></div>"""
    return layout("Entschieden", body, "klick")


def _verlauf_zeile(e: dict, confirmation: str = "") -> str:
    reset_hint = (f' <span class="hint">{escape(e["reset_on"])}'
                  f' — {escape(e["reset_reason"])}</span>' if e["status"] != "aktiv" else "")
    aktion = ""
    if e["status"] == "aktiv":
        aktion = (f'<form method="post" action="/api/undo/{escape(e["id"])}">'
                  f'<input type="hidden" name="confirmation" value="{escape(confirmation)}">'
                  '<button class="btn" type="submit">Rückgängig</button></form>')
    status = "zurückgesetzt" if e["status"] == "zurueckgesetzt" else e["status"]
    return (
        f'<tr><td><code>{escape(e["id"])}</code></td>'
        f'<td>{escape(e["title"])}</td>'
        f'<td>{escape(e["choice"] or "—")}</td>'
        f'<td>{escape(e["decided_on"])}</td>'
        f'<td><span class="tag">{escape(status)}</span>{reset_hint}</td>'
        f'<td>{aktion}</td></tr>'
    )


def verlauf(eintraege: list[dict], confirmations: dict[str, str] | None = None) -> bytes:
    if eintraege:
        confirmations = confirmations or {}
        zeilen = "".join(_verlauf_zeile(e, confirmations.get(e["id"], "")) for e in eintraege)
        tabelle = ('<div class="table-wrap"><table><tr><th>ID</th><th>Titel</th><th>Wahl</th><th>Am</th>'
                   f"<th>Status</th><th></th></tr>{zeilen}</table></div>")
    else:
        tabelle = '<div class="leer">Noch keine über den Clicker getroffene Entscheidung.</div>'
    body = f"""<h1>Verlauf</h1>
<div class="meta">Nur Entscheidungen, die über diese Oberfläche getroffen wurden — nicht
das vollständige Register aller Entscheidungen (dafür: <a href="/register">Register</a>).</div>
<div class="card"><h2>{len(eintraege)} Einträge</h2>{tabelle}</div>"""
    return layout("Verlauf", body, "verlauf")


def neu(next_id: str, ziel: str, meldung: str = "") -> bytes:
    kopf = f'<div class="empf">{meldung}</div>' if meldung else ""
    body = f"""{kopf}<h1>Entscheidung einstellen</h1>
<div class="meta">Nächste freie ID: <code>{escape(next_id)}</code> ·
Ziel: <code>{escape(ziel)}</code></div>
<form method="post" action="/api/new" class="card">
<label>Titel <span class="hint">(kurz, ohne ID)</span></label>
<input name="title" required placeholder="Wovon handelt die Entscheidung?">
<label>Frage <span class="hint">(was genau ist zu entscheiden?)</span></label>
<input name="frage" required placeholder="Soll … oder …?">
<label>Kontext <span class="hint">(Fakten, Stand, Folgen — mehrzeilig)</span></label>
<textarea name="kontext" rows="6"></textarea>
<label>Optionen <span class="hint">(je Zeile eine, beginnend mit A/B/C)</span></label>
<textarea name="optionen" rows="4" required placeholder="A — …&#10;B — …"></textarea>
<label>Empfehlung</label>
<input name="empfehlung" placeholder="A — weil …">
<label>Quelle <span class="hint">(Datei, Lauf, Briefing)</span></label>
<input name="quelle">
<label>Evidenzanker <span class="hint">(optional, je Zeile eine stabile Fundstelle)</span></label>
<textarea name="evidenzanker" rows="3"></textarea>
<label>Gegenbelege <span class="hint">(optional, je Zeile)</span></label>
<textarea name="gegenbelege" rows="2"></textarea>
<label>Fehlende Informationen <span class="hint">(optional, je Zeile)</span></label>
<textarea name="fehlende_informationen" rows="2"></textarea>
<label>Erstellt von <span class="hint">(Person oder Adapterkennung)</span></label>
<input name="erstellt_von">
<label>Kontext-Fingerprint <span class="hint">(optional: sha256:&lt;64 Hex-Zeichen&gt;)</span></label>
<input name="kontext_fingerprint">
<label>Geltung <span class="hint">(leer = global)</span></label>
<input name="scope" placeholder="global | host:WORKSTATION | projekt:…">
<div class="reihe"><button class="prim" type="submit">In die Kette einstellen</button>
<a class="btn" href="/">Abbrechen</a></div>
</form>"""
    return layout("Einstellen", body, "neu")


def register(eintraege: list[dict], suche: str) -> bytes:
    if eintraege:
        zeilen = "".join(
            f"<tr><td><code>{escape(e['key'])}</code></td><td>{escape(e['date'])}</td>"
            f"<td>{escape(e['title'])}</td>"
            f"<td>{escape(e['decision_field_raw'] or '—')}</td>"
            f"<td><span class=\"tag\">{escape(e['status_class'])}</span></td>"
            "<td>" + " ".join(f"<code>{escape(f)}</code>"
                              for f in e.get("fundstellen", [e["source_file"]])) + "</td></tr>"
            for e in eintraege
        )
        tabelle = ('<div class="table-wrap"><table><tr><th>ID</th><th>Datum</th><th>Titel</th>'
                   f"<th>Entscheidung</th><th>Status</th><th>Fundstelle(n)</th></tr>{zeilen}</table></div>")
    else:
        tabelle = '<div class="leer">Kein Treffer.</div>'
    body = f"""<h1>Register</h1>
<form method="get" action="/register" class="card">
<label>Suche <span class="hint">(ID, Titel, Entscheidungstext)</span></label>
<input name="q" value="{escape(suche)}" placeholder="z. B. Zenodo, D-20260731, Routinika">
<div class="reihe"><button class="prim" type="submit">Suchen</button>
<a class="btn" href="/register">Zurücksetzen</a></div></form>
<div class="card"><h2>{len(eintraege)} getroffene Entscheidungen</h2>{tabelle}</div>"""
    return layout("Register", body, "register")


def meldung(titel: str, text: str, ziel: str = "/klick", ziel_text: str = "Weiter") -> bytes:
    body = (f'<h1>{escape(titel)}</h1><div class="card"><p>{escape(text)}</p>'
            f'<div class="reihe"><a class="btn prim" href="{escape(ziel)}">{escape(ziel_text)}</a>'
            f'<a class="btn" href="/">Übersicht</a></div></div>')
    return layout(titel, body)

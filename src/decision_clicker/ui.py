# SPDX-License-Identifier: MIT
"""HTML-Oberflaeche — bewusst ohne Framework, damit START.bat immer laeuft."""
from __future__ import annotations

import re
from html import escape

CSS = """
:root{--bg:#f6f7f9;--fg:#1b1f24;--mut:#5b6673;--card:#fff;--line:#dfe3e8;
--acc:#2f6f4f;--acc2:#e8f2ec;--warn:#8a5a00;--warnbg:#fdf3e0}
@media(prefers-color-scheme:dark){:root{--bg:#14171a;--fg:#e8eaed;--mut:#98a2ad;
--card:#1c2025;--line:#2c3238;--acc:#6fbf8f;--acc2:#1d2a23;--warn:#e0b062;--warnbg:#2a2317}}
*{box-sizing:border-box}
body{margin:0;font:16px/1.55 "Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{background:var(--card);border-bottom:1px solid var(--line);padding:.7rem 1.2rem;
display:flex;gap:1.2rem;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:5}
header b{font-size:1.05rem}
nav a{color:var(--fg);text-decoration:none;padding:.3rem .6rem;border-radius:6px}
nav a:hover{background:var(--acc2)}
nav a.on{background:var(--acc);color:#fff}
main{max-width:900px;margin:0 auto;padding:1.4rem 1.2rem 4rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:1.1rem 1.3rem;margin-bottom:1rem}
.zahlen{display:flex;gap:.7rem;flex-wrap:wrap;margin-bottom:1.2rem}
.zahl{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:.7rem 1rem;min-width:7.5rem}
.zahl .n{font-size:1.7rem;font-weight:700;display:block;line-height:1.1}
.zahl .l{color:var(--mut);font-size:.8rem}
h1{font-size:1.35rem;margin:.2rem 0 1rem}
h2{font-size:1.1rem;margin:0 0 .6rem}
.meta{color:var(--mut);font-size:.85rem;margin-bottom:.9rem}
.kontext{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);
border-radius:8px;padding:.8rem 1rem;font-size:.92rem;max-height:22rem;overflow:auto}
button,.btn{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);
border-radius:8px;padding:.6rem 1rem;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,.btn:hover{border-color:var(--acc)}
button.wahl{display:block;width:100%;text-align:left;margin:.45rem 0;padding:.8rem 1rem}
button.wahl:hover{background:var(--acc2);border-color:var(--acc)}
button.wahl b{color:var(--acc)}
button.prim{background:var(--acc);color:#fff;border-color:var(--acc)}
.empf{background:var(--acc2);border-left:4px solid var(--acc);padding:.6rem .9rem;
border-radius:0 8px 8px 0;margin:.9rem 0}
.warn{background:var(--warnbg);border-left:4px solid var(--warn);padding:.6rem .9rem;
border-radius:0 8px 8px 0;margin:.9rem 0;color:var(--warn)}
input,textarea,select{font:inherit;width:100%;padding:.55rem .7rem;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--fg)}
label{display:block;margin:.8rem 0 .25rem;font-weight:600;font-size:.9rem}
.hint{color:var(--mut);font-size:.82rem;font-weight:400}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600}
.tag{font-size:.72rem;padding:.15rem .5rem;border-radius:99px;background:var(--acc2);
color:var(--acc);white-space:nowrap}
.leer{color:var(--mut);text-align:center;padding:2.5rem 1rem}
code{background:var(--bg);padding:.1rem .35rem;border-radius:4px;font-size:.85em}
.reihe{display:flex;gap:.6rem;flex-wrap:wrap;margin-top:1rem}
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


def intake_banner(offene: list[dict]) -> str:
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
            '<form method="post" action="/api/intake"><div class="reihe">'
            '<button class="prim" type="submit">Jetzt übernehmen</button>'
            "</div></form></div>")


def home(data: dict[str, int], offen: list[dict], hinweis: str = "",
         postfach: list[dict] | None = None) -> bytes:
    kopf = f'<div class="warn">{escape(hinweis)}</div>' if hinweis else ""
    kopf += intake_banner(postfach or [])
    if offen:
        zeilen = "".join(
            f'<tr><td><a href="/klick?key={escape(e["key"])}"><code>{escape(e["key"])}</code></a></td>'
            f'<td>{escape(e["title"])}</td>'
            f'<td><span class="tag">{escape(e["scope"])}</span></td></tr>'
            for e in offen
        )
        tabelle = (
            "<table><tr><th>ID</th><th>Titel</th><th>Geltung</th></tr>"
            f"{zeilen}</table>"
            '<div class="reihe"><a class="btn prim" href="/klick">Durchklicken starten</a></div>'
        )
    else:
        tabelle = '<div class="leer">Keine offene Entscheidung. Nichts zu tun.</div>'
    body = (
        f"{kopf}<h1>Übersicht</h1>{numbers(data)}"
        f'<div class="card"><h2>Offene Entscheidungen</h2>{tabelle}</div>'
    )
    return layout("Übersicht", body, "home")


def klick(entry: dict | None, rest: int, hinweis: str = "") -> bytes:
    if entry is None:
        body = (
            "<h1>Durchklicken</h1>"
            '<div class="card"><div class="leer">Alle Entscheidungen sind getroffen.<br>'
            '<a class="btn" href="/" style="margin-top:1rem">Zur Übersicht</a></div></div>'
        )
        return layout("Durchklicken", body, "klick")

    optionen = entry.get("_optionen") or parse_options(entry.get("options_excerpt", ""))
    empfehlung = (entry.get("recommendation_excerpt") or "").strip()
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

    kontext = entry.get("_raw") or entry.get("question") or ""
    warn = f'<div class="warn">{escape(hinweis)}</div>' if hinweis else ""
    empf_block = f'<div class="empf"><b>Empfehlung:</b> {escape(empfehlung)}</div>' if empfehlung else ""

    body = f"""{warn}<h1>{escape(entry["title"])}</h1>
<div class="meta"><code>{escape(entry["key"])}</code> · {escape(entry["date"])} ·
Quelle: <code>{escape(entry["source_file"])}</code>, Zeile {entry["source_line"]} ·
noch {rest} offen</div>
<div class="card"><h2>Kontext</h2><div class="kontext">{escape(kontext)}</div></div>
{empf_block}
<form method="post" action="/api/decide" class="card">
<input type="hidden" name="key" value="{escape(entry["key"])}">
<h2>Entscheidung</h2>{knoepfe}
<label>Anmerkung <span class="hint">(optional, wird mit eingetragen)</span></label>
<textarea name="note" rows="2" placeholder="Begründung, Einschränkung, Auflage …"></textarea>
</form>
<div class="reihe"><a class="btn" href="/klick?skip={escape(entry["key"])}">Später entscheiden</a>
<a class="btn" href="/">Abbrechen</a></div>"""
    return layout("Durchklicken", body, "klick")


def neu(next_id: str, ziel: str, meldung: str = "") -> bytes:
    kopf = f'<div class="empf">{meldung}</div>' if meldung else ""
    body = f"""{kopf}<h1>Entscheidung einstellen</h1>
<div class="meta">Nächste freie ID: <code>{escape(next_id)}</code> ·
Ziel: <code>{escape(ziel)}</code></div>
<form method="post" action="/api/new" class="card">
<label>Titel <span class="hint">(kurz, ohne ID)</span></label>
<input name="title" required placeholder="Wovon handelt die Entscheidung?">
<label>Frage <span class="hint">(was genau ist zu entscheiden?)</span></label>
<input name="frage" placeholder="Soll … oder …?">
<label>Kontext <span class="hint">(Fakten, Stand, Folgen — mehrzeilig)</span></label>
<textarea name="kontext" rows="6"></textarea>
<label>Optionen <span class="hint">(je Zeile eine, beginnend mit A/B/C)</span></label>
<textarea name="optionen" rows="4" placeholder="A — …&#10;B — …"></textarea>
<label>Empfehlung</label>
<input name="empfehlung" placeholder="A — weil …">
<label>Quelle <span class="hint">(Datei, Lauf, Briefing)</span></label>
<input name="quelle">
<label>Geltung <span class="hint">(leer = global)</span></label>
<input name="scope" placeholder="global | host:ASUS-GEI | projekt:…">
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
        tabelle = ("<table><tr><th>ID</th><th>Datum</th><th>Titel</th>"
                   f"<th>Entscheidung</th><th>Status</th><th>Fundstelle(n)</th></tr>{zeilen}</table>")
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

"""Baut die Grafiken für das GitHub-Profil im jacob.decoded-Look.

  assets/profil.svg      das ganze Profil als eine Terminal-Sitzung, mit Live-Daten
  assets/profil-handy.svg  dasselbe schmal für Smartphones
  assets/link-*.svg      Link-Etiketten (Website, YouTube, ...)

Live-Daten:
  * GitHub-REST-API: öffentliche Repos, Sterne, Forks, Sprachen, gemergte PRs
  * YouTube-Feed des Kanals (RSS, kein API-Schlüssel nötig): neueste Videos

Aufruf:  python scripts/profil.py
Das Profil wird nur neu geschrieben, wenn sich Daten oder Skript geändert
haben – so entsteht kein täglicher Commit ohne Inhalt. Schlägt ein Abruf fehl,
bleibt der bisherige Stand stehen.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

NUTZER = "JacobMenge"
KANAL_ID = "UCuG3DZ4awzd4rtsIr02TL7Q"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Farben wie im restlichen Profil
GRUEN = "#00E676"
GRUEN_HELL = "#D1FFE6"
GRUND = "#0B0E11"
FLAECHE = "#0F1419"
LINIE = "#2A2F36"
GRAU = "#9CA3AF"
TEXT = "#E5E7EB"
WEISS = "#FFFFFF"

W = 1200  # Standardbreite der Grafiken

# Breiteste gängige Monospace-Schrift (Menlo, DejaVu Sans Mono: 0,602 em).
# Consolas ist schmaler (0,55 em) - dort wird es nur etwas luftiger.
ZEICHEN_EM = 0.61
SCHRIFT = "'Cascadia Mono', Consolas, 'SF Mono', Menlo, 'DejaVu Sans Mono', 'Liberation Mono', monospace"

STACK = [
    ("cloud & devops", ["AWS", "Azure", "Docker", "Kubernetes", "Terraform", "Ansible",
                        "GitHub Actions", "Jenkins", "Prometheus", "Grafana", "Linux"]),
    ("sprachen & backend", ["Python", "Bash", "JavaScript", "Node.js", "Express.js", "React"]),
    ("datenbanken", ["PostgreSQL", "MySQL", "MariaDB", "MongoDB", "Redis"]),
    ("tools", ["Git", "VS Code", "Jest", "Nextcloud"]),
]

# Inhalt von "Über mich" - **fett**, ==grün==
UEBER = {
    "gruss": "Moin, ich bin Jacob!",
    "rollen": "Dozent · DevOps Engineer · Creator bei jacob.decoded",
    "claim": "IT, Technik & spannende Projekte – verständlich erklärt.",
    "absaetze": [
        "Ich bin **Dozent und DevOps Engineer** mit einer Leidenschaft dafür, komplexe Tech-Themen "
        "verständlich zu machen. Ich baue Cloud-Infrastrukturen, entwickle KI-gestützte Workflows und "
        "bilde die nächste Generation von IT-Fachkräften aus.",
        "Außerdem betreibe ich ==@jacob.decoded==: Dort geht es um IT, Technik und spannende Projekte. "
        "Ich gehe Fragen nach, die mich nicht loslassen, und probiere selbst aus, was wirklich dahintersteckt.",
    ],
    "punkte": [
        ("Dozent", "für Linux, Cloud Computing, Python & DevOps"),
        ("DevOps Engineer", "für Cloud-Architekturen, Automatisierung & KI-gestützte Workflows"),
        ("Creator", "bei ==@jacob.decoded==: Tech-Experimente, Projekte & spannende Fragen rund um IT"),
    ],
}

# Dateiname, Beschriftung, Symbol (die Ziele stehen im README)
LINKS = [
    ("website", "jacob-decoded.de", "globus"),
    ("youtube", "YouTube", "play"),
    ("instagram", "Instagram", "kamera"),
    ("tiktok", "TikTok", "note"),
    ("mail", "Mail", "brief"),
]


# ---------------------------------------------------------------- Hilfen

def esc(text: str) -> str:
    return html.escape(text, quote=True)


def breite(text: str, groesse: float) -> float:
    """Obergrenze der Textbreite in px für eine Monospace-Schrift."""
    return len(text) * groesse * ZEICHEN_EM


def kuerzen(text: str, max_zeichen: int) -> str:
    # Emojis und Symbole haben in Monospace keine feste Breite - raus damit
    text = re.sub("[\u2600-\u27bf\U0001f000-\U0001faff\ufe0f\u200d]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_zeichen else text[: max_zeichen - 1].rstrip(" ,.:;-–") + "…"


def svg(hoehe: int, label: str, stil: str, defs: str, inhalt: str, weite: int = W) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {weite} {hoehe}" '
            f'width="{weite}" height="{hoehe}" role="img" aria-label="{esc(label)}">\n'
            f"<title>{esc(label)}</title>\n"
            f"<style>\n  text {{ font-family: {SCHRIFT}; }}\n{stil}</style>\n"
            f"<defs>\n{defs}</defs>\n{inhalt}</svg>\n")


# Blinkender Block als Teil einer Textzeile (tspan kennt kein opacity, nur fill-opacity)
CURSOR_TEXT = """  .cursor-text { animation: blinken-text 1s steps(1) infinite; }
  @keyframes blinken-text { 50% { fill-opacity: 0; } }
"""

BEWEGUNG_AUS = """  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; }
    .rein, .zeile, .buchstabe { opacity: 1 !important; }
  }
"""


def matrix_regen(zufall: random.Random, hoehe: int, x_von: int = 12, x_bis: int = W,
                 dichte: float = 1.0, groesse: int = 16) -> tuple[str, str]:
    """Fallende Zeichenspalten. Gibt (CSS, SVG) zurück."""
    zeichen = "01{}[]<>/$#=+*;:ABCDEF0123456789"
    zeilenabstand = groesse + 4
    spalten = []
    for x in range(x_von, x_bis, 24):
        if zufall.random() > dichte:
            continue
        laenge = zufall.randint(8, 16)
        dauer = zufall.uniform(7, 15) * hoehe / 360 + 3
        start = -zufall.uniform(0, dauer)
        tspans = []
        for i in range(laenge):
            kopf = i == laenge - 1
            deckkraft = 0.9 if kopf else 0.12 + 0.5 * i / laenge
            tspans.append(f'<tspan x="{x}" dy="{zeilenabstand}" fill="{GRUEN_HELL if kopf else GRUEN}" '
                          f'fill-opacity="{deckkraft:.2f}">{esc(zufall.choice(zeichen))}</tspan>')
        spalten.append(f'  <text class="regen" style="animation-duration:{dauer:.1f}s;'
                       f'animation-delay:{start:.1f}s">{"".join(tspans)}</text>')
    laenge_px = 16 * zeilenabstand
    css = (f"  .regen {{ font-size: {groesse}px; animation: fallen linear infinite; }}\n"
           f"  @keyframes fallen {{ from {{ transform: translateY(-{laenge_px + 20}px); }} "
           f"to {{ transform: translateY({hoehe + 20}px); }} }}\n")
    return css, "\n".join(spalten)


def symbol(name: str, cx: float, cy: float) -> str:
    """Kleine Linien-Symbole (18 x 18 px) für Etiketten."""
    s = f'fill="none" stroke="{GRUEN}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
    if name == "play":
        return f'<path d="M{cx - 5:.1f} {cy - 8:.1f}l13 8-13 8z" fill="{GRUEN}"/>'
    if name == "globus":
        return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8.5" {s}/>'
                f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="3.8" ry="8.5" {s}/>'
                f'<path d="M{cx - 8.5:.1f} {cy:.1f}h17" {s}/>')
    if name == "kamera":
        return (f'<rect x="{cx - 8.5:.1f}" y="{cy - 8.5:.1f}" width="17" height="17" rx="5" {s}/>'
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" {s}/>'
                f'<circle cx="{cx + 4.6:.1f}" cy="{cy - 4.6:.1f}" r="1.1" fill="{GRUEN}"/>')
    if name == "note":
        return (f'<circle cx="{cx - 3.5:.1f}" cy="{cy + 5:.1f}" r="3.5" {s}/>'
                f'<path d="M{cx:.1f} {cy + 5:.1f}V{cy - 8.5:.1f}c1 3.5 4 5 7 5" {s}/>')
    if name == "brief":
        return (f'<rect x="{cx - 9:.1f}" y="{cy - 6.5:.1f}" width="18" height="13" rx="2" {s}/>'
                f'<path d="M{cx - 8.5:.1f} {cy - 5.5:.1f}l8.5 6.5 8.5-6.5" {s}/>')
    return ""


def pille(x: float, y: float, text: str, groesse: int = 17, zeichen: str = "") -> tuple[str, float]:
    """Umrandetes Etikett wie im Banner. Gibt (SVG, Breite) zurück."""
    innen = 26 if zeichen else 0
    b = breite(text, groesse) + innen + 36
    h = groesse + 23
    teile = [f'<rect x="{x:.1f}" y="{y}" width="{b:.1f}" height="{h}" rx="{h / 2}" fill="{FLAECHE}"/>'
             f'<rect x="{x:.1f}" y="{y}" width="{b:.1f}" height="{h}" rx="{h / 2}" fill="{GRUEN}" '
             f'fill-opacity=".08" stroke="{GRUEN}" stroke-opacity=".55"/>']
    mx, my = x + 18, y + h / 2
    if zeichen:
        teile.append(symbol(zeichen, mx + 9, my))
    teile.append(f'<text x="{mx + innen:.1f}" y="{my + groesse * .35:.1f}" font-size="{groesse}" '
                 f'fill="{WEISS}">{esc(text)}</text>')
    return "".join(teile), b


# ---------------------------------------------------------------- Live-Daten

def hole(url: str, accept: str = "application/vnd.github+json") -> bytes:
    kopf = {"User-Agent": "jacobmenge-profil", "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        kopf["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=kopf), timeout=20) as antwort:
        return antwort.read()


def github_daten(nutzer: str) -> dict:
    repos: list[dict] = []
    for seite in range(1, 11):
        teil = json.loads(hole(f"https://api.github.com/users/{nutzer}/repos"
                               f"?type=owner&per_page=100&page={seite}"))
        repos += teil
        if len(teil) < 100:
            break
    eigene = [r for r in repos if not r["fork"]]
    sprachen = Counter(r["language"] for r in eigene if r["language"])
    q = urllib.parse.quote(f"is:pr author:{nutzer} is:merged")
    prs = json.loads(hole(f"https://api.github.com/search/issues?q={q}&per_page=1"))
    return {
        "repos": len(eigene),
        "sterne": sum(r["stargazers_count"] for r in eigene),
        "forks": sum(r["forks_count"] for r in eigene),
        "prs": prs["total_count"],
        "sprachen": [s for s, _ in sprachen.most_common(3)],
    }


def youtube_videos(kanal_id: str, anzahl: int = 2) -> list[dict]:
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    wurzel = ET.fromstring(hole(f"https://www.youtube.com/feeds/videos.xml?channel_id={kanal_id}",
                                accept="application/atom+xml"))
    return [{"titel": e.findtext("a:title", "", ns), "datum": e.findtext("a:published", "", ns)[:10],
             "id": e.findtext("yt:videoId", "", ns)}
            for e in wurzel.findall("a:entry", ns)[:anzahl]]


# ---------------------------------------------------------------- Text

# Einfache Auszeichnung in den Texten: **fett** (weiß), ==betont== (grün)
AUSZEICHNUNG = re.compile(r"(\*\*.+?\*\*|==.+?==)")


def woerter(text: str) -> list[tuple[str, str]]:
    """Zerlegt ausgezeichneten Text in (Wort, Stil)-Paare."""
    ergebnis = []
    for teil in AUSZEICHNUNG.split(text):
        if not teil:
            continue
        stil = "normal"
        if teil.startswith("**"):
            teil, stil = teil[2:-2], "fett"
        elif teil.startswith("=="):
            teil, stil = teil[2:-2], "gruen"
        if teil[0].isspace() and ergebnis:
            # Leerzeichen zwischen zwei Auszeichnungen gehört ans vorige Wort
            wort, alt = ergebnis[-1]
            ergebnis[-1] = (wort.rstrip() + " ", alt)
        for wort in re.findall(r"\S+\s*", teil):
            ergebnis.append((wort, stil))
    return ergebnis


def umbrechen(text: str, max_zeichen: int) -> list[list[tuple[str, str]]]:
    zeilen: list[list[tuple[str, str]]] = [[]]
    laenge = 0
    for wort, stil in woerter(text):
        if laenge + len(wort.rstrip()) > max_zeichen and zeilen[-1]:
            zeilen.append([])
            laenge = 0
        zeilen[-1].append((wort, stil))
        laenge += len(wort)
    # Kein einzelnes Wort allein in der letzten Zeile
    if len(zeilen) > 1 and len(zeilen[-1]) == 1 and len(zeilen[-2]) > 3:
        zeilen[-1].insert(0, zeilen[-2].pop())
    return zeilen


def textzeile(x: float, y: float, teile: list[tuple[str, str]], groesse: int, farbe: str = TEXT) -> str:
    farben = {"normal": f'fill="{farbe}"', "fett": f'fill="{WEISS}" font-weight="bold"',
              "gruen": f'fill="{GRUEN}" font-weight="bold"'}
    # Gleiche Stile zusammenfassen, damit Leerzeichen innerhalb eines tspans bleiben
    gruppen: list[list[str]] = []
    for wort, stil in teile:
        if gruppen and gruppen[-1][1] == stil:
            gruppen[-1][0] += wort
        else:
            gruppen.append([wort, stil])
    tspans = "".join(f"<tspan {farben[stil]}>{esc(t)}</tspan>" for t, stil in gruppen)
    return f'<text x="{x:.0f}" y="{y:.0f}" font-size="{groesse}" xml:space="preserve">{tspans.rstrip()}</text>'


FENSTER_STIL = """  .rein { opacity: 0; animation: auftauchen .45s ease-out both; }
  @keyframes auftauchen { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
""" + BEWEGUNG_AUS

# ---------------------------------------------------------------- Profil als Terminal-Sitzung

TITEL = "jacob.decoded"


@dataclass(frozen=True)
class Layout:
    """Maße einer Fassung. Die Handy-Fassung ist schmaler und hat relativ größere Schrift."""
    weite: int
    rand: int          # linker und rechter Innenabstand
    fliess: int        # Fließtext
    zeile: int         # Zeilenabstand im Fließtext
    befehl: int        # Eingabezeilen ($ ...)
    name: int          # jacob.decoded
    rollen: int
    leiste: int        # Titelleiste
    abschnitt: int     # Luft vor jedem Befehl
    schmal: bool


DESKTOP = Layout(weite=1200, rand=72, fliess=20, zeile=33, befehl=22, name=78, rollen=24,
                 leiste=52, abschnitt=64, schmal=False)
HANDY = Layout(weite=640, rand=36, fliess=24, zeile=37, befehl=26, name=64, rollen=25,
               leiste=60, abschnitt=60, schmal=True)


def ohne_auszeichnung(text: str) -> str:
    return AUSZEICHNUNG.sub(lambda m: m.group(0).strip("*="), text)


def sitzung(gh: dict, videos: list[dict], stand: datetime, lay: Layout = DESKTOP) -> str:
    """Das ganze Profil als ein Terminalfenster, das man von oben nach unten liest."""
    x, w = lay.rand, lay.weite
    zeichen_pro_zeile = int((w - 2 * x) / (lay.fliess * ZEICHEN_EM))
    einzug = round(1.6 * lay.fliess)
    teile: list[str] = []
    verzoegerung = iter(0.1 * n for n in range(200))

    def abschnitt(inhalt: str) -> None:
        teile.append(f'<g class="rein" style="animation-delay:{next(verzoegerung):.2f}s">{inhalt}</g>')

    def befehl(y: float, kommando: str, argument: str = "") -> None:
        arg = f' <tspan fill="{TEXT}">{esc(argument)}</tspan>' if argument else ""
        abschnitt(f'<text x="{x}" y="{y:.0f}" font-size="{lay.befehl}" font-weight="bold">'
                  f'<tspan fill="{GRUEN}">$ </tspan><tspan fill="{WEISS}">{esc(kommando)}</tspan>{arg}</text>')

    def absatz(y: float, text: str, groesse: int, max_zeichen: int, links: float, farbe: str = TEXT) -> float:
        """Setzt umbrochenen Text, gibt das y der letzten Zeile zurück."""
        zeilen = umbrechen(text, max_zeichen)
        teile_absatz = []
        for i, zeile in enumerate(zeilen):
            teile_absatz.append(textzeile(links, y + i * lay.zeile, zeile, groesse, farbe))
        abschnitt("".join(teile_absatz))
        return y + (len(zeilen) - 1) * lay.zeile

    # --- whoami
    y = lay.leiste + 72
    befehl(y, "whoami")
    y += round(lay.name * 1.18)
    schritt = lay.name * ZEICHEN_EM
    teile.append("".join(
        f'<text x="{x - 3 + i * schritt:.1f}" y="{y}" class="buchstabe" font-size="{lay.name}" font-weight="bold" '
        f'fill="{WEISS if i < 5 else GRUEN}" style="animation-delay:{0.2 + i * 0.05:.2f}s">{z}</text>'
        for i, z in enumerate(TITEL)))
    rollen = [r.strip() for r in UEBER["rollen"].split("·")]
    punkt = f'<tspan fill="{GRUEN}"> · </tspan>'
    if lay.schmal:  # Rollen untereinander
        y += round(lay.rollen * .5)
        for rolle in rollen:
            y += round(lay.rollen * 1.45)
            abschnitt(f'<text x="{x}" y="{y}" font-size="{lay.rollen}" fill="{TEXT}">{esc(rolle)}</text>')
    else:
        y += round(lay.rollen * 2)
        abschnitt(f'<text x="{x}" y="{y}" font-size="{lay.rollen}" fill="{TEXT}">'
                  + punkt.join(esc(r) for r in rollen) + "</text>")
    y += round(lay.zeile * 1.15)
    y = absatz(y, UEBER["claim"], lay.fliess, zeichen_pro_zeile, x, GRAU)

    # --- über mich
    y += lay.abschnitt
    befehl(y, "cat", "über-mich.md")
    y += round(lay.zeile * 1.55)
    abschnitt(f'<text x="{x}" y="{y}" font-size="{round(lay.fliess * 1.35)}" font-weight="bold" '
              f'fill="{WEISS}">{esc(UEBER["gruss"])}</text>')
    for text in UEBER["absaetze"]:
        y = absatz(y + lay.zeile + 12, text, lay.fliess, zeichen_pro_zeile, x)
    y += 10
    for titel, rest in UEBER["punkte"]:
        y += lay.zeile
        abschnitt(f'<text x="{x}" y="{y}" font-size="{lay.fliess}" fill="{GRUEN}">▸</text>')
        y = absatz(y, f"**{titel}** {rest}", lay.fliess, zeichen_pro_zeile - int(einzug / (lay.fliess * ZEICHEN_EM)) - 1, x + einzug)

    # --- stack
    y += lay.abschnitt
    befehl(y, "ls", "~/stack")
    y += 6
    if lay.schmal:  # Bereich als eigene Zeile, darunter die Technologien
        for bereich, dinge in STACK:
            y += lay.zeile + 14
            abschnitt(f'<text x="{x}" y="{y}" font-size="{lay.fliess}" fill="{GRAU}">{esc(bereich)}</text>')
            for reihe in _reihen(dinge, zeichen_pro_zeile):
                y += lay.zeile
                abschnitt(_liste(x, y, reihe, lay.fliess))
    else:
        spalte = x + max(len(b) for b, _ in STACK) * lay.fliess * ZEICHEN_EM + 40
        max_stack = int((w - x - spalte) / (lay.fliess * ZEICHEN_EM))
        for bereich, dinge in STACK:
            y += lay.zeile + 6
            zeilen = [f'<text x="{x}" y="{y}" font-size="{lay.fliess}" fill="{GRAU}">{esc(bereich)}</text>']
            for i, reihe in enumerate(_reihen(dinge, max_stack)):
                zeilen.append(_liste(spalte, y + i * lay.zeile, reihe, lay.fliess))
            y += (len(zeilen) - 2) * lay.zeile
            abschnitt("".join(zeilen))

    # --- live: GitHub
    y += lay.abschnitt
    befehl(y, "repo-radar", "--profil")
    zahlen = [(gh["repos"], "repos"), (gh["sterne"], "sterne"), (gh["forks"], "forks"), (gh["prs"], "prs gemergt")]
    paare = [f'<tspan fill="{WEISS}" font-weight="bold">{n}</tspan> <tspan fill="{GRAU}">{esc(t)}</tspan>'
             for n, t in zahlen]
    gruppen = [paare[:2], paare[2:]] if lay.schmal else [paare]
    y += 10
    for gruppe in gruppen:
        y += lay.zeile
        abschnitt(f'<text x="{x}" y="{y}" font-size="{lay.fliess}" xml:space="preserve">'
                  + "   ".join(gruppe) + "</text>")
    y += lay.zeile
    abschnitt(f'<text x="{x}" y="{y}" font-size="{lay.fliess}" fill="{GRAU}">sprachen</text>'
              + _liste(x + 9 * lay.fliess * ZEICHEN_EM + 10, y, gh["sprachen"] or ["–"], lay.fliess))

    # --- live: YouTube
    y += lay.abschnitt
    befehl(y, "youtube", "--neueste")
    y += 10
    for video in videos:
        y += lay.zeile
        datum = datetime.fromisoformat(video["datum"]).strftime("%d.%m.")
        abschnitt(f'<text x="{x}" y="{y}" font-size="{lay.fliess}" fill="{GRAU}">{datum}</text>')
        y = absatz(y, kuerzen(video["titel"], 200), lay.fliess, zeichen_pro_zeile - 8,
                   x + 8 * lay.fliess * ZEICHEN_EM, WEISS)

    # --- Eingabezeile am Ende
    y += lay.abschnitt
    abschnitt(f'<text x="{x}" y="{y}" font-size="{lay.befehl}" font-weight="bold" fill="{GRUEN}">$'
              f'<tspan class="cursor-text"> █</tspan></text>')
    hoehe = y + round(lay.abschnitt * .8)

    # Leiser Matrix-Regen nur oben rechts neben dem Namen
    # (auf dem Handy liefe er hinter dem Namen - dort weglassen)
    regen_hoehe = round(lay.name * 4.2)
    regen_css, regen = matrix_regen(random.Random(7), regen_hoehe, x_von=w - round(w * .35),
                                    x_bis=w - 20, dichte=0 if lay.schmal else .5, groesse=15)
    stil = regen_css + FENSTER_STIL + CURSOR_TEXT + """  .buchstabe { animation: an .01s steps(1) both; }
  @keyframes an { from { opacity: 0; } to { opacity: 1; } }
"""
    kopf_y = lay.leiste
    defs = f"""  <clipPath id="rahmen"><rect width="{w}" height="{hoehe}" rx="18"/></clipPath>
  <clipPath id="kopfbereich"><rect y="{kopf_y}" width="{w}" height="{regen_hoehe}"/></clipPath>
  <linearGradient id="regen-weg" x1="0" x2="1">
    <stop offset="0" stop-color="{GRUND}"/><stop offset=".45" stop-color="{GRUND}" stop-opacity=".6"/>
    <stop offset="1" stop-color="{GRUND}" stop-opacity=".15"/>
  </linearGradient>
  <linearGradient id="regen-unten" x1="0" y1="0" x2="0" y2="1">
    <stop offset=".5" stop-color="{GRUND}" stop-opacity="0"/><stop offset="1" stop-color="{GRUND}"/>
  </linearGradient>
"""
    regen_b = round(w * .37)
    punkte_x = [lay.leiste * .6 + i * lay.leiste * .42 for i in range(3)]
    ampel = "".join(f'<circle cx="{cx:.0f}" cy="{lay.leiste / 2:.0f}" r="{lay.leiste * .125:.1f}" fill="{f}"/>'
                    for cx, f in zip(punkte_x, ("#FF5F57", "#FEBC2E", "#28C840")))
    leiste_schrift = round(lay.leiste * .31)
    titel_x = w / 2 if not lay.schmal else punkte_x[-1] + lay.leiste * .5
    anker = "middle" if not lay.schmal else "start"
    nl = "\n  "
    inhalt = f"""<g clip-path="url(#rahmen)">
  <rect width="{w}" height="{hoehe}" fill="{GRUND}"/>
  <g clip-path="url(#kopfbereich)">
{regen}
    <rect x="{w - regen_b}" y="{kopf_y}" width="{regen_b}" height="{regen_hoehe}" fill="url(#regen-weg)"/>
    <rect x="{w - regen_b}" y="{kopf_y}" width="{regen_b}" height="{regen_hoehe}" fill="url(#regen-unten)"/>
  </g>
  <rect width="{w}" height="{lay.leiste}" fill="{FLAECHE}"/>
  <path d="M0 {lay.leiste + .5}h{w}" stroke="{LINIE}"/>
  {ampel}
  <text x="{titel_x:.0f}" y="{lay.leiste / 2 + leiste_schrift * .36:.0f}" font-size="{leiste_schrift}" fill="{GRAU}" text-anchor="{anker}">jacob@decoded: ~</text>
  <text x="{w - 28}" y="{lay.leiste / 2 + leiste_schrift * .36:.0f}" font-size="{leiste_schrift - 2}" fill="{GRAU}" text-anchor="end">live · {stand:%d.%m.%Y}</text>
  {nl.join(teile)}
</g>
<rect x=".5" y=".5" width="{w - 1}" height="{hoehe - 1}" rx="18" fill="none" stroke="{GRUEN}" stroke-opacity=".25"/>
"""
    label = " ".join([
        "jacob.decoded –", UEBER["rollen"] + ".", UEBER["claim"], UEBER["gruss"],
        *[ohne_auszeichnung(a) for a in UEBER["absaetze"]],
        *[f"{t} {ohne_auszeichnung(r)}." for t, r in UEBER["punkte"]],
        "Technologien:", *[f"{b}: {', '.join(d)}." for b, d in STACK],
        f"GitHub: {gh['repos']} Repos, {gh['sterne']} Sterne, {gh['forks']} Forks, {gh['prs']} gemergte Pull Requests.",
        "Neueste Videos:", *[v["titel"] + "." for v in videos],
    ])
    return svg(hoehe, label, stil, defs, inhalt, weite=w)


def _reihen(dinge: list[str], max_zeichen: int) -> list[list[str]]:
    """Verteilt Technologien als ganze Einheiten auf Zeilen."""
    reihen: list[list[str]] = [[]]
    laenge = 0
    for ding in dinge:
        if reihen[-1] and laenge + 3 + len(ding) > max_zeichen:
            reihen.append([])
            laenge = 0
        laenge += len(ding) + (3 if reihen[-1] else 0)
        reihen[-1].append(ding)
    return reihen


def _liste(x: float, y: float, dinge: list[str], groesse: int) -> str:
    trenner = f'<tspan fill="{GRUEN}" fill-opacity=".5"> · </tspan>'
    return (f'<text x="{x:.0f}" y="{y:.0f}" font-size="{groesse}" fill="{WEISS}" xml:space="preserve">'
            + trenner.join(esc(d) for d in dinge) + "</text>")


# ---------------------------------------------------------------- Links

def link(text: str, zeichen: str) -> str:
    """Einzelnes Link-Etikett für die Zeile unter der Begrüßung."""
    etikett, b = pille(1, 1, text, zeichen=zeichen)
    return svg(42, text, "", "", etikett + "\n", weite=round(b + 2))


# ---------------------------------------------------------------- Aufruf

def schreiben(datei: Path, inhalt: str) -> bool:
    if datei.exists() and datei.read_text(encoding="utf-8") == inhalt:
        return False
    datei.write_text(inhalt, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    for strom in (sys.stdout, sys.stderr):
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Baut die Profil-Grafiken im jacob.decoded-Look.")
    parser.add_argument("--nur-statisch", action="store_true",
                        help="nur die Link-Etiketten bauen (keine Netzabfragen)")
    args = parser.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)

    statisch = {f"link-{name}.svg": link(text, zeichen) for name, text, zeichen in LINKS}
    for name, inhalt in statisch.items():
        if schreiben(ASSETS / name, inhalt):
            print(f"geschrieben: assets/{name}")
    if args.nur_statisch:
        return 0

    try:
        gh = github_daten(NUTZER)
        videos = youtube_videos(KANAL_ID)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, KeyError, ValueError) as fehler:
        # Alter Stand bleibt stehen; in der Action als Warnung sichtbar, nicht als Fehler
        print(f"::warning::Live-Daten nicht abrufbar, Profil bleibt unverändert: {fehler}")
        return 0

    # Fingerabdruck aus Daten und Skript: nur bei echten Änderungen neu schreiben
    daten = json.dumps({"gh": gh, "videos": videos}, sort_keys=True).encode()
    abdruck = hashlib.sha256(daten + Path(__file__).read_bytes()).hexdigest()[:16]
    ziel = ASSETS / "profil.svg"
    if ziel.exists() and f"<!-- daten:{abdruck} -->" in ziel.read_text(encoding="utf-8"):
        print("profil.svg: Daten unverändert")
        return 0
    jetzt = datetime.now(timezone.utc)
    for name, lay in (("profil.svg", DESKTOP), ("profil-handy.svg", HANDY)):
        schreiben(ASSETS / name, sitzung(gh, videos, jetzt, lay) + f"<!-- daten:{abdruck} -->\n")
    print(f"geschrieben: assets/profil.svg und profil-handy.svg ({gh['repos']} Repos, {gh['sterne']} Sterne, "
          f"{gh['prs']} PRs, neuestes Video: {videos[0]['titel'] if videos else '–'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

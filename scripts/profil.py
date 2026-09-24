"""Baut die Grafiken für das GitHub-Profil im jacob.decoded-Look.

  assets/banner.svg      animiertes Banner mit Live-Daten (täglich per Action)
  assets/link-*.svg      Link-Etiketten (Website, YouTube, ...)
  assets/ueber-mich.svg  Begrüßung und "Über mich"
  assets/stack.svg       Technologien & Tools
  assets/fuss.svg        Abschluss

Live-Daten:
  * GitHub-REST-API: öffentliche Repos, Sterne, Forks, Sprachen, gemergte PRs
  * YouTube-Feed des Kanals (RSS, kein API-Schlüssel nötig): neueste Videos

Aufruf:  python scripts/profil.py
Das Banner wird nur neu geschrieben, wenn sich die Daten geändert haben – so
entsteht kein täglicher Commit ohne Inhalt. Schlägt ein Abruf fehl, bleibt das
bisherige Banner stehen.
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
from datetime import datetime, timezone
from pathlib import Path

NUTZER = "JacobMenge"
KANAL_ID = "UCuG3DZ4awzd4rtsIr02TL7Q"
KANAL = "@jacob.decoded"
WEBSITE = "www.jacob-decoded.de"
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

W = 1200  # alle Grafiken gleich breit, damit sie im README bündig stehen

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
        ("hut", "Dozent", "für Linux, Cloud Computing, Python & DevOps"),
        ("wolke", "DevOps Engineer", "für Cloud-Architekturen, Automatisierung & KI-gestützte Workflows"),
        ("klappe", "Creator", "bei ==@jacob.decoded==: Tech-Experimente, Projekte & spannende Fragen rund um IT"),
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


def verlaeufe(hoehe: int) -> str:
    """Rahmen-Clip und dunkle Kanten oben/unten."""
    return (f'  <clipPath id="rahmen"><rect width="{W}" height="{hoehe}" rx="18"/></clipPath>\n'
            f'  <linearGradient id="kanten" x1="0" y1="0" x2="0" y2="1">\n'
            f'    <stop offset="0" stop-color="{GRUND}"/><stop offset=".18" stop-color="{GRUND}" stop-opacity="0"/>\n'
            f'    <stop offset=".82" stop-color="{GRUND}" stop-opacity="0"/><stop offset="1" stop-color="{GRUND}"/>\n'
            f'  </linearGradient>\n')


def rand(hoehe: int) -> str:
    return (f'<rect x=".5" y=".5" width="{W - 1}" height="{hoehe - 1}" rx="18" fill="none" '
            f'stroke="{GRUEN}" stroke-opacity=".25"/>\n')


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
    if name == "hut":
        return (f'<path d="M{cx - 9:.1f} {cy - 3:.1f}l9-4.5 9 4.5-9 4.5z" {s}/>'
                f'<path d="M{cx - 5:.1f} {cy - 1:.1f}v4.5c0 1.8 10 1.8 10 0v-4.5M{cx + 9:.1f} {cy - 3:.1f}v5" {s}/>')
    if name == "wolke":
        return (f'<path d="M{cx - 5:.1f} {cy + 6:.1f}h10.5a4.5 4.5 0 0 0 .5-9 6 6 0 0 0-11.5-1.5 '
                f'4.5 4.5 0 0 0 .5 10.5z" {s}/>')
    if name == "klappe":
        return (f'<rect x="{cx - 8.5:.1f}" y="{cy - 3:.1f}" width="17" height="11" rx="1.5" {s}/>'
                f'<path d="M{cx - 8.5:.1f} {cy - 3:.1f}l1-5 16 3-1 2M{cx - 3.5:.1f} {cy - 7:.1f}l-1 4.5'
                f'M{cx + 2:.1f} {cy - 6:.1f}l-1 4" {s}/>')
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
    return [{"titel": e.findtext("a:title", "", ns), "id": e.findtext("yt:videoId", "", ns)}
            for e in wurzel.findall("a:entry", ns)[:anzahl]]


# ---------------------------------------------------------------- Banner

TITEL = "jacob.decoded"
TITEL_X, TITEL_Y, TITEL_GROESSE = 56, 160, 64
TITEL_SCHRITT = TITEL_GROESSE * ZEICHEN_EM


def banner(gh: dict, videos: list[dict], stand: datetime) -> str:
    H = 360
    zufall = random.Random(7)
    regen_css, regen = matrix_regen(zufall, H)

    # Schriftzug: jeder Buchstabe einzeln, damit er getippt erscheint und bei
    # jeder Schrift an derselben Stelle steht
    buchstaben, leuchten = [], []
    for i, z in enumerate(TITEL):
        x = TITEL_X + i * TITEL_SCHRITT
        verz = f"animation-delay:{0.3 + i * 0.07:.2f}s"
        buchstaben.append(f'  <text x="{x:.1f}" y="{TITEL_Y}" class="titel buchstabe" '
                          f'fill="{WEISS if i < 5 else GRUEN}" style="{verz}">{z}</text>')
        leuchten.append(f'<text x="{x:.1f}" y="{TITEL_Y}" class="titel">{z}</text>')
    cursor_x = TITEL_X + len(TITEL) * TITEL_SCHRITT + 4

    # Chips unter dem Untertitel
    chip1, b1 = pille(60, 236, f"YouTube {KANAL}", zeichen="play")
    chip2, _ = pille(60 + b1 + 14, 236, WEBSITE, zeichen="globus")

    # Terminal rechts
    tx, ty, tb, th = 700, 30, 460, 296
    innen_b = tb - 44
    groesse = 15
    max_zeichen = int(innen_b / (groesse * ZEICHEN_EM))
    zeilen: list[tuple[str, object]] = [
        ("befehl", f"$ repo-radar {NUTZER} --profil"),
        ("wert", ("repos", str(gh["repos"]))),
        ("wert", ("sterne", str(gh["sterne"]))),
        ("wert", ("forks", str(gh["forks"]))),
        ("wert", ("prs gemergt", str(gh["prs"]))),
        ("wert", ("sprachen", " · ".join(gh["sprachen"]) or "–")),
        ("abstand", None),
        ("befehl", "$ youtube --neueste"),
    ]
    zeilen += [("video", kuerzen(v["titel"], max_zeichen - 2)) for v in videos]

    terminal = []
    y = ty + 64
    for n, (art, inhalt) in enumerate(zeilen):
        if art == "abstand":
            y += 8
            continue
        stil = f'style="animation-delay:{0.6 + n * 0.25:.2f}s"'
        x = tx + 22
        if art == "befehl":
            terminal.append(f'  <text x="{x}" y="{y}" class="zeile befehl" {stil}>{esc(inhalt)}</text>')
        elif art == "wert":
            name, wert = inhalt
            wert = kuerzen(wert, max_zeichen - 14)
            terminal.append(f'  <text x="{x}" y="{y}" class="zeile" {stil}><tspan fill="{GRAU}">{esc(name)}</tspan>'
                            f'<tspan x="{x + 14 * groesse * ZEICHEN_EM:.0f}" fill="{WEISS}" font-weight="bold">'
                            f'{esc(wert)}</tspan></text>')
        else:
            terminal.append(f'  <text x="{x}" y="{y}" class="zeile" {stil}><tspan fill="{GRUEN}">▶</tspan>'
                            f'<tspan x="{x + 2 * groesse * ZEICHEN_EM:.0f}" fill="{WEISS}">{esc(inhalt)}</tspan></text>')
        y += 22
    cursor_verz = 0.6 + len(zeilen) * 0.25
    assert y + 6 <= ty + th, "Terminal-Inhalt ist höher als das Fenster"

    stil = regen_css + f"""  .titel {{ font-size: {TITEL_GROESSE}px; font-weight: bold; }}
  .buchstabe {{ animation: an .01s steps(1) both; }}
  @keyframes an {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
  .leuchten {{ opacity: 0; animation: einblenden .6s 1.2s ease-out forwards, pulsieren 4s 1.8s ease-in-out infinite; }}
  @keyframes einblenden {{ to {{ opacity: .45; }} }}
  @keyframes pulsieren {{ 0%, 100% {{ opacity: .45; }} 50% {{ opacity: .9; }} }}
  .cursor {{ animation: blinken 1s steps(1) infinite; }}
  @keyframes blinken {{ 50% {{ opacity: 0; }} }}
  .rein {{ opacity: 0; animation: auftauchen .5s ease-out both; }}
  .zeile {{ font-size: {groesse}px; fill: {TEXT}; opacity: 0; animation: auftauchen .25s ease-out both; }}
  .befehl {{ fill: {GRUEN}; }}
  @keyframes auftauchen {{ from {{ opacity: 0; transform: translateX(-6px); }} to {{ opacity: 1; transform: none; }} }}
  .scan {{ animation: scan 6s linear infinite; }}
  @keyframes scan {{ from {{ transform: translateY(-40px); }} to {{ transform: translateY({H + 40}px); }} }}
""" + BEWEGUNG_AUS

    defs = verlaeufe(H) + f"""  <linearGradient id="links" x1="0" x2="1">
    <stop offset="0" stop-color="{GRUND}" stop-opacity=".96"/>
    <stop offset=".75" stop-color="{GRUND}" stop-opacity=".9"/>
    <stop offset="1" stop-color="{GRUND}" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="scanlinie" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{GRUEN}" stop-opacity="0"/><stop offset=".5" stop-color="{GRUEN}" stop-opacity=".07"/>
    <stop offset="1" stop-color="{GRUEN}" stop-opacity="0"/>
  </linearGradient>
  <clipPath id="terminal"><rect x="{tx}" y="{ty}" width="{tb - 16}" height="{th}"/></clipPath>
  <filter id="weich" x="-10%" y="-60%" width="120%" height="220%"><feGaussianBlur stdDeviation="10"/></filter>
"""
    nl = "\n"
    inhalt = f"""<g clip-path="url(#rahmen)">
  <rect width="{W}" height="{H}" fill="{GRUND}"/>
{regen}
  <rect width="{W}" height="{H}" fill="url(#kanten)"/>
  <rect width="{tx + 40}" height="{H}" fill="url(#links)"/>
  <rect class="scan" width="{W}" height="40" fill="url(#scanlinie)"/>

  <text x="60" y="86" font-size="17" fill="{GRAU}" class="rein" style="animation-delay:.1s">~ $ whoami</text>
  <g class="leuchten" fill="{GRUEN}" filter="url(#weich)">{"".join(leuchten)}</g>
{nl.join(buchstaben)}
  <rect x="{cursor_x:.0f}" y="114" width="16" height="54" fill="{GRUEN}" class="cursor"/>
  <text x="60" y="204" font-size="18" fill="{TEXT}" class="rein" style="animation-delay:1.4s">IT, Technik &amp; spannende Projekte – verständlich erklärt.</text>
  <g class="rein" style="animation-delay:1.7s">{chip1}</g>
  <g class="rein" style="animation-delay:1.9s">{chip2}</g>
  <text x="60" y="318" font-size="15" fill="{GRAU}" class="rein" style="animation-delay:2.1s">Dozent · DevOps Engineer · Linux, Cloud &amp; Python</text>

  <g class="rein" style="animation-delay:.3s">
    <rect x="{tx}" y="{ty}" width="{tb}" height="{th}" rx="12" fill="{FLAECHE}" stroke="{LINIE}"/>
    <path d="M{tx} {ty + 34}h{tb}" stroke="{LINIE}"/>
    <circle cx="{tx + 20}" cy="{ty + 17}" r="6" fill="#FF5F57"/>
    <circle cx="{tx + 40}" cy="{ty + 17}" r="6" fill="#FEBC2E"/>
    <circle cx="{tx + 60}" cy="{ty + 17}" r="6" fill="#28C840"/>
    <text x="{tx + tb / 2 + 30:.0f}" y="{ty + 22}" font-size="13" fill="{GRAU}" text-anchor="middle">live · stand {stand:%d.%m.%Y}</text>
  </g>
  <g clip-path="url(#terminal)">
{nl.join(terminal)}
  </g>
  <rect x="{tx + 22}" y="{y - 15}" width="9" height="17" fill="{GRUEN}" class="cursor rein" style="animation-delay:{cursor_verz:.2f}s"/>
</g>
{rand(H)}"""
    label = (f"jacob.decoded – IT, Technik und spannende Projekte. YouTube {KANAL}, {WEBSITE}. "
             f"{gh['repos']} Repos, {gh['sterne']} Sterne. Neuestes Video: "
             f"{videos[0]['titel'] if videos else '–'}")
    return svg(H, label, stil, defs, inhalt)


# ---------------------------------------------------------------- Fenster

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
    return zeilen


def textzeile(x: float, y: float, teile: list[tuple[str, str]], groesse: int, extra: str = "") -> str:
    farben = {"normal": f'fill="{TEXT}"', "fett": f'fill="{WEISS}" font-weight="bold"',
              "gruen": f'fill="{GRUEN}" font-weight="bold"'}
    # Gleiche Stile zusammenfassen, damit Leerzeichen innerhalb eines tspans bleiben
    gruppen: list[list[str]] = []
    for wort, stil in teile:
        if gruppen and gruppen[-1][1] == stil:
            gruppen[-1][0] += wort
        else:
            gruppen.append([wort, stil])
    tspans = "".join(f"<tspan {farben[stil]}>{esc(t)}</tspan>" for t, stil in gruppen)
    return f'<text x="{x:.0f}" y="{y:.0f}" font-size="{groesse}" xml:space="preserve"{extra}>{tspans.rstrip()}</text>'


def fenster(hoehe: int, titel: str, befehl: str, argument: str) -> str:
    """Terminalfenster mit Titelleiste und Eingabezeile - der Rahmen jedes Abschnitts."""
    return f"""<g clip-path="url(#rahmen)">
  <rect width="{W}" height="{hoehe}" fill="{FLAECHE}"/>
  <rect width="{W}" height="48" fill="{GRUND}"/>
  <path d="M0 48.5h{W}" stroke="{LINIE}"/>
  <circle cx="30" cy="24" r="6" fill="#FF5F57"/><circle cx="50" cy="24" r="6" fill="#FEBC2E"/><circle cx="70" cy="24" r="6" fill="#28C840"/>
  <text x="{W / 2:.0f}" y="30" font-size="16" fill="{GRAU}" text-anchor="middle">{esc(titel)}</text>
  <text x="{RAND_X}" y="98" font-size="22"><tspan fill="{GRUEN}" font-weight="bold">$ </tspan><tspan fill="{GRUEN}" font-weight="bold">{esc(befehl)} </tspan><tspan fill="{WEISS}" font-weight="bold">{esc(argument)}</tspan></text>
"""


FENSTER_STIL = """  .rein { opacity: 0; animation: auftauchen .45s ease-out both; }
  @keyframes auftauchen { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
""" + BEWEGUNG_AUS

RAND_X = 60


def trennlinie(y: float) -> str:
    return f'<path d="M{RAND_X} {y:.0f}h{W - 2 * RAND_X}" stroke="{LINIE}" stroke-dasharray="2 6"/>'


def ueber_mich() -> str:
    """Begrüßung, Rollen, beide Absätze und die drei Punkte aus dem Profil."""
    teile: list[str] = []
    verz = iter(0.15 * n for n in range(40))

    def rein(inhalt: str) -> str:
        return f'  <g class="rein" style="animation-delay:{next(verz):.2f}s">{inhalt}</g>'

    y = 166
    gruss = UEBER["gruss"]
    teile.append(rein(f'<text x="{RAND_X}" y="{y}" font-size="48" font-weight="bold" fill="{WEISS}">{esc(gruss)}'
                      f'<tspan fill="{GRUEN}" class="cursor-text"> █</tspan></text>'))
    y += 44
    teile.append(rein(f'<text x="{RAND_X}" y="{y}" font-size="22" font-weight="bold" fill="{GRUEN}">'
                      f'{esc(UEBER["rollen"])}</text>'))
    y += 34
    teile.append(rein(f'<text x="{RAND_X}" y="{y}" font-size="20" fill="{GRAU}">{esc(UEBER["claim"])}</text>'))
    y += 38
    teile.append(trennlinie(y))
    y += 20

    groesse, zeilenhoehe = 21, 34
    max_zeichen = int((W - 2 * RAND_X) / (groesse * ZEICHEN_EM))
    for absatz in UEBER["absaetze"]:
        zeilen = umbrechen(absatz, max_zeichen)
        block = []
        for zeile in zeilen:
            y += zeilenhoehe
            block.append(textzeile(RAND_X, y, zeile, groesse))
        teile.append(rein("".join(block)))
        y += 20

    y += 6
    teile.append(trennlinie(y))
    y += 14
    einzug = RAND_X + 52
    max_punkt = int((W - einzug - RAND_X) / (groesse * ZEICHEN_EM))
    for zeichen, titel, rest in UEBER["punkte"]:
        block = []
        zeilen = umbrechen(f"**{titel}** {rest}", max_punkt)
        y += 48
        block.append(f'<rect x="{RAND_X}" y="{y - 25}" width="34" height="34" rx="9" fill="{GRUEN}" '
                     f'fill-opacity=".1" stroke="{GRUEN}" stroke-opacity=".5"/>' + symbol(zeichen, RAND_X + 17, y - 8))
        for i, zeile in enumerate(zeilen):
            block.append(textzeile(einzug, y + i * zeilenhoehe, zeile, groesse))
        y += (len(zeilen) - 1) * zeilenhoehe
        teile.append(rein("".join(block)))
    hoehe = y + 40

    nl = "\n"
    inhalt = (fenster(hoehe, "jacob@decoded: ~", "cat", "über-mich.md") + nl.join(teile) + "\n</g>\n" + rand(hoehe))
    label = " ".join([gruss, UEBER["rollen"], UEBER["claim"]]
                     + [AUSZEICHNUNG.sub(lambda m: m.group(0).strip("*="), a) for a in UEBER["absaetze"]]
                     + [f"{t} {AUSZEICHNUNG.sub(lambda m: m.group(0).strip('*='), r)}." for _, t, r in UEBER["punkte"]])
    return svg(hoehe, label, FENSTER_STIL + CURSOR_TEXT, verlaeufe(hoehe), inhalt)


def stack() -> str:
    """Technologien als Etiketten je Bereich, automatisch umbrochen."""
    groesse, zeilenhoehe, abstand = 19, 56, 22
    rechts = W - 48
    x_start = RAND_X + max(breite(b, 20) for b, _ in STACK) + 36

    gruppen, trenner, y = [], [], 132
    for n, (bereich, dinge) in enumerate(STACK):
        if n:
            trenner.append(trennlinie(y - abstand / 2 - 4))
        teile = [f'<text x="{RAND_X}" y="{y + 28}" font-size="20" font-weight="bold" fill="{GRUEN}">{esc(bereich)}</text>']
        x = x_start
        for ding in dinge:
            if x + breite(ding, groesse) + 36 > rechts:
                x, y = x_start, y + zeilenhoehe
            etikett, b = pille(x, y, ding, groesse)
            teile.append(etikett)
            x += b + 10
        gruppen.append(f'  <g class="rein" style="animation-delay:{0.15 + n * 0.15:.2f}s">{"".join(teile)}</g>')
        y += zeilenhoehe + abstand
    hoehe = y - abstand + 30

    nl = "\n"
    inhalt = (fenster(hoehe, "jacob@decoded: ~", "ls", "~/stack") + "  " + "".join(trenner) + nl
              + nl.join(gruppen) + "\n</g>\n" + rand(hoehe))
    label = "Technologien & Tools – " + "; ".join(f"{b}: {', '.join(d)}" for b, d in STACK)
    return svg(hoehe, label, FENSTER_STIL, verlaeufe(hoehe), inhalt)


# ---------------------------------------------------------------- Links und Fuß

def link(text: str, zeichen: str) -> str:
    """Einzelnes Link-Etikett für die Zeile unter der Begrüßung."""
    etikett, b = pille(1, 1, text, zeichen=zeichen)
    return svg(42, text, "", "", etikett + "\n", weite=round(b + 2))


def fuss() -> str:
    H = 110
    css, regen = matrix_regen(random.Random(3), H, dichte=.8, groesse=13)
    stil = css + CURSOR_TEXT + BEWEGUNG_AUS
    defs = verlaeufe(H) + f"""  <radialGradient id="mitte" cx=".5" cy=".5" r=".5">
    <stop offset="0" stop-color="{GRUND}" stop-opacity=".97"/><stop offset=".6" stop-color="{GRUND}" stop-opacity=".85"/>
    <stop offset="1" stop-color="{GRUND}" stop-opacity=".3"/>
  </radialGradient>
"""
    zeile2 = f"Danke fürs Vorbeischauen – mehr auf {WEBSITE}"
    inhalt = f"""<g clip-path="url(#rahmen)">
  <rect width="{W}" height="{H}" fill="{GRUND}"/>
{regen}
  <rect width="{W}" height="{H}" fill="url(#kanten)"/>
  <rect x="{W / 2 - 430:.0f}" y="0" width="860" height="{H}" fill="url(#mitte)"/>
  <text x="{W / 2:.0f}" y="48" font-size="20" text-anchor="middle" fill="{GRUEN}"><tspan font-weight="bold">$ exit</tspan><tspan class="cursor-text"> █</tspan></text>
  <text x="{W / 2:.0f}" y="80" font-size="16" fill="{GRAU}" text-anchor="middle">{esc(zeile2)}</text>
</g>
{rand(H)}"""
    return svg(H, zeile2, stil, defs, inhalt)


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
                        help="nur Köpfe, Stack und Fuß bauen (keine Netzabfragen)")
    args = parser.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)

    statisch = {f"link-{name}.svg": link(text, zeichen) for name, text, zeichen in LINKS}
    statisch |= {"ueber-mich.svg": ueber_mich(), "stack.svg": stack(), "fuss.svg": fuss()}
    for name, inhalt in statisch.items():
        if schreiben(ASSETS / name, inhalt):
            print(f"geschrieben: assets/{name}")
    if args.nur_statisch:
        return 0

    try:
        gh = github_daten(NUTZER)
        videos = youtube_videos(KANAL_ID)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, KeyError, ValueError) as fehler:
        # Altes Banner bleibt stehen; in der Action als Warnung sichtbar, nicht als Fehler
        print(f"::warning::Live-Daten nicht abrufbar, Banner bleibt unverändert: {fehler}")
        return 0

    # Fingerabdruck aus Daten und Skript: nur bei echten Änderungen neu schreiben
    daten = json.dumps({"gh": gh, "videos": videos}, sort_keys=True).encode()
    abdruck = hashlib.sha256(daten + Path(__file__).read_bytes()).hexdigest()[:16]
    ziel = ASSETS / "banner.svg"
    if ziel.exists() and f"<!-- daten:{abdruck} -->" in ziel.read_text(encoding="utf-8"):
        print("banner.svg: Daten unverändert")
        return 0
    inhalt = banner(gh, videos, datetime.now(timezone.utc)) + f"<!-- daten:{abdruck} -->\n"
    schreiben(ziel, inhalt)
    print(f"geschrieben: assets/banner.svg ({gh['repos']} Repos, {gh['sterne']} Sterne, "
          f"{gh['prs']} PRs, neuestes Video: {videos[0]['titel'] if videos else '–'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

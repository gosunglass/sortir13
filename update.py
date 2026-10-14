#!/usr/bin/env python3
"""Met à jour data/events.json : collecte les pages des sources, puis demande à Claude
d'en extraire les sorties et de les classer par profil (famille, jeune, senior)."""

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import anthropic
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "scripts" / "sources.json"
OUTPUT = ROOT / "data" / "events.json"

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
USER_AGENT = "Sorties13Bot/1.0 (agrégateur de sorties, contact : à renseigner)"
MAX_SUBPAGES = 4          # pages d'agenda suivies par source
CHUNK_CHARS = 35_000      # taille de texte envoyée à l'IA par appel
MAX_CHUNKS_PER_PAGE = 2
LINK_HINTS = re.compile(r"agenda|evenement|événement|sortir|programme|spectacle|a-voir|que-faire", re.I)
CATEGORIES = ["Musique", "Spectacle", "Exposition", "Nature", "Sport", "Visite",
              "Conférence", "Atelier", "Fête et marché", "Cinéma", "Soirée", "Autre"]

SYSTEM_PROMPT = f"""Tu extrais des sorties à partir du texte brut d'une page web de ville ou de tourisme, dans les Bouches-du-Rhône.
Réponds UNIQUEMENT par un tableau JSON, sans texte autour ni balises Markdown.
Chaque élément a exactement ces champs :
- title : titre de la sortie
- city : commune
- venue : lieu précis ("" si inconnu)
- date_start : "AAAA-MM-JJ"
- date_end : "AAAA-MM-JJ" (identique à date_start si un seul jour)
- time : horaire principal comme "20h30" ("" si inconnu)
- category : une valeur parmi {CATEGORIES}
- free : true si l'entrée est gratuite, sinon false
- price_label : tarif court comme "12 €" ("" si inconnu ou gratuit)
- url : lien direct vers la fiche de la sortie, tel qu'il apparaît dans les liens fournis ("" si absent)
- summary : une phrase de 200 caractères maximum, reformulée avec tes propres mots
- fit : objet avec trois notes entières de 0 à 3 pour "famille", "jeune" et "senior"
  (3 = très adapté, 0 = inadapté).
  famille : enfants présents, durée courte, horaires de jour ou début de soirée, tarifs doux.
  jeune : jeunes adultes et adultes actifs, concerts, soirées, festivals, sport, culture.
  senior : accessibilité, assise, horaires de journée, rythme calme, peu de station debout.
Règles : n'invente rien. Ignore ce qui n'est pas une sortie datée (pages institutionnelles, démarches).
Si l'année est absente, déduis-la de la date du jour. Ne garde que les sorties à venir ou en cours.
Si aucune sortie n'est présente, réponds []."""


def robots_ok(url: str, cache: dict) -> bool:
    parts = urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in cache:
        rp = robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None
        cache[base] = rp
    rp = cache[base]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def fetch(url: str, cache: dict):
    if not robots_ok(url, cache):
        print(f"  robots.txt interdit : {url}")
        return None
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def page_text(soup: BeautifulSoup, base_url: str) -> str:
    """Texte de la page, avec les liens inscrits à côté de leur intitulé."""
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form"]):
        tag.decompose()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href.startswith("http") and a.get_text(strip=True):
            a.replace_with(f"{a.get_text(' ', strip=True)} <{href}>")
    lines = [l.strip() for l in soup.get_text("\n").splitlines()]
    return "\n".join(l for l in lines if l)


def discover(soup: BeautifulSoup, base_url: str) -> list:
    host = urlparse(base_url).netloc
    found = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        if urlparse(href).netloc != host or href.rstrip("/") == base_url.rstrip("/"):
            continue
        if LINK_HINTS.search(href) or LINK_HINTS.search(a.get_text(" ", strip=True)):
            if href not in found:
                found.append(href)
    return found[:MAX_SUBPAGES]


def parse_json_list(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    return json.loads(text[start:end + 1])


def extract(client, text: str, source: dict, today: str):
    events = []
    for i in range(0, min(len(text), CHUNK_CHARS * MAX_CHUNKS_PER_PAGE), CHUNK_CHARS):
        chunk = text[i:i + CHUNK_CHARS]
        msg = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content":
                f"Date du jour : {today}\nSource : {source['name']} (commune par défaut : {source.get('city') or 'à déduire'})\n\n{chunk}"}],
        )
        try:
            events += parse_json_list("".join(b.text for b in msg.content if b.type == "text"))
        except json.JSONDecodeError as exc:
            print(f"  JSON invalide ignoré : {exc}")
    return events


def clean(raw: dict, source: dict, today: str):
    try:
        start = raw["date_start"]
        end = raw.get("date_end") or start
        dt.date.fromisoformat(start)
        dt.date.fromisoformat(end)
    except (KeyError, ValueError, TypeError):
        return None
    if end < today or not raw.get("title"):
        return None
    fit = raw.get("fit") or {}
    return {
        "title": str(raw["title"]).strip(),
        "city": str(raw.get("city") or source.get("city") or "").strip(),
        "venue": str(raw.get("venue") or "").strip(),
        "date_start": start,
        "date_end": end,
        "time": str(raw.get("time") or "").strip(),
        "category": raw.get("category") if raw.get("category") in CATEGORIES else "Autre",
        "free": bool(raw.get("free")),
        "price_label": str(raw.get("price_label") or "").strip(),
        "url": str(raw.get("url") or "").strip(),
        "source": source["name"],
        "summary": str(raw.get("summary") or "").strip()[:240],
        "fit": {k: max(0, min(3, int(fit.get(k, 0) or 0))) for k in ("famille", "jeune", "senior")},
    }


def dedupe(events: list) -> list:
    seen = {}
    for e in events:
        key = (re.sub(r"\W+", "", e["title"].lower()), e["date_start"], e["city"].lower())
        # en cas de doublon, on garde la fiche la plus complète
        if key not in seen or len(e["summary"]) > len(seen[key]["summary"]):
            seen[key] = e
    return list(seen.values())


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY manquante.")
        return 1
    client = anthropic.Anthropic()
    today = dt.date.today().isoformat()
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]

    previous = []
    if OUTPUT.exists():
        previous = json.loads(OUTPUT.read_text(encoding="utf-8")).get("events", [])

    robots_cache, collected, failed = {}, [], set()
    for src in sources:
        print(f"[{src['name']}]")
        try:
            home = fetch(src["url"], robots_cache)
            if home is None:
                failed.add(src["name"])
                continue
            urls = [src["url"]] + discover(home, src["url"])
            before = len(collected)
            for url in urls:
                soup = home if url == src["url"] else fetch(url, robots_cache)
                if soup is None:
                    continue
                for raw in extract(client, page_text(soup, url), src, today):
                    event = clean(raw, src, today)
                    if event:
                        collected.append(event)
                time.sleep(1)  # politesse envers les sites
            print(f"  {len(collected) - before} sorties")
        except Exception as exc:  # une source en panne ne doit pas bloquer les autres
            print(f"  échec : {exc}")
            failed.add(src["name"])

    # Les sources en échec gardent leurs sorties de la veille (si pas encore passées).
    for e in previous:
        if e.get("source") in failed and (e.get("date_end") or e["date_start"]) >= today:
            collected.append(e)

    events = dedupe(collected)
    if not events:
        print("Aucune sortie collectée : le fichier existant est conservé.")
        return 1

    events.sort(key=lambda e: (e["date_start"], e["title"]))
    for n, e in enumerate(events, 1):
        e["id"] = f"e{n}"
    OUTPUT.write_text(json.dumps({
        "demo": False,
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "events": events,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(events)} sorties écrites dans {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

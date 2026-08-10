#!/usr/bin/env python3
"""
Bot de novetats i resultats del CE Sabadell per a X (Twitter).

Flux:
  1. Recull articles PUBLICATS AVUI de fonts fiables (Marca, As, Sport, Mundo
     Deportivo, Google News general, i la web oficial del club).
  2. Descarta els que no siguin d'avui i els que ja s'han publicat abans
     (fitxer posted.json).
  3. Formata un tuit per a cada novetat nova (títol al post, enllaç en fil).
  4. Publica via l'API de Postproxy (que ja té el compte de X connectat).
  5. Desa l'estat perquè no es repeteixin publicacions en la propera execució.

Pensat per executar-se cada hora (veure .github/workflows/bot.yml): a cada
execució només publica novetats que encara no s'havien vist.

Variables d'entorn necessàries:
  POSTPROXY_API_KEY   -> clau de l'API de Postproxy (Settings > API Keys al dashboard)
  POSTPROXY_PROFILE    -> id o nom del perfil de X a Postproxy.

Configuració editable més avall a CONFIG.
"""

import os
import re
import sys
import json
import time
import html
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

# Fus horari de referència per decidir què compta com "d'avui".
LOCAL_TZ = ZoneInfo("Europe/Madrid")

# ─────────────────────────────────────────────────────────────────────────
# CONFIG — edita aquí segons les teves preferències
# ─────────────────────────────────────────────────────────────────────────

CONFIG = {
    # Fonts RSS. Es fan servir cerques de Google News acotades a cada mitjà
    # (site:...) per assegurar cobertura de premsa esportiva de referència,
    # més una cerca general i la web oficial del club.
    "sources": [
        {
            "name": "Marca",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+site:marca.com+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "As",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+site:as.com+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "Sport",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+site:sport.es+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "Mundo Deportivo",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+site:mundodeportivo.com+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "BeSoccer",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+site:besoccer.com+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "El Desmarque",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+site:eldesmarque.com+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "Cadena SER",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+%22futbol%22+site:cadenaser.com+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "Cadena COPE",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+%22futbol%22+site:cope.es+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "LaLiga Hypermotion (oficial)",
            "url": "https://news.google.com/rss/search?q=%22Sabadell%22+site:laliga.com+when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "Google News - CE Sabadell (general)",
            "url": "https://news.google.com/rss/search?q=%22CE%20Sabadell%22%20OR%20%22Centre%20d%27Esports%20Sabadell%22%20when:1d&hl=ca&gl=ES&ceid=ES:ca",
        },
        {
            "name": "Web oficial CE Sabadell",
            "url": "https://www.cesabadellfc.com/es/feed/",
        },
    ],
    # Nombre màxim de tuits nous que es publiquen en una sola execució.
    # Com que ara corre cada hora, n'hi ha prou amb un marge petit.
    "max_posts_per_run": 5,
    # Si és True, només es publiquen articles amb pubDate d'avui (hora local
    # Europe/Madrid). Els articles sense data reconeguda es descarten per
    # seguretat quan aquesta opció està activada.
    "only_today": True,
    # Fitxer on es guarden els enllaços ja publicats, per no repetir-los.
    "state_file": "posted.json",
    # Quants dies de "memòria" es conserven al fitxer d'estat (neteja automàtica).
    "state_retention_days": 30,
    # Perfil de destí a Postproxy. Pot ser "twitter" (agafa el primer perfil
    # de X connectat) o l'id concret del perfil si en tens més d'un.
    # Nota: fem servir "or" i no el segon argument de os.environ.get(), perquè
    # GitHub Actions passa la variable com a cadena buida si no s'ha definit
    # (no com a variable absent), i el segon argument de .get() només actua
    # quan la clau no existeix.
    "postproxy_profile": os.environ.get("POSTPROXY_PROFILE") or "twitter",
}

POSTPROXY_API_URL = "https://api.postproxy.dev/api/posts"

# ─────────────────────────────────────────────────────────────────────────
# Utilitats
# ─────────────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(f"[bot] {msg}", flush=True)


def clean_html(raw: str) -> str:
    """Treu etiquetes HTML i descodifica entitats d'un fragment de text."""
    text = re.sub(r"<[^>]+>", "", raw or "")
    return html.unescape(text).strip()


def fetch_rss(url: str, name: str):
    """Descarrega i parseja un feed RSS. Retorna una llista d'items normalitzats."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (CE-Sabadell-Bot)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
    except Exception as e:
        log(f"AVÍS: no s'ha pogut llegir la font '{name}': {e}")
        return []

    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        log(f"AVÍS: XML invàlid a '{name}': {e}")
        return []

    items = []
    for item in root.iter("item"):
        title = clean_html(item.findtext("title", default=""))
        link = (item.findtext("link", default="") or "").strip()
        desc = clean_html(item.findtext("description", default=""))
        pub = item.findtext("pubDate", default="")
        if not title or not link:
            continue
        items.append({
            "source": name,
            "title": title,
            "link": link,
            "summary": desc,
            "pub_date": pub,
        })
    return items


def is_from_today(item: dict) -> bool:
    """Comprova si el pubDate de l'article correspon al dia d'avui, en hora
    local (Europe/Madrid). Si no es pot interpretar la data, es descarta
    l'article (millor perdre'n un que publicar-ne un de vell per error)."""
    raw = item.get("pub_date", "")
    if not raw:
        return False
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(LOCAL_TZ)
    today_local = datetime.now(LOCAL_TZ).date()
    return local_dt.date() == today_local


def looks_relevant(item: dict) -> bool:
    """Filtre de rellevància en dos nivells, per evitar notícies locals de
    Sabadell (ciutat) que no tenen res a veure amb el club de futbol:

      1. Si el text conté un identificador inequívoc del club (p. ex.
         "CE Sabadell", "Arlequinat", "Centre d'Esports", "Nova Creu Alta"),
         es considera rellevant directament.
      2. Si només conté "Sabadell" a soles, cal que aparegui també
         vocabulari futbolístic/de Lliga Hypermotion — així es descarten
         notícies de successos, ajuntament, cultura, etc. de la ciutat.
    """
    text = f"{item['title']} {item['summary']}".lower()

    club_identifiers = [
        "ce sabadell", "c.e. sabadell", "arlequinat", "nova creu alta",
        "centre d'esports", "centre d'esports sabadell",
    ]
    if any(k in text for k in club_identifiers):
        return True

    if "sabadell" not in text:
        return False

    football_context = [
        "liga hypermotion", "lliga hypermotion", "segunda división",
        "segunda divisió", "futbol", "fútbol", "partido", "partit",
        "gol", "gols", "goles", "golejada", "jornada", "entrenador",
        "fitxatge", "fitxatges", "fichaje", "fichajes", "pretemporada",
        "davanter", "porteria", "porter", "lliga", "liga", "clasificación",
        "classificació", "estadi", "estadio",
    ]
    return any(k in text for k in football_context)


def item_id(item: dict) -> str:
    """Identificador estable per detectar duplicats (hash de l'enllaç)."""
    return hashlib.sha256(item["link"].encode("utf-8")).hexdigest()


def load_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def prune_state(state: dict, retention_days: int) -> dict:
    cutoff = time.time() - retention_days * 86400
    return {k: v for k, v in state.items() if v.get("posted_at", 0) >= cutoff}


def build_tweet(item: dict):
    """Construeix el text del tuit principal i el de la resposta amb l'enllaç.

    X no permet enllaços al cos del primer post via Postproxy; cal publicar-lo
    com una resposta en fil (thread). Retorna (text_principal, text_enllaç).
    """
    title = item["title"].strip()
    link = item["link"].strip()
    max_title_len = 280
    if len(title) > max_title_len:
        title = title[: max_title_len - 1].rstrip() + "…"
    return title, link


def post_to_x(text: str, link: str, api_key: str, profile: str) -> bool:
    payload = {
        "post": {"body": text},
        "profiles": [profile],
        "thread": [{"body": link}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(POSTPROXY_API_URL, headers=headers, json=payload, timeout=30)
    except requests.RequestException as e:
        log(f"ERROR de xarxa publicant a Postproxy: {e}")
        return False

    if resp.status_code >= 300:
        log(f"ERROR Postproxy ({resp.status_code}): {resp.text[:500]}")
        return False

    log(f"Publicat correctament: {text.splitlines()[0][:80]}...")
    return True


# ─────────────────────────────────────────────────────────────────────────
# Programa principal
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    api_key = os.environ.get("POSTPROXY_API_KEY")
    if not api_key:
        log("ERROR: falta la variable d'entorn POSTPROXY_API_KEY.")
        return 1

    state_path = CONFIG["state_file"]
    state = load_state(state_path)
    state = prune_state(state, CONFIG["state_retention_days"])

    all_items = []
    for source in CONFIG["sources"]:
        items = fetch_rss(source["url"], source["name"])
        log(f"Font '{source['name']}': {len(items)} articles trobats.")
        all_items.extend(items)

    # Filtra rellevància + duplicats ja publicats
    new_items = []
    for item in all_items:
        if not looks_relevant(item):
            continue
        if CONFIG["only_today"] and not is_from_today(item):
            continue
        iid = item_id(item)
        if iid in state:
            continue
        new_items.append((iid, item))

    # Evita duplicats dins la mateixa execució (mateixa notícia a dues fonts)
    seen_titles = set()
    dedup_items = []
    for iid, item in new_items:
        key = item["title"].lower().strip()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        dedup_items.append((iid, item))

    log(f"Novetats no publicades encara: {len(dedup_items)}")

    to_publish = dedup_items[: CONFIG["max_posts_per_run"]]
    if not to_publish:
        log("Res nou per publicar en aquesta execució.")
        save_state(state_path, state)
        return 0

    published_count = 0
    for iid, item in to_publish:
        tweet_text, tweet_link = build_tweet(item)
        ok = post_to_x(tweet_text, tweet_link, api_key, CONFIG["postproxy_profile"])
        if ok:
            state[iid] = {
                "title": item["title"],
                "link": item["link"],
                "source": item["source"],
                "posted_at": time.time(),
            }
            published_count += 1
            time.sleep(3)  # marge petit entre publicacions
        else:
            log(f"No s'ha pogut publicar: {item['title']}")

    save_state(state_path, state)
    log(f"Fet. Publicats {published_count}/{len(to_publish)} tuits nous.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

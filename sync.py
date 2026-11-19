#!/usr/bin/env python3
"""Read public Webador articles into a local catalogue and serve the prototype.

This is a local proof of concept. It only reads the public site and writes JSON
under this prototype directory. It never logs in, posts, or edits Webador.
Requires Python 3.9+ and Playwright (`python3 -m pip install playwright`).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ORIGIN = "https://www.tresors-spirituels.net"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CATALOG_PATH = DATA_DIR / "articles.json"
STATUS_PATH = DATA_DIR / "sync-status.json"
ARTICLE_SEGMENT = re.compile(r"^\d+_")
LABELS = {
    "confidences": "Confidences",
    "vie-de-femmes": "Vie de femmes",
    "tresors-de-la-bible": "Trésors de la Bible",
    "batir-sa-maison": "Bâtir sa Maison",
    "une-lettre-pour-toi": "Une lettre pour toi",
    "citations": "Citations",
    "tu-dis-alors-je-prie": "Tu dis… alors je prie",
    "poemes": "Poèmes",
    "sources-d-inspiration": "Sources d’inspiration",
    "vitamines": "Vitamines",
    "histoires": "Histoires",
    "temoignages": "Témoignages",
    "droleries": "Drôleries",
}
MONTHS = {
    "janv": 1, "janvier": 1, "févr": 2, "fevr": 2, "février": 2,
    "mars": 3, "avr": 4, "avril": 4, "mai": 5, "juin": 6,
    "juil": 7, "juillet": 7, "août": 8, "aout": 8, "sept": 9,
    "septembre": 9, "oct": 10, "octobre": 10, "nov": 11,
    "novembre": 11, "déc": 12, "dec": 12, "décembre": 12,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("tresors-sync")


def parse_date(value: str) -> tuple[str, str]:
    """Return (display, sortable ISO value) for the French dates Webador shows."""
    display = " ".join((value or "").split())
    match = re.search(r"(\d{1,2})\s+([A-Za-zÀ-ÿ.]+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", display)
    if not match:
        return display, ""
    day, month_name, year, hour, minute = match.groups()
    month = MONTHS.get(month_name.lower().rstrip("."))
    if not month:
        return display, ""
    try:
        stamp = datetime(int(year), month, int(day), int(hour or 0), int(minute or 0))
    except ValueError:
        return display, ""
    return display, stamp.isoformat(timespec="minutes")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def category_routes(urls: list[str]) -> list[str]:
    routes = []
    for url in urls:
        parts = [part for part in urlparse(url).path.split("/") if part]
        if urlparse(url).scheme != "https" or urlparse(url).netloc != "www.tresors-spirituels.net" or not parts or len(parts) > 3 or any(ARTICLE_SEGMENT.match(part) for part in parts):
            continue
        if any(part in LABELS for part in parts):
            routes.append(url)
    return list(dict.fromkeys(routes))


def article_url(url: str, base: str) -> bool:
    parsed = urlparse(url)
    root = urlparse(base)
    parts = [part for part in parsed.path.split("/") if part]
    base_parts = [part for part in root.path.split("/") if part]
    return (
        parsed.scheme == "https"
        and parsed.netloc == root.netloc == "www.tresors-spirituels.net"
        and len(parts) >= 2
        and parts[:-1] == base_parts[:len(parts) - 1]
        and bool(ARTICLE_SEGMENT.match(parts[-1]))
    )


def clean_text(text: str) -> str:
    return " ".join((text or "").split())


def extract_card(card: dict[str, str], category: str, category_url: str) -> dict[str, Any] | None:
    url = card.get("url", "")
    if not article_url(url, category_url):
        return None
    title = clean_text(card.get("title", ""))
    if not title:
        return None
    date_display, date_sort = parse_date(card.get("date", ""))
    date_short = re.sub(r"\s+\d{1,2}:\d{2}$", "", date_display)
    return {
        "id": url.rstrip("/").rsplit("/", 1)[-1],
        "url": url,
        "title": title,
        "category": category,
        "categoryUrl": category_url,
        "date": date_short,
        "published": date_display,
        "publishedSort": date_sort,
        "excerpt": clean_text(card.get("excerpt", "")),
        "image": card.get("image", ""),
        "blocks": [],
    }


def playwright_api():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright manque. Installe-le avec « python3 -m pip install playwright », "
            "puis « python3 -m playwright install chromium »."
        ) from exc


def sync_once(max_articles: int = 300) -> dict[str, Any]:
    """Refresh listings, fetch new articles and revisit the latest cards for edits."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    old = read_json(CATALOG_PATH, {"articles": []})
    known = {item.get("url"): item for item in old.get("articles", []) if item.get("url")}
    sync_playwright = playwright_api()
    listing_by_url: dict[str, dict[str, Any]] = {}
    category_order: list[str] = []
    errors: list[str] = []
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

    with sync_playwright() as p:
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        launch_options: dict[str, Any] = {"headless": True}
        if executable:
            launch_options["executable_path"] = executable
        browser = p.chromium.launch(**launch_options)
        page = browser.new_page(locale="fr-FR")
        page.set_default_timeout(20000)
        try:
            page.goto(f"{ORIGIN}/sitemap.xml", wait_until="domcontentloaded")
            root = ET.fromstring(page.content())
            sitemap_urls = [node.text.strip() for node in root.iter() if node.tag.endswith("loc") and node.text]
            routes = category_routes(sitemap_urls)
            if not routes:
                raise RuntimeError("Le sitemap ne contient aucune rubrique candidate.")

            for route in routes:
                try:
                    page.goto(route, wait_until="domcontentloaded"); route = page.url.rstrip("/")
                    page.locator("main, #main-content").first.wait_for(state="attached")
                    page_count = page.locator(".jw-pagination").count()
                    total = int(page.locator(".jw-pagination").get_attribute("data-page-total") or "1") if page_count else 1
                    heading = page.locator("#main-content h1").first
                    heading_text = clean_text(heading.inner_text()) if heading.count() else ""
                    path_parts = [part for part in urlparse(route).path.split("/") if part]
                    category = next((LABELS[part] for part in path_parts if part in LABELS), heading_text or path_parts[-1].replace("-", " ").title())
                    found = 0
                    for page_number in range(1, total + 1):
                        if page_number > 1:
                            page.locator(f'.jw-pagination a[data-page="{page_number}"]').click()
                            page.wait_for_function(
                                "n => document.querySelector('.jw-pagination')?.getAttribute('data-page-current') === String(n)",
                                arg=page_number,
                            )
                        cards = page.locator("article.jw-news-post").evaluate_all(
                            "nodes => nodes.map(card => ({"
                            "url: card.querySelector('a[data-segment-type=post]')?.href || '',"
                            "title: card.querySelector('.jw-news-post__title')?.innerText || '',"
                            "date: card.querySelector('.jw-news-post__meta')?.innerText || '',"
                            "excerpt: card.querySelector('.jw-news-post__lead')?.innerText || '',"
                            "image: card.querySelector('.jw-news-post__image img')?.currentSrc || ''"
                            "}))"
                        )
                        for card in cards:
                            record = extract_card(card, category, route)
                            if record:
                                listing_by_url[record["url"]] = record
                                found += 1
                    if found:
                        category_order.append(route)
                        LOG.info("Rubrique %s : %s articles listés, %s pages", category, found, total)
                except Exception as exc:  # continue other public categories when one page changes/fails
                    errors.append(f"{route}: {type(exc).__name__}: {exc}")
                    LOG.warning("Rubrique ignorée après erreur: %s (%s)", route, exc)

            if not listing_by_url:
                raise RuntimeError("Aucun article valide extrait; le catalogue précédent est conservé.")

            new_urls = [url for url in listing_by_url if url not in known]
            refresh_urls: list[str] = []
            for route in category_order:
                category_items = [item for item in listing_by_url.values() if item["categoryUrl"] == route]
                category_items.sort(key=lambda item: item.get("publishedSort", ""), reverse=True)
                refresh_urls.extend(item["url"] for item in category_items[:2])
            candidates = list(dict.fromkeys(new_urls + refresh_urls))
            candidates.sort(
                key=lambda url: (listing_by_url[url].get("publishedSort", ""), url in known),
                reverse=True,
            )
            wanted = candidates[:max(1, max_articles)]
            LOG.info("Fiches à récupérer ou actualiser : %s (nouveautés détectées : %s)", len(wanted), len(new_urls))

            current = {url: {**known[url], **listing_by_url[url], "blocks": known[url].get("blocks", [])} for url in known.keys() & listing_by_url.keys()}
            for index, url in enumerate(wanted, start=1):
                listing = listing_by_url[url]
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    body = page.locator("#main-content .news-page-content-container")
                    body.wait_for(state="visible")
                    detail = page.evaluate("""() => {
                      const main = document.querySelector('#main-content');
                      const body = main?.querySelector('.news-page-content-container');
                      if (!main || !body) return null;
                      const heading = main.querySelector('h1');
                      const published = main.innerText.match(/Publié le\\s+([^\\n]+)/i)?.[1] || '';
                      const blocks = [];
                      for (const node of body.querySelectorAll('h2,h3,h4,p,ul,ol,blockquote,img')) {
                        const tag = node.tagName.toLowerCase();
                        if (tag === 'img') {
                          const src = node.currentSrc || node.src;
                          if (src) blocks.push({type:'image', src, alt:node.alt || ''});
                        } else if (tag === 'ul' || tag === 'ol') {
                          const items = [...node.querySelectorAll(':scope > li')].map(x => x.innerText.trim()).filter(Boolean);
                          if (items.length) blocks.push({type:'list', ordered:tag === 'ol', items});
                        } else {
                          const text = node.innerText.trim();
                          if (!text) continue;
                          const type = tag === 'blockquote' ? 'quote' : (tag[0] === 'h' ? 'heading' : 'paragraph');
                          blocks.push({type, level:type === 'heading' ? Number(tag.slice(1)) : 0, text});
                        }
                      }
                      return {title:heading?.innerText.trim() || '', published, blocks};
                    }""")
                    if not detail or not detail.get("title") or not detail.get("blocks"):
                        raise RuntimeError("Titre ou contenu manquant")
                    published, published_sort = parse_date(detail.get("published", ""))
                    record = dict(listing)
                    record.update({
                        "title": detail["title"],
                        "date": published or listing.get("date", ""),
                        "published": detail.get("published") or listing.get("published", ""),
                        "publishedSort": published_sort or listing.get("publishedSort", ""),
                        "blocks": detail["blocks"],
                        "syncedAt": timestamp,
                        "source": "Webador public",
                    })
                    images = [block["src"] for block in detail["blocks"] if block.get("type") == "image"]
                    if images:
                        record["image"] = images[0]
                    record["excerpt"] = listing.get("excerpt") or next(
                        (block["text"] for block in detail["blocks"] if block.get("type") == "paragraph"), ""
                    )
                    current[url] = record
                    LOG.info("[%s/%s] synchronisé : %s", index, len(wanted), record["title"])
                    time.sleep(0.25)
                except Exception as exc:
                    errors.append(f"{url}: {type(exc).__name__}: {exc}")
                    LOG.warning("Article conservé sans actualisation: %s (%s)", url, exc)

            ordered = sorted(
                current.values(),
                key=lambda item: (item.get("publishedSort", ""), item.get("title", "")),
                reverse=True,
            )
            catalog = {
                "source": ORIGIN,
                "syncedAt": timestamp,
                "categories": sorted(set(LABELS.values()), key=str.casefold),
                "listedArticles": len(listing_by_url),
                "storedArticles": len(ordered),
                "articles": ordered,
            }
            write_json_atomic(CATALOG_PATH, catalog)
            status = {
                "ok": not errors,
                "syncedAt": timestamp,
                "listedArticles": len(listing_by_url),
                "storedArticles": len(ordered),
                "newArticles": len([url for url in new_urls if url in current]),
                "errors": errors,
            }
            write_json_atomic(STATUS_PATH, status)
            return status
        finally:
            browser.close()


class PrototypeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/api/articles.json":
            path = CATALOG_PATH
        elif self.path.split("?", 1)[0] == "/api/status.json":
            path = STATUS_PATH
        else:
            return super().do_GET()
        payload = path.read_bytes() if path.exists() else b'{"articles":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(port: int, interval_hours: float, max_articles: int) -> None:
    LOG.info("Synchronisation initiale avant ouverture du prototype")
    sync_once(max_articles)
    stop = threading.Event()

    def repeat_sync() -> None:
        while not stop.wait(max(0.25, interval_hours) * 3600):
            try:
                sync_once(max_articles)
            except Exception:
                LOG.exception("Échec de la synchronisation; les données précédentes restent servies")

    worker = threading.Thread(target=repeat_sync, name="webador-sync", daemon=True)
    worker.start()
    server = ThreadingHTTPServer(("127.0.0.1", port), PrototypeHandler)
    LOG.info("Prototype local : http://127.0.0.1:%s/index.html", port)
    LOG.info("Actualisation automatique toutes les %.1f heures pendant que ce programme tourne", interval_hours)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Arrêt demandé")
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronisation locale du site Trésors spirituels")
    parser.add_argument("--serve", action="store_true", help="synchroniser périodiquement et servir l’aperçu local")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval-hours", type=float, default=6)
    parser.add_argument("--max-articles", type=int, default=300, help="maximum de fiches complètes par cycle")
    args = parser.parse_args()
    if args.serve:
        serve(args.port, args.interval_hours, args.max_articles)
    else:
        result = sync_once(args.max_articles)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

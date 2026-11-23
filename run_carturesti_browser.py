"""Scraper Cărturești cu browser Chrome/Chromium (randare JavaScript).

Exemple:
  python run_carturesti_browser.py --queries fantasy thriller --pages 2 --limit 50
  python run_carturesti_browser.py --urls-file urls_carturesti.txt
  python run_carturesti_browser.py --probe "https://carturesti.ro/carte/..."

Folosește Selenium Manager pentru driverul Chrome. Dacă site-ul afișează o
pagină de refuz/captcha, oprește colectarea; nu încearcă să o ocolească.
"""
import argparse
import csv
import logging
import time
from pathlib import Path
from urllib.parse import quote_plus

from book_scraper.extract import Book, parse_product
from book_scraper.sites import SITES, extract_links

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("carturesti.browser")
SITE = SITES["carturesti"]
FIELDS = list(Book().to_row().keys())
CATEGORY_ROUTES = {
    "fantasy": "/raft/fantasy-1181214",
    "romance": "/raft/romance-187",
    "thriller": "/raft/thriller-horror-181",
    "sf": "/raft/sf-183",
    "sci-fi": "/raft/sf-183",
    "science fiction": "/raft/sf-183",
    "istorie": "/raft/istorie-196",
    "history": "/raft/istorie-196",
}


def blocked_page(driver):
    title = (driver.title or "").lower()
    body = driver.find_element("tag name", "body").text.lower()
    return any(term in title or term in body[:5000]
               for term in ("access denied", "403 forbidden", "captcha", "verify you are human"))


def open_page(driver, url, delay):
    driver.get(url)
    time.sleep(delay)
    if blocked_page(driver):
        raise RuntimeError(f"Cărturești a afișat un refuz/captcha pentru {url}; am oprit scraperul.")
    return driver.page_source


def discover(driver, query, pages, delay):
    seen = set()
    for page in range(1, pages + 1):
        category = CATEGORY_ROUTES.get(query.strip().lower())
        url = (f"{SITE.base}{category}?page={page}" if category else
               SITE.search_url.format(q=quote_plus(query), page=page))
        html = open_page(driver, url, delay)
        links = [link for link in extract_links(html, url, SITE) if link not in seen]
        if not links:
            log.warning("0 linkuri de produs găsite la căutarea %r, pagina %d (%s)", query, page, url)
            return
        seen.update(links)
        yield from links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", nargs="+", default=["fantasy", "romance", "thriller", "sf", "istorie"])
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--limit", type=int, default=200, help="maxim de cărți în această rulare")
    parser.add_argument("--urls-file", help="URL-uri de produs, câte unul pe linie")
    parser.add_argument("--out", default="data/carturesti.csv")
    parser.add_argument("--delay", type=float, default=5.0, help="pauză între pagini încărcate")
    parser.add_argument("--headless", action="store_true", help="rulează Chrome fără fereastră")
    parser.add_argument("--probe", help="încarcă și afișează câmpurile unui singur produs")
    args = parser.parse_args()

    try:
        from selenium import webdriver
    except ImportError as exc:
        raise SystemExit("Lipsește Selenium. Instalează dependențele cu: pip install -r requirements.txt") from exc

    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless=new")
    options.add_argument("--lang=ro-RO")
    driver = webdriver.Chrome(options=options)
    try:
        if args.probe:
            html = open_page(driver, args.probe, args.delay)
            book = parse_product(html, args.probe, SITE.name, SITE.platform,
                                 SITE.default_lang, SITE.genres_selector, SITE.price_selector)
            if not book:
                print("Pagina s-a încărcat, dar nu am putut extrage o carte din HTML.")
                return
            for key, value in book.to_row().items():
                print(f"  {key:18} {value!r}")
            return

        if args.urls_file:
            candidates = [line.strip() for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines()
                          if line.strip() and "carturesti.ro/" in line]
        else:
            candidates = []
            for query in args.queries:
                candidates.extend(discover(driver, query, args.pages, args.delay))

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        new_file = not out.exists() or out.stat().st_size == 0
        count, seen = 0, set()
        with out.open("a", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            for url in candidates:
                if count >= args.limit or url in seen:
                    continue
                seen.add(url)
                html = open_page(driver, url, args.delay)
                book = parse_product(html, url, SITE.name, SITE.platform,
                                     SITE.default_lang, SITE.genres_selector, SITE.price_selector)
                if not book:
                    log.info("nu am extras date de produs: %s", url)
                    continue
                writer.writerow(book.to_row())
                stream.flush()
                count += 1
                log.info("%d/%d %s", count, args.limit, book.titlu)
        log.info("Gata: %s (%d cărți)", out, count)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()

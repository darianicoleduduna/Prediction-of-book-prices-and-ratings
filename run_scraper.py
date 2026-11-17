"""Utilizare:
  python run_scraper.py --sites libris elefant --queries fantasy thriller --pages 3 --limit 100
  python run_scraper.py --probe https://www.libris.ro/<pagina-de-produs>      # diagnostic
  python run_scraper.py --sites goodreads --urls-file urls.txt                # URL-uri date manual
"""
import argparse
import csv
import logging
import random
from pathlib import Path
from urllib.parse import quote_plus

from book_scraper.enrich import enrich_from_goodreads
from book_scraper.extract import Book, parse_product
from book_scraper.http import PoliteClient, BlockedError
from book_scraper.sites import SITES, extract_links

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scraper")
FIELDS = list(Book().to_row().keys())


def load_proxies(path):
    p = Path(path)
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text().splitlines() if l.strip() and not l.startswith("#")]


def build_client(args):
    return PoliteClient(
        min_delay=args.min_delay, max_delay=args.max_delay,
        domain_delays={s.base.split("//")[1].replace("www.", ""): s.delay for s in SITES.values()},
        proxies=load_proxies(args.proxies), cache_dir=args.cache,
        respect_robots=not args.ignore_robots)


def discover(client, site, query, pages):
    seen = set()
    for page in range(1, pages + 1):
        html = client.get(site.search_url.format(q=quote_plus(query), page=page))
        if not html:
            log.warning("[%s] nu am primit pagina: %s", site.name, site.search_url.format(q=query, page=page))
            return
        new = [l for l in extract_links(html, site.search_url, site) if l not in seen]
        if not new:
            log.warning("[%s] 0 linkuri de produs gasite (pagina %d, query=%s) - verifica search_url/product_re",
                        site.name, page, query)
            return
        seen.update(new)
        yield from new


def probe(client, url):
    site = next((s for s in SITES.values() if s.base.split("//")[1].replace("www.", "") in url), None)
    html = client.get(url, use_cache=False)
    if not html:
        print("Nu am putut descarca pagina."); return
    print(f"HTML: {len(html)} caractere, JSON-LD: {'application/ld+json' in html}")
    b = parse_product(html, url, site.name if site else "?", site.platform if site else "",
                      site.default_lang if site else "", site.genres_selector if site else None,
                      site.price_selector if site else None)
    if not b:
        print("NU pare pagina de produs (sau continutul e incarcat din JavaScript)."); return
    for k, v in b.to_row().items():
        print(f"  {k:18} {v!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=[s for s in SITES if s != "goodreads"], choices=list(SITES))
    ap.add_argument("--no-goodreads", action="store_true", help="nu completa rating/keywords din Goodreads")
    ap.add_argument("--gr-min-match", type=float, default=0.6, help="similaritate minima titlu (0-1)")
    ap.add_argument("--queries", nargs="+", default=["fantasy", "romance", "thriller", "sf", "istorie"])
    ap.add_argument("--pages", type=int, default=2, help="pagini de rezultate / query")
    ap.add_argument("--limit", type=int, default=200, help="max carti / site")
    ap.add_argument("--urls-file", help="fisier cu URL-uri de produs (unul pe linie)")
    ap.add_argument("--out", default="data/books.csv")
    ap.add_argument("--proxies", default="proxies.txt")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--min-delay", type=float, default=3.0)
    ap.add_argument("--max-delay", type=float, default=9.0)
    ap.add_argument("--ignore-robots", action="store_true")
    ap.add_argument("--probe")
    args = ap.parse_args()

    client = build_client(args)
    if args.probe:
        return probe(client, args.probe)

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        with out.open(encoding="utf-8-sig", newline="") as f:
            done = {r["url"] for r in csv.DictReader(f)}
    new_file = not out.exists()
    manual = [l.strip() for l in Path(args.urls_file).read_text().splitlines() if l.strip()] if args.urls_file else []

    with out.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        sites = list(args.sites); random.shuffle(sites)   # alternam ordinea intre rulari
        for name in sites:
            site, count = SITES[name], 0
            def urls():
                yield from (u for u in manual if site.base.split("//")[1].replace("www.", "") in u)
                if not args.urls_file:
                    for q in args.queries:
                        yield from discover(client, site, q, args.pages)
            try:
                for url in urls():
                    if count >= args.limit:
                        break
                    if url in done:
                        continue
                    html = client.get(url)
                    done.add(url)
                    if not html:
                        continue
                    book = parse_product(html, url, site.name, site.platform,
                                         site.default_lang, site.genres_selector, site.price_selector)
                    if book:
                        if not args.no_goodreads and name != "goodreads":
                            ok = enrich_from_goodreads(client, book, args.gr_min_match)
                            if not ok:
                                log.info("[%s] fara potrivire pe Goodreads: %s", name, book.titlu)
                        w.writerow(book.to_row()); f.flush(); count += 1
                        log.info("[%s] %d/%d %s", name, count, args.limit, book.titlu)
            except BlockedError as e:
                log.error("Opresc %s: %s. Incearca mai tarziu / delay mai mare / proxy.", name, e)
    log.info("Gata: %s", out)


if __name__ == "__main__":
    main()
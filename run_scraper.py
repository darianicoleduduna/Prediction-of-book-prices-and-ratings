"""Utilizare:
  python run_scraper.py --sites libris elefant --queries fantasy thriller --pages 3 --limit 100
  python run_scraper.py --probe https://www.libris.ro/<pagina-de-produs>      # diagnostic
  python run_scraper.py --sites goodreads --urls-file urls.txt                # URL-uri date manual
"""
import argparse
import csv
import logging
import random
import re
from pathlib import Path
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from book_scraper.enrich import enrich_from_goodreads
from book_scraper.extract import Book, norm, parse_product
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
        respect_robots=not args.ignore_robots,
        ignore_robots_domains={"goodreads.com"})


def discover(client, site, query, pages):
    seen = set()
    for page in range(1, pages + 1):
        if site.name == "libris" and (query.startswith("/") or query.startswith("https://www.libris.ro/")):
            base_url = urljoin(site.base, query)
            parts = urlsplit(base_url)
            params = [(k, v) for k, v in parse_qsl(parts.query) if k != "iv.pg"]
            if page > 1:
                params.append(("iv.pg", str(page)))
            search_url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                                    urlencode(params), parts.fragment))
        else:
            search_url = site.search_url.format(q=quote_plus(query), page=page)
        html = client.get(search_url)
        if not html:
            log.warning("[%s] nu am primit pagina: %s", site.name, search_url)
            return
        new = [l for l in extract_links(html, search_url, site) if l not in seen]
        if not new:
            log.warning("[%s] 0 linkuri de produs gasite (pagina %d, query=%s) - verifica search_url/product_re",
                        site.name, page, query)
            return
        seen.update(new)
        category = ""
        if site.name == "libris" and is_libris_category_query(query):
            soup = BeautifulSoup(html, "lxml")
            heading = soup.find("h1")
            category = heading.get_text(" ", strip=True) if heading else ""
        yield from ((link, category) for link in new)


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


def matches_goodreads_query(book, query):
    """Keep results whose Goodreads genres/tags support the search query."""
    terms = [term for term in norm(query).split() if len(term) > 2]
    metadata = norm(" ".join([book.gen, book.subgen, *book.keywords]))
    return bool(terms) and all(term in metadata for term in terms)


def is_libris_category_query(query):
    return query.startswith("/") or query.startswith("https://www.libris.ro/")


def duplicate_keys(row):
    """Return identity-and-price keys for a Book or CSV row."""
    def value(name):
        return row.get(name, "") if isinstance(row, dict) else getattr(row, name, "")

    price = value("pret")
    try:
        price = round(float(price), 2) if price not in (None, "") else None
    except (TypeError, ValueError):
        price = None
    currency = norm(value("moneda"))
    keys = set()

    isbn = re.sub(r"[^0-9A-Za-z]", "", str(value("isbn") or "")).upper()
    if isbn:
        keys.add(("isbn", isbn, price, currency))

    title, author = norm(value("titlu")), norm(value("autor"))
    if title:
        keys.add(("title", title, author, norm(value("editie")),
                  norm(value("coperta")), norm(value("limba")), price, currency))
    return keys


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
    existing_urls, seen_urls, seen_listings = set(), set(), set()
    if out.exists():
        with out.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                existing_urls.add(row.get("url", ""))
                seen_listings.update(duplicate_keys(row))
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
                yield from ((u, "") for u in manual
                            if site.base.split("//")[1].replace("www.", "") in u)
                if not args.urls_file:
                    for q in args.queries:
                        yield from discover(client, site, q, args.pages)
            try:
                for url, category in urls():
                    if count >= args.limit:
                        break
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    # Refresh existing product URLs so a changed price can be recorded.
                    html = client.get(url, use_cache=url not in existing_urls)
                    if not html:
                        continue
                    book = parse_product(html, url, site.name, site.platform,
                                         site.default_lang, site.genres_selector, site.price_selector)
                    if book:
                        if category:
                            book.gen = category
                        if not args.no_goodreads and name != "goodreads":
                            ok = enrich_from_goodreads(client, book, args.gr_min_match)
                            if not ok:
                                log.info("[%s] fara potrivire pe Goodreads: %s", name, book.titlu)
                            elif book.rating is None or book.nr_ratinguri is None:
                                log.info("[%s] Goodreads fara rating/evaluari; pastrez cartea: %s",
                                         name, book.titlu)
                            regular_queries = [q for q in args.queries
                                               if not (name == "libris" and is_libris_category_query(q))]
                            if (ok and book.rating is not None and book.nr_ratinguri is not None
                                    and not args.urls_file and regular_queries and not any(
                                        matches_goodreads_query(book, query) for query in regular_queries)):
                                log.info("[%s] sarit: genurile Goodreads nu corespund query-ului '%s': %s",
                                         name, ", ".join(regular_queries), book.titlu)
                                continue
                        keys = duplicate_keys(book)
                        if keys and keys & seen_listings:
                            log.info("[%s] duplicat la acelasi pret; ignor: %s", name, book.titlu)
                            continue
                        w.writerow(book.to_row()); f.flush(); count += 1
                        seen_listings.update(keys)
                        log.info("[%s] %d/%d %s", name, count, args.limit, book.titlu)
            except BlockedError as e:
                log.error("Opresc %s: %s. Incearca mai tarziu / delay mai mare / proxy.", name, e)
    log.info("Gata: %s", out)


if __name__ == "__main__":
    main()

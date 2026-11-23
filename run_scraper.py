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
    domain_delays = {
        s.base.split("//")[1].replace("www.", ""): s.delay for s in SITES.values()
    }
    domain_delays["goodreads.com"] = (args.gr_min_delay, args.gr_max_delay)
    return PoliteClient(
        min_delay=args.min_delay, max_delay=args.max_delay,
        domain_delays=domain_delays,
        proxies=load_proxies(args.proxies), cache_dir=args.cache,
        respect_robots=not args.ignore_robots,
        ignore_robots_domains={"goodreads.com"},
        fail_fast_403_domains={"carturesti.ro"})


def discover(client, site, query, pages):
    seen = set()
    page = 1
    while pages <= 0 or page <= pages:
        if site.name == "libris" and (query.startswith("/") or query.startswith("https://www.libris.ro/")):
            base_url = urljoin(site.base, query)
            parts = urlsplit(base_url)
            params = [(k, v) for k, v in parse_qsl(parts.query) if k != "iv.pg"]
            if page > 1:
                params.append(("iv.pg", str(page)))
            search_url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                                    urlencode(params), parts.fragment))
        elif site.name == "elefant" and (
                query.startswith("/list/carti/") or query.startswith(site.base + "/list/carti/")):
            base_url = urljoin(site.base, query)
            parts = urlsplit(base_url)
            params = [(k, v) for k, v in parse_qsl(parts.query) if k != "pag"]
            if page > 1:
                params.append(("pag", str(page)))
            search_url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                                     urlencode(params), parts.fragment))
        elif site.name == "bookzone":
            # Bookzone uses category URLs for its browse pages; /cautare?q= is obsolete.
            if query.startswith("/carti/") or query.startswith(site.base + "/carti/"):
                base_url = urljoin(site.base, query)
                parts = urlsplit(base_url)
                params = [(k, v) for k, v in parse_qsl(parts.query) if k != "pagina"]
                params.append(("pagina", str(page)))
                search_url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                                         urlencode(params), parts.fragment))
            else:
                categories = {
                    "fantasy": "fantasy",
                    "romance": "romane-de-dragoste-romantice",
                    "thriller": "thriller-mister-suspans",
                    "sf": "sf",
                    "science fiction": "sf",
                    "istorie": "istorie",
                    "history": "istorie",
                }
                category = categories.get(query.strip().lower())
                if category:
                    search_url = f"{site.base}/carti/{category}?pagina={page}"
                else:
                    search_url = site.search_url.format(q=quote_plus(query), page=page)
        else:
            search_url = site.search_url.format(q=quote_plus(query), page=page)
        log.info("[%s] caut rezultate pentru '%s', pagina %d: %s",
                 site.name, query, page, search_url)
        html = client.get(search_url)
        if not html:
            log.warning("[%s] nu am primit pagina: %s", site.name, search_url)
            return
        new = [l for l in extract_links(html, search_url, site) if l not in seen]
        if not new:
            log.warning("[%s] 0 linkuri de produs gasite (pagina %d, query=%s) - verifica search_url/product_re",
                        site.name, page, query)
            return
        log.info("[%s] găsite %d linkuri de produs pentru '%s'", site.name, len(new), query)
        seen.update(new)
        category = ""
        if site.name == "libris" and is_libris_category_query(query):
            soup = BeautifulSoup(html, "lxml")
            heading = soup.find("h1")
            category = heading.get_text(" ", strip=True) if heading else ""
        yield from ((link, category) for link in new)
        page += 1


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


def is_bookzone_category_query(query):
    return query.startswith("/carti/") or query.startswith(SITES["bookzone"].base + "/carti/")


def is_elefant_category_query(query):
    return query.startswith("/list/carti/") or query.startswith(SITES["elefant"].base + "/list/carti/")


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


def book_identity(row):
    """Identity key for category-crossing dedupe, including the observed price."""
    def value(name):
        return row.get(name, "") if isinstance(row, dict) else getattr(row, name, "")

    raw_price = value("pret")
    try:
        price = round(float(raw_price), 2) if raw_price not in (None, "") else None
    except (TypeError, ValueError):
        price = None
    currency = norm(value("moneda"))
    isbn = re.sub(r"[^0-9A-Za-z]", "", str(value("isbn") or "")).upper()
    if isbn:
        return ("isbn", isbn, price, currency)
    title, author = norm(value("titlu")), norm(value("autor"))
    return ("title", title, author, price, currency) if title else None


def book_dedupe_identity(row):
    """Book identity without price, for removing the same Elefant book across categories."""
    def value(name):
        return row.get(name, "") if isinstance(row, dict) else getattr(row, name, "")

    isbn = re.sub(r"[^0-9A-Za-z]", "", str(value("isbn") or "")).upper()
    if isbn:
        return ("isbn", isbn)
    title, author = norm(value("titlu")), norm(value("autor"))
    if not title:
        return None
    return ("title", title, author, norm(value("editie")),
            norm(value("coperta")), norm(value("limba")))


_BUNDLE_TITLE_PATTERNS = (
    r"\bpachet\w*\b",
    r"\b(?:box\s*set|boxed\s*set|boxset|bundle)\b",
    r"\bset\s+complet\b",
    r"\bset(?:ul)?\s+(?:de\s+)?carti\b",
    r"\b(?:seria|serie|colectia|colectie)\s+completa\b",
    r"\b(?:seria|serie|colectia|colectie)\s+integrala\b",
    r"\b(?:complete|full)\s+(?:series|collection|set)\b",
    r"\btoate\s+(?:cele\s+)?volumele\b",
    r"\bvolumele\s+\d+\s*[-–]\s*\d+\b",
    r"\bvol(?:um)?\.?\s*\d+\s*[-–]\s*\d+\b",
    r"\btrilogia\s+completa\b",
    r"^seria\b",
)


def is_book_bundle(title):
    """Exclude package/full-series listings while keeping individual series volumes."""
    title = norm(title)
    return any(re.search(pattern, title) for pattern in _BUNDLE_TITLE_PATTERNS)


def main(default_sites=None, default_out="data/books.csv", default_queries=None,
         default_no_goodreads=False, default_pages=2, default_limit=200,
         default_per_category_limit=0):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=default_sites or [s for s in SITES if s != "goodreads"], choices=list(SITES))
    ap.add_argument("--no-goodreads", action="store_true", default=default_no_goodreads,
                    help="nu completa rating/keywords din Goodreads")
    ap.add_argument("--gr-min-match", type=float, default=0.6, help="similaritate minima titlu (0-1)")
    ap.add_argument("--gr-min-delay", type=float, default=60.0,
                    help="pauza minimă între cereri Goodreads, în secunde")
    ap.add_argument("--gr-max-delay", type=float, default=120.0,
                    help="pauza maximă între cereri Goodreads, în secunde")
    ap.add_argument("--queries", nargs="+", default=default_queries or
                    ["fantasy", "romance", "thriller", "sf", "istorie"])
    ap.add_argument("--pages", type=int, default=default_pages,
                    help="pagini / categorie; 0 = toate paginile disponibile")
    ap.add_argument("--limit", type=int, default=default_limit,
                    help="max cărți / site; 0 = fără limită")
    ap.add_argument("--per-category-limit", type=int, default=default_per_category_limit,
                    help="max cărți unice / query/categorie; 0 = fără limită")
    ap.add_argument("--urls-file", help="fisier cu URL-uri de produs (unul pe linie)")
    ap.add_argument("--out", default=default_out)
    ap.add_argument("--proxies", default="proxies.txt")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--min-delay", type=float, default=3.0)
    ap.add_argument("--max-delay", type=float, default=9.0)
    ap.add_argument("--ignore-robots", action="store_true")
    ap.add_argument("--probe")
    args = ap.parse_args()

    log.info("Pornesc scraperul pentru: %s; ieșire: %s", ", ".join(args.sites), args.out)
    client = build_client(args)
    if args.probe:
        return probe(client, args.probe)

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    existing_urls, seen_urls, seen_listings = set(), set(), set()
    seen_bookzone_books, seen_elefant_books = set(), set()
    if out.exists():
        with out.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                existing_urls.add(row.get("url", ""))
                seen_listings.update(duplicate_keys(row))
                if row.get("sursa") == "bookzone":
                    identity = book_identity(row)
                    if identity:
                        seen_bookzone_books.add(identity)
                elif row.get("sursa") == "elefant":
                    identity = book_dedupe_identity(row)
                    if identity:
                        seen_elefant_books.add(identity)
    new_file = not out.exists() or out.stat().st_size == 0
    manual = [l.strip() for l in Path(args.urls_file).read_text().splitlines() if l.strip()] if args.urls_file else []
    goodreads_blocked = False

    with out.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
            f.flush()
        sites = list(args.sites); random.shuffle(sites)   # alternam ordinea intre rulari
        for name in sites:
            site, count = SITES[name], 0
            category_counts = {}
            def urls():
                yield from ((u, "", "") for u in manual
                            if site.base.split("//")[1].replace("www.", "") in u)
                if not args.urls_file:
                    for q in args.queries:
                        if (args.per_category_limit > 0
                                and category_counts.get(q, 0) >= args.per_category_limit):
                            continue
                        for url, category in discover(client, site, q, args.pages):
                            if (args.per_category_limit > 0
                                    and category_counts.get(q, 0) >= args.per_category_limit):
                                break
                            yield url, category, q
            try:
                for url, category, group in urls():
                    if args.limit > 0 and count >= args.limit:
                        break
                    if (group and args.per_category_limit > 0
                            and category_counts.get(group, 0) >= args.per_category_limit):
                        continue
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    log.info("[%s] descarc produsul %s", name, url)
                    # Refresh existing product URLs so a changed price can be recorded.
                    html = client.get(url, use_cache=url not in existing_urls)
                    if not html:
                        log.warning("[%s] pagina nu a putut fi citită: %s", name, url)
                        continue
                    book = parse_product(html, url, site.name, site.platform,
                                         site.default_lang, site.genres_selector, site.price_selector)
                    if book:
                        if name in {"bookzone", "elefant"} and is_book_bundle(book.titlu):
                            log.info("[%s] exclud pachet/serie completă: %s", name, book.titlu)
                            continue
                        if category:
                            book.gen = category
                        if name in {"bookzone", "elefant"}:
                            # Goodreads-only fields must never fall back to store metadata.
                            book.original_title = ""
                            book.rating = None
                            book.nr_ratinguri = None
                            book.goodreads_url = ""
                            book.goodreads_match = None
                            book.serie = ""
                            book.keywords = []
                        identity = book_identity(book) if name == "bookzone" else None
                        elefant_identity = book_dedupe_identity(book) if name == "elefant" else None
                        if identity and identity in seen_bookzone_books:
                            log.info("[%s] duplicat în altă categorie, ignor: %s", name, book.titlu)
                            continue
                        if elefant_identity and elefant_identity in seen_elefant_books:
                            log.info("[%s] duplicat în altă categorie, ignor: %s", name, book.titlu)
                            continue
                        if not args.no_goodreads and name != "goodreads" and not goodreads_blocked:
                            ok = enrich_from_goodreads(
                                client, book, args.gr_min_match,
                                use_goodreads_series=name in {"bookzone", "elefant"},
                            )
                            if not ok:
                                log.info("[%s] fara potrivire pe Goodreads: %s", name, book.titlu)
                            elif book.rating is None or book.nr_ratinguri is None:
                                log.info("[%s] Goodreads fara rating/evaluari; pastrez cartea: %s",
                                         name, book.titlu)
                            if client._blocks.get("goodreads.com", 0) >= client.block_limit:
                                goodreads_blocked = True
                                log.warning("Goodreads a blocat/limitat accesul; continui colectarea fără alte lookup-uri Goodreads.")
                            regular_queries = [q for q in args.queries
                                               if not (name == "libris" and is_libris_category_query(q))
                                               and not (name == "bookzone" and is_bookzone_category_query(q))
                                               and not (name == "elefant" and is_elefant_category_query(q))]
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
                        if identity:
                            seen_bookzone_books.add(identity)
                        if elefant_identity:
                            seen_elefant_books.add(elefant_identity)
                        if group:
                            category_counts[group] = category_counts.get(group, 0) + 1
                        log.info("[%s] %d cărți adăugate: %s", name, count, book.titlu)
                    else:
                        log.warning("[%s] pagina a fost descărcată, dar nu am extras date de carte: %s",
                                    name, url)
            except BlockedError as e:
                log.error("Opresc %s: %s. Incearca mai tarziu / delay mai mare / proxy.", name, e)
    log.info("Gata: %s", out)


if __name__ == "__main__":
    main()

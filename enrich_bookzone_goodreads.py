"""Match existing Bookzone CSV rows to Goodreads without changing the source file."""
import argparse
import csv
import logging
from pathlib import Path
from types import SimpleNamespace

from book_scraper.enrich import enrich_from_goodreads
from book_scraper.extract import parse_product
from book_scraper.http import PoliteClient
from book_scraper.sites import SITES
from run_scraper import load_proxies


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bookzone.goodreads")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input", default="data/date_bookzone.csv")
    parser.add_argument("--out", default="data/date_bookzone_goodreads.csv")
    parser.add_argument("--limit", type=int, default=0,
                        help="număr maxim de rânduri la care încearcă potrivirea; 0 = toate")
    parser.add_argument("--min-match", type=float, default=0.6,
                        help="similaritate minimă a titlului (0-1)")
    parser.add_argument("--proxies", default="proxies.txt")
    parser.add_argument("--cache", default="cache")
    parser.add_argument("--min-delay", type=float, default=60.0,
                        help="pauza minimă între cereri Goodreads, în secunde (implicit: 60)")
    parser.add_argument("--max-delay", type=float, default=120.0,
                        help="pauza maximă între cereri Goodreads, în secunde (implicit: 120)")
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.out)
    if not source.is_file():
        raise SystemExit(f"Nu există fișierul de intrare: {source}")
    if source.resolve() == output.resolve():
        raise SystemExit("Fișierul de ieșire trebuie să fie diferit de cel de intrare.")

    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not fields:
        raise SystemExit(f"CSV-ul nu are antet: {source}")
    if "original_title" not in fields:
        insert_at = fields.index("titlu") + 1 if "titlu" in fields else len(fields)
        fields.insert(insert_at, "original_title")

    client = PoliteClient(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        domain_delays={"goodreads.com": SITES["goodreads"].delay},
        proxies=load_proxies(args.proxies),
        cache_dir=args.cache,
        respect_robots=True,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    matched = attempted = 0
    blocked = False
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for index, row in enumerate(rows):
            # When enriching an Elefant export, refresh its publication year from
            # the already-cached store page; Goodreads enrichment alone cannot do this.
            store_site = SITES.get(row.get("sursa", ""))
            product_url = row.get("url", "")
            if store_site and product_url and "an_aparitie" in fields:
                product_cache = client._cache_path(product_url)
                if product_cache.is_file():
                    product_html = product_cache.read_text(encoding="utf-8")
                    store_book = parse_product(
                        product_html, product_url, store_site.name,
                        store_site.platform, store_site.default_lang,
                        store_site.genres_selector, store_site.price_selector,
                    )
                    if store_book and store_book.an_aparitie is not None:
                        row["an_aparitie"] = store_book.an_aparitie

            row["keywords"] = ""
            row["serie"] = ""
            row["original_title"] = ""
            row["rating"] = ""
            row["nr_ratinguri"] = ""
            row["goodreads_url"] = ""
            row["goodreads_match"] = ""
            if (args.limit > 0 and attempted >= args.limit) or blocked:
                writer.writerow(row)
                continue

            title = (row.get("titlu") or "").strip()
            if not title:
                writer.writerow(row)
                continue

            book = SimpleNamespace(
                titlu=title,
                autor=(row.get("autor") or "").strip(),
                isbn=(row.get("isbn") or "").strip(),
                original_title="",
                serie="",
                rating=None,
                nr_ratinguri=None,
                keywords=[],
                goodreads_url="",
                goodreads_match=None,
            )
            attempted += 1
            log.info("Potrivire Goodreads %d/%d: %s", attempted, len(rows), title)
            if enrich_from_goodreads(client, book, args.min_match, use_goodreads_series=True):
                row["rating"] = book.rating
                row["nr_ratinguri"] = book.nr_ratinguri
                row["keywords"] = "|".join(book.keywords)
                row["serie"] = book.serie
                row["original_title"] = book.original_title
                row["goodreads_url"] = book.goodreads_url
                row["goodreads_match"] = book.goodreads_match
                matched += 1
                log.info("Potrivire găsită (%.2f): %s", book.goodreads_match, book.goodreads_url)
            else:
                log.info("Nu am găsit o potrivire suficient de sigură: %s", title)

            writer.writerow(row)
            stream.flush()
            if client._blocks.get("goodreads.com", 0) >= client.block_limit:
                blocked = True
                log.warning("Goodreads a limitat cererile; păstrez restul rândurilor fără modificări.")

    log.info("Gata: %s — %d potriviri din %d încercări; %d rânduri în total.",
             output, matched, attempted, len(rows))


if __name__ == "__main__":
    main()

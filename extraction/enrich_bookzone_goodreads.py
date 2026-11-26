"""Match existing book CSV rows to Goodreads."""
import argparse
import csv
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from book_scraper.enrich import enrich_from_goodreads
from book_scraper.extract import parse_product
from book_scraper.http import PoliteClient
from book_scraper.sites import SITES
from run_scraper import load_proxies


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("goodreads.enrichment")


def _save_attempt_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def main(*, default_input="data/raw/carti_bookzone.csv",
         default_output="data/raw/carti_bookzone.csv",
         default_min_delay=6.0, default_max_delay=18.0,
         default_batch_pause=(60.0, 120.0), goodreads_block_waits=(300, 600)):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input", default=default_input)
    parser.add_argument("--out", default=default_output)
    parser.add_argument("--limit", type=int, default=0,
                        help="număr maxim de rânduri la care încearcă potrivirea; 0 = toate")
    parser.add_argument("--min-match", type=float, default=0.6,
                        help="similaritate minimă a titlului (0-1)")
    parser.add_argument("--proxies", default="proxies.txt")
    parser.add_argument("--cache", default="other/cache")
    parser.add_argument("--min-delay", type=float, default=default_min_delay,
                        help=f"pauza minimă între cereri Goodreads, în secunde (implicit: {default_min_delay:g})")
    parser.add_argument("--max-delay", type=float, default=default_max_delay,
                        help=f"pauza maximă între cereri Goodreads, în secunde (implicit: {default_max_delay:g})")
    parser.add_argument("--batch-size", type=int, default=25,
                        help="numărul de accesări Goodreads între pauzele lungi (implicit: 25)")
    parser.add_argument("--batch-pause-min", type=float, default=default_batch_pause[0],
                        help=f"pauza minimă după fiecare grup, în secunde (implicit: {default_batch_pause[0]:g})")
    parser.add_argument("--batch-pause-max", type=float, default=default_batch_pause[1],
                        help=f"pauza maximă după fiecare grup, în secunde (implicit: {default_batch_pause[1]:g})")
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.out)
    if not source.is_file():
        raise SystemExit(f"Nu există fișierul de intrare: {source}")
    in_place = source.resolve() == output.resolve()
    write_path = (output.with_name(f"{output.stem}.tmp{output.suffix}")
                  if in_place else output)
    state_path = Path("other/state") / f"{output.stem}.goodreads_state.json"

    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not fields:
        raise SystemExit(f"CSV-ul nu are antet: {source}")
    if "original_title" not in fields:
        insert_at = fields.index("titlu") + 1 if "titlu" in fields else len(fields)
        fields.insert(insert_at, "original_title")

    if state_path.is_file():
        try:
            attempt_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Nu pot citi progresul Goodreads din {state_path}: {exc}")
    else:
        attempt_state = {}
        last_match_index = max(
            (i for i, row in enumerate(rows) if (row.get("goodreads_url") or "").strip()),
            default=-1,
        )
        for row in rows[:last_match_index + 1]:
            url = (row.get("url") or "").strip()
            if url and not (row.get("goodreads_url") or "").strip():
                attempt_state[url] = "before_checkpoint"
        if in_place and write_path.is_file():
            try:
                with write_path.open(encoding="utf-8-sig", newline="") as stream:
                    partial_rows = list(csv.DictReader(stream))
            except (OSError, csv.Error):
                partial_rows = []
            if len(partial_rows) < len(rows) and all(
                partial_rows[i].get("url") == rows[i].get("url")
                for i in range(len(partial_rows))
            ):
                for row in partial_rows[:-1]:
                    url = (row.get("url") or "").strip()
                    if url and not (row.get("goodreads_url") or "").strip():
                        attempt_state.setdefault(url, "no_match")
        _save_attempt_state(state_path, attempt_state)

    client = PoliteClient(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        # Intervalul CLI se aplică și domeniului Goodreads; fără această setare,
        # intervalul per domeniu ar suprascrie valorile CLI cu delay-ul site-ului.
        domain_delays={"goodreads.com": (args.min_delay, args.max_delay)},
        long_pause_every=(args.batch_size, args.batch_size),
        long_pause=(args.batch_pause_min, args.batch_pause_max),
        goodreads_block_waits=goodreads_block_waits,
        proxies=load_proxies(args.proxies),
        cache_dir=args.cache,
        respect_robots=True,
        # Excepția robots pentru accesul Goodreads este limitată la acest domeniu.
        ignore_robots_domains={"goodreads.com"},
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    matched = attempted = 0
    blocked = False
    with write_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for index, row in enumerate(rows):
            # Pentru exporturile Elefant, anul apariției se recitește din pagina
            # produsului salvată în cache; Goodreads completează celelalte metadate.
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

            if (row.get("goodreads_url") or "").strip():
                writer.writerow(row)
                continue

            product_url = (row.get("url") or "").strip()
            if attempt_state.get(product_url) in ("no_match", "before_checkpoint"):
                log.info("Sar peste carte deja încercată fără potrivire: %s",
                         (row.get("titlu") or "").strip())
                writer.writerow(row)
                continue

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
                attempt_state.pop(product_url, None)
                log.info("Potrivire găsită (%.2f): %s", book.goodreads_match, book.goodreads_url)
            else:
                log.info("Nu am găsit o potrivire suficient de sigură: %s", title)
                attempt_state[product_url] = (
                    "blocked" if client._blocks.get("goodreads.com", 0) >= client.block_limit
                    else "no_match"
                )

            _save_attempt_state(state_path, attempt_state)

            writer.writerow(row)
            stream.flush()
            if client._blocks.get("goodreads.com", 0) >= client.block_limit:
                blocked = True
                log.warning("Goodreads a limitat cererile; păstrez restul rândurilor fără modificări.")

    if in_place:
        write_path.replace(output)

    log.info("Gata: %s — %d potriviri din %d încercări; %d rânduri în total.",
             output, matched, attempted, len(rows))


if __name__ == "__main__":
    main()

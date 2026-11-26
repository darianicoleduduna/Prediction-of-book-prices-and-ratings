"""Find Goodreads matches for low-review books in the Libris dataset."""
import argparse
import csv
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from book_scraper.enrich import enrich_from_goodreads
from book_scraper.http import BlockedError, PoliteClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("libris.goodreads")
GOODREADS_FIELDS = (
    "original_title", "serie", "keywords", "rating", "nr_ratinguri",
    "goodreads_url", "goodreads_match",
)


def _review_count_below(value, threshold):
    raw = str(value or "").strip()
    if not raw:
        return True
    digits = re.sub(r"[\s,.]", "", raw)
    return digits.isdigit() and int(digits) < threshold


def _load_proxies(path):
    proxy_file = Path(path)
    if not proxy_file.is_file():
        return []
    return [line.strip() for line in proxy_file.read_text(encoding="utf-8")
            .splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input", default="other/archive/date_libris.csv")
    parser.add_argument("--out", default="data/raw/date_libris2.csv")
    parser.add_argument("--max-reviews", type=int, default=100,
                        help="include rândurile cu mai puține review-uri decât pragul; valorile goale sunt incluse")
    parser.add_argument("--min-match", type=float, default=0.6)
    parser.add_argument("--limit", type=int, default=0,
                        help="număr maxim de cărți la care încearcă potrivirea; 0 = toate")
    parser.add_argument("--min-delay", type=float, default=3.0)
    parser.add_argument("--max-delay", type=float, default=8.0)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--batch-pause-min", type=float, default=60.0)
    parser.add_argument("--batch-pause-max", type=float, default=120.0)
    parser.add_argument("--proxies", default="proxies.txt")
    parser.add_argument("--cache", default="other/cache")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.out)
    if not input_path.is_file():
        raise SystemExit(f"Nu există fișierul de intrare: {input_path}")
    if input_path.resolve() == output_path.resolve():
        raise SystemExit("Fișierul rezultat trebuie să fie separat de fișierul Libris original.")
    if args.max_reviews <= 0 or args.batch_size <= 0:
        raise SystemExit("--max-reviews și --batch-size trebuie să fie mai mari decât zero.")
    if args.min_delay < 0 or args.max_delay < args.min_delay:
        raise SystemExit("Intervalul --min-delay/--max-delay nu este valid.")
    if args.batch_pause_min < 0 or args.batch_pause_max < args.batch_pause_min:
        raise SystemExit("Intervalul pauzei lungi nu este valid.")

    state_path = Path("other/state") / f"{output_path.stem}.goodreads_state.json"
    temp_output = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    # O rulare completă se reia din exportul îmbogățit; după o întrerupere înainte
    # de finalizarea exportului, sursa rămâne CSV-ul Libris inițial.
    base_path = output_path if output_path.is_file() and state_path.is_file() else input_path
    with base_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not fields:
        raise SystemExit(f"CSV-ul nu are antet: {base_path}")
    if "original_title" not in fields:
        insert_at = fields.index("titlu") + 1 if "titlu" in fields else len(fields)
        fields.insert(insert_at, "original_title")

    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Nu pot citi progresul Goodreads din {state_path}: {exc}")
    else:
        state = {}
    if not isinstance(state, dict):
        raise SystemExit(f"Fișierul de progres nu are formatul așteptat: {state_path}")

    # Exportul parțial păstrează prefixul deja procesat, aliniat la sursa Libris;
    # ultimul rând rămâne reluabil, deoarece putea fi în curs la întrerupere.
    if base_path.resolve() == input_path.resolve() and temp_output.is_file():
        try:
            with temp_output.open(encoding="utf-8-sig", newline="") as stream:
                partial = list(csv.DictReader(stream))
        except (OSError, csv.Error):
            partial = []
        aligned = len(partial) < len(rows) and all(
            partial[i].get("url") == rows[i].get("url") for i in range(len(partial))
        )
        if aligned:
            for i, saved in enumerate(partial):
                rows[i].update({key: saved.get(key, "") for key in fields if key in saved})
            for saved in partial[:-1]:
                url = (saved.get("url") or "").strip()
                if (url and _review_count_below(saved.get("nr_ratinguri"), args.max_reviews)
                        and not (saved.get("goodreads_url") or "").strip()):
                    state.setdefault(url, "no_match")

    client = PoliteClient(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        domain_delays={"goodreads.com": (args.min_delay, args.max_delay)},
        long_pause_every=(args.batch_size, args.batch_size),
        long_pause=(args.batch_pause_min, args.batch_pause_max),
        goodreads_block_waits=(300, 600),
        proxies=_load_proxies(args.proxies),
        cache_dir=args.cache,
        respect_robots=True,
        ignore_robots_domains={"goodreads.com"},
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    attempted = matched = eligible = 0
    blocked = False
    with temp_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            if not _review_count_below(row.get("nr_ratinguri"), args.max_reviews):
                writer.writerow(row)
                continue
            eligible += 1

            url = (row.get("url") or "").strip()
            if (row.get("goodreads_url") or "").strip():
                writer.writerow(row)
                continue
            if state.get(url) == "no_match":
                log.info("Sar peste carte încercată anterior fără potrivire: %s", row.get("titlu", ""))
                writer.writerow(row)
                continue
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
            log.info("Potrivire Goodreads %d: %s", attempted, title)
            if enrich_from_goodreads(client, book, args.min_match, use_goodreads_series=True):
                row["rating"] = book.rating
                row["nr_ratinguri"] = book.nr_ratinguri
                row["keywords"] = "|".join(book.keywords)
                row["serie"] = book.serie
                row["original_title"] = book.original_title
                row["goodreads_url"] = book.goodreads_url
                row["goodreads_match"] = book.goodreads_match
                state.pop(url, None)
                matched += 1
                log.info("Potrivire găsită (%.2f): %s", book.goodreads_match, book.goodreads_url)
            else:
                is_blocked = client._blocks.get("goodreads.com", 0) >= client.block_limit
                state[url] = "blocked" if is_blocked else "no_match"
                if is_blocked:
                    blocked = True
                else:
                    log.info("Nu am găsit o potrivire suficient de sigură: %s", title)

            writer.writerow(row)
            stream.flush()
            _save_state(state_path, state)

    temp_output.replace(output_path)
    log.info("Gata: %s — %d potriviri din %d încercări; %d rânduri eligibile.",
             output_path, matched, attempted, eligible)


if __name__ == "__main__":
    main()

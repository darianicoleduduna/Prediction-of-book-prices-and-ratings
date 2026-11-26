import argparse
import csv
import hashlib
import json
import logging
import time
from pathlib import Path

from book_scraper.enrich import enrich_from_goodreads_status
from book_scraper.extract import Book
from book_scraper.http import PoliteClient
from book_scraper.sites import SITES
from run_scraper import load_proxies

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("libris_goodreads_retry")


class CacheOnlyClient:
    """Read cached Goodreads pages without making any network requests."""
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self._last_status = {}
        self._blocks = {"goodreads.com": 0}
        self.block_limit = 3

    def get(self, url, use_cache=True):
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        cached = self.cache_dir / f"{key}.html"
        if cached.exists():
            self._last_status[url] = 200
            return cached.read_text(encoding="utf-8")
        self._last_status[url] = None
        return None


def save_csv(path, fieldnames, rows):
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
    temp.replace(path)


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def make_book(row):
    return Book(titlu=row.get("titlu", ""), autor=row.get("autor", ""),
                isbn=row.get("isbn", ""), serie=row.get("serie", ""),
                original_title=row.get("original_title", ""),
                goodreads_url=row.get("goodreads_url", ""))


def persist_result(index, total, row, book, result, state, state_path,
                   csv_path, fieldnames, rows):
    url = row.get("url", "")
    if result == "matched":
        if book.rating is not None:
            row["rating"] = str(book.rating)
        if book.nr_ratinguri is not None:
            row["nr_ratinguri"] = str(book.nr_ratinguri)
        if book.original_title:
            row["original_title"] = book.original_title
        if book.keywords:
            row["keywords"] = "|".join(book.keywords)
        if book.goodreads_url:
            row["goodreads_url"] = book.goodreads_url
        if book.goodreads_match is not None:
            row["goodreads_match"] = str(book.goodreads_match)
        # Potrivirea Goodreads fără rating este terminală pentru această rundă;
        # căutarea nu se repetă în reluările limitate la rating.
        if book.rating is None:
            state[url] = "matched_no_rating"
        else:
            state[url] = "matched" if book.original_title else "matched_no_original"
        log.info("[%d/%d] potrivire Goodreads: %s (rating=%s, original title=%s)",
                 index, total, book.titlu, row["rating"] or "null",
                 row["original_title"] or "null")
    else:
        state[url] = "not_found"
        log.info("[%d/%d] nu există o potrivire Goodreads confirmată: %s",
                 index, total, book.titlu)
    save_csv(csv_path, fieldnames, rows)
    save_state(state_path, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="other/archive/date_libris.csv", help="CSV-ul Libris existent")
    parser.add_argument("--state", default="other/state/date_libris_goodreads_retry.json",
                        help="fișierul de stare pentru reluare")
    parser.add_argument("--retry-delay", type=float, default=300,
                        help="secunde de așteptare după blocaj/eroare (implicit 300)")
    parser.add_argument("--challenge-delay", type=float, default=240,
                        help="secunde de pauză după un challenge Goodreads")
    parser.add_argument("--ignore-saved-cooldowns", action="store_true",
                        help="încearcă live chiar dacă starea salvată are un cooldown activ")
    parser.add_argument("--retry-not-found", action="store_true",
                        help="reîncearcă rândurile marcate not_found folosind căutarea actualizată")
    parser.add_argument("--gr-min-delay", type=float, default=3)
    parser.add_argument("--gr-max-delay", type=float, default=8)
    parser.add_argument("--proxies", default="proxies.txt")
    parser.add_argument("--cache", default="other/cache")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"Nu există fișierul: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    required = {"url", "sursa", "titlu", "autor", "isbn", "rating", "nr_ratinguri",
                "keywords", "serie", "original_title", "goodreads_url", "goodreads_match"}
    missing = required - set(fieldnames)
    if missing:
        raise SystemExit(f"Lipsesc coloanele necesare: {', '.join(sorted(missing))}")

    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    domain_delays = {
        site.base.split("//")[1].replace("www.", ""): site.delay
        for site in SITES.values()
    }
    domain_delays["goodreads.com"] = (args.gr_min_delay, args.gr_max_delay)
    client = PoliteClient(
        min_delay=3.0, max_delay=9.0, domain_delays=domain_delays,
        long_pause_every=(25, 25), long_pause=(60, 120),
        proxies=load_proxies(args.proxies), cache_dir=args.cache,
        respect_robots=True, ignore_robots_domains={"goodreads.com"},
        exact_delay_domains={"goodreads.com"},
        # Pauza de cinci minute este gestionată de acest loop, fără o a doua
        # pauză imediată în PoliteClient.
        cooldown_retry_domains=set(),
    )

    pending = [row for row in rows if row.get("sursa") == "libris"
               and not (row.get("rating") or "").strip()]
    log.info("Rânduri Libris fără rating: %d; fișier: %s",
             len(pending), path)

    # Rândurile nerezolvate rămân într-o coadă, astfel încât un URL Goodreads
    # inaccesibil să nu blocheze procesarea întregului CSV. În cooldown se folosesc
    # paginile Goodreads din cache, fără cereri suplimentare.
    state.pop("__goodreads_global_retry_after", None)
    cache_client = CacheOnlyClient(args.cache)
    pending_urls = {row.get("url", "") for row in pending}
    saved_cooldowns = [
        float(entry.get("retry_after", 0))
        for url, entry in state.items()
        if url in pending_urls and isinstance(entry, dict)
        and entry.get("status") == "deferred"
    ]
    resume_cooldown_until = (0 if args.ignore_saved_cooldowns
                             else max(saved_cooldowns, default=0))
    global_retry_at = resume_cooldown_until
    live_blocked = resume_cooldown_until > time.time()
    deferred = []
    for index, row in enumerate(pending, 1):
        url = row.get("url", "")
        entry = state.get(url)
        status = entry.get("status") if isinstance(entry, dict) else entry
        if status == "matched_no_rating" or (status == "not_found" and not args.retry_not_found):
            continue
        book = make_book(row)
        entry_retry_at = (float(entry.get("retry_after", 0))
                          if isinstance(entry, dict) else 0)
        row_cooldown_active = (not args.ignore_saved_cooldowns
                               and status == "deferred"
                               and entry_retry_at > time.time())
        lookup_client = (cache_client if row_cooldown_active or live_blocked
                         or client._blocks.get("goodreads.com", 0) >= client.block_limit
                         else client)
        result = enrich_from_goodreads_status(
            lookup_client, book, min_match=0.6,
            use_goodreads_series=False, use_cache=True
        )
        if result == "retry":
            challenged = (lookup_client is client and
                          client._blocks.get("goodreads.com", 0) >= client.block_limit)
            old_entry = state.get(url)
            old_retry_at = (float(old_entry.get("retry_after", 0))
                            if isinstance(old_entry, dict) else 0)
            retry_at = (max(global_retry_at, old_retry_at, time.time())
                        if lookup_client is cache_client
                        else time.time() + (args.challenge_delay if challenged
                                            else args.retry_delay))
            state[url] = {"status": "deferred", "retry_after": retry_at}
            deferred.append((index, row))
            save_state(state_path, state)
            if challenged:
                client._blocks["goodreads.com"] = 0
                live_blocked = False
                global_retry_at = retry_at
                log.warning("[%d/%d] Goodreads a dat challenge; aștept %.0f secunde și continui cu următoarea carte: %s",
                            index, len(pending), args.challenge_delay, book.titlu)
                time.sleep(args.challenge_delay)
            else:
                log.info("[%d/%d] amân rândul fără rezultat sigur și continui: %s",
                         index, len(pending), book.titlu)
            continue
        persist_result(index, len(pending), row, book, result, state,
                       state_path, path, fieldnames, rows)

    # La final există o singură rundă de retry pentru rândurile al căror cooldown
    # a expirat. Rândurile încă în cooldown rămân pentru o rulare ulterioară.
    if deferred:
        save_state(state_path, state)
        now = time.time()
        ready = []
        for index, row in deferred:
            entry = state.get(row.get("url", ""))
            retry_at = float(entry.get("retry_after", 0)) if isinstance(entry, dict) else 0
            if retry_at <= now:
                ready.append((index, row))
        waiting = len(deferred) - len(ready)
        if waiting:
            log.info("Fără așteptare: %d rânduri rămân amânate până la cooldown; %d sunt eligibile pentru retry acum",
                     waiting, len(ready))

        client._blocks["goodreads.com"] = 0
        live_blocked = False
        for position, (index, row) in enumerate(ready):
            url = row.get("url", "")
            entry = state.get(url)
            status = entry.get("status") if isinstance(entry, dict) else entry
            if status in {"not_found", "matched", "matched_no_original", "matched_no_rating"}:
                continue
            book = make_book(row)
            lookup_client = cache_client if live_blocked else client
            result = enrich_from_goodreads_status(
                lookup_client, book, min_match=0.6,
                use_goodreads_series=False, use_cache=True
            )
            if result == "retry":
                challenged = (lookup_client is client and
                              client._blocks.get("goodreads.com", 0) >= client.block_limit)
                old_entry = state.get(url)
                old_retry_at = (float(old_entry.get("retry_after", 0))
                                if isinstance(old_entry, dict) else 0)
                retry_at = (max(global_retry_at, old_retry_at, time.time())
                            if lookup_client is cache_client
                            else time.time() + (args.challenge_delay if challenged
                                                else args.retry_delay))
                state[url] = {"status": "deferred", "retry_after": retry_at}
                save_state(state_path, state)
                if challenged:
                    client._blocks["goodreads.com"] = 0
                    live_blocked = False
                    global_retry_at = retry_at
                    log.warning("[%d/%d] challenge la retry-ul final; aștept %.0f secunde și continui cu următoarea carte.",
                                index, len(pending), args.challenge_delay)
                    time.sleep(args.challenge_delay)
                else:
                    log.info("[%d/%d] retry final fără rezultat sigur; rând amânat pentru următoarea rulare: %s",
                             index, len(pending), book.titlu)
                continue
            persist_result(index, len(pending), row, book, result, state,
                           state_path, path, fieldnames, rows)

    log.info("Gata. CSV actualizat: %s; stare retry: %s", path, state_path)


if __name__ == "__main__":
    main()

import csv
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from book_scraper.extract import parse_product
from book_scraper.sites import SITES


CSV_PATH = Path("data/raw/date_libristo.csv")
CACHE_DIR = Path("other/cache_libristo")
GOODREADS_FIELDS = {
    "original_title", "rating", "nr_ratinguri", "serie", "keywords",
}


def cached_html(url):
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    path = CACHE_DIR / f"{key}.html"
    return path.read_text(encoding="utf-8") if path.exists() else None


def row_value(book, field):
    value = getattr(book, field)
    if field == "keywords":
        return "|".join(value or [])
    return "" if value is None else str(value)


def main():
    if not CSV_PATH.exists():
        raise SystemExit(f"Nu există fișierul: {CSV_PATH}")
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    changed = 0
    store_updates = 0
    goodreads_updates = 0
    for row in rows:
        updated_row = False
        html = cached_html(row.get("url", ""))
        if html:
            book = parse_product(html, row["url"], "libristo", "online", "",
                                 price_selector=SITES["libristo"].price_selector)
            if book:
                for field in fieldnames:
                    if field in GOODREADS_FIELDS or field in {"url", "sursa", "platforma_vanzare"}:
                        continue
                    value = row_value(book, field) if hasattr(book, field) else ""
                    if not (row.get(field) or "").strip() and value:
                        row[field] = value
                        updated_row = True
                        store_updates += 1

        gr_url = row.get("goodreads_url", "")
        if gr_url and any(not (row.get(field) or "").strip() for field in GOODREADS_FIELDS):
            gr_html = cached_html(gr_url)
            if gr_html:
                gr = parse_product(gr_html, gr_url, "goodreads", "", "",
                                   SITES["goodreads"].genres_selector)
                if gr:
                    for field in GOODREADS_FIELDS:
                        value = row_value(gr, field)
                        if not (row.get(field) or "").strip() and value:
                            row[field] = value
                            updated_row = True
                            goodreads_updates += 1
        if updated_row:
            changed += 1

    if changed:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = CSV_PATH.with_name(f"{CSV_PATH.stem}.before_retry_{stamp}{CSV_PATH.suffix}")
        shutil.copy2(CSV_PATH, backup)
        temp = CSV_PATH.with_name(CSV_PATH.name + ".tmp")
        with temp.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
        temp.replace(CSV_PATH)
        print(f"Backup: {backup}")

    print(f"Rânduri: {len(rows)}; rânduri actualizate: {changed}")
    print(f"Câmpuri Libristo completate din cache: {store_updates}")
    print(f"Câmpuri Goodreads completate din cache: {goodreads_updates}")
    for field in ("pret", "moneda", "coperta", "original_title", "rating",
                  "nr_ratinguri", "serie", "keywords", "goodreads_url",
                  "an_aparitie"):
        missing = sum(not (row.get(field) or "").strip() for row in rows)
        print(f"{field}: {missing} valori goale")


if __name__ == "__main__":
    main()

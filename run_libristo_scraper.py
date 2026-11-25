"""Scraper Libristo pe categorii, cu completare Goodreads și cache separat.

Exemple:
  python run_libristo_scraper.py
  python run_libristo_scraper.py --pages 1 --limit 10
  python run_libristo_scraper.py --probe https://www.libristo.ro/ro/carte/slug_123456
"""
from run_scraper import main

LIBRISTO_CATEGORIES = [
    "https://www.libristo.ro/ro/carti-in-limba-engleza/fantasy",
    "https://www.libristo.ro/ro/carti-in-limba-engleza/science-fiction",
    "https://www.libristo.ro/ro/carti-in-limba-engleza/romance",
    "https://www.libristo.ro/ro/carti-in-limba-engleza/thriller-suspense-fiction",
    "https://www.libristo.ro/ro/carti-in-limba-engleza/horror-supernatural-fiction",
    "https://www.libristo.ro/ro/carti-in-limba-engleza/historical-fiction",
    "https://www.libristo.ro/ro/carti-in-limba-engleza/adventure-fiction",
    "https://www.libristo.ro/ro/carti-in-limba-engleza/fantasy-romance-dark-romance",
    "https://www.libristo.ro/ro/carti-in-limba-romana/fantasy-romance-dark-romance",
]


if __name__ == "__main__":
    main(default_sites=["libristo"], default_out="data/date_libristo.csv",
         default_queries=LIBRISTO_CATEGORIES, default_no_goodreads=False,
         default_pages=0, default_limit=0, default_per_category_limit=100,
         default_cache="cache_libristo")

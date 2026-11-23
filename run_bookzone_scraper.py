"""Rulare dedicată Bookzone, cu export implicit în data/date_bookzone.csv.

Exemple:
  python run_bookzone_scraper.py
  python run_bookzone_scraper.py --queries fantasy --pages 1 --limit 5
  python run_bookzone_scraper.py --probe https://bookzone.ro/carte/...
"""
from run_scraper import main

BOOKZONE_CATEGORIES = [
    "https://bookzone.ro/carti/beletristica",
    "https://bookzone.ro/carti/thriller-mister-suspans",
    "https://bookzone.ro/carti/fantasy",
    "https://bookzone.ro/carti/sf",
    "https://bookzone.ro/carti/young-adults-pentru-adolescenti",
    "https://bookzone.ro/carti/fictiune-in-limba-engleza",
]


if __name__ == "__main__":
    main(default_sites=["bookzone"], default_out="data/carti_bookzone.csv",
         default_queries=BOOKZONE_CATEGORIES, default_no_goodreads=False,
         default_pages=0, default_limit=0, default_per_category_limit=300)

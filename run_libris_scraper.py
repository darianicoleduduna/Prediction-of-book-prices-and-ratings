"""Scraper Libris pentru categorii, cu export în data/date_libris.csv.

Exemple:
  python run_libris_scraper.py
  python run_libris_scraper.py --per-category-limit 100
  python run_libris_scraper.py --probe https://www.libris.ro/carte/.../123456
"""
from run_scraper import main

LIBRIS_CATEGORIES = [
    # Categorii în română
    "https://www.libris.ro/fiction/action-adventure",
    "https://www.libris.ro/fiction/african-american",
    "https://www.libris.ro/fiction/alternative-history",
    "https://www.libris.ro/fiction/anthologies-multiple-authors-",
    "https://www.libris.ro/fiction/biographical",
    "https://www.libris.ro/fiction/classics",
    "https://www.libris.ro/fiction/coming-of-age",
    "https://www.libris.ro/fiction/contemporary-women",
    "https://www.libris.ro/fiction/crime",
    "https://www.libris.ro/fiction/dystopian",
    "https://www.libris.ro/fiction/fairy-tales-folk-tales-legends-mythology",
    "https://www.libris.ro/fiction/family-life",
    "https://www.libris.ro/fiction/fantasy",
    "https://www.libris.ro/fiction/gay",
    "https://www.libris.ro/fiction/horror",
    "https://www.libris.ro/fiction/romance",
    "https://www.libris.ro/fiction/thrillers",
    "https://www.libris.ro/carti-de-aventura",
    "https://www.libris.ro/carti-horror",
    "https://www.libris.ro/carti-pentru-adolescenti-young-adult",
    "https://www.libris.ro/carti-politiste",
    "https://www.libris.ro/carti-thriller",
    "https://www.libris.ro/literatura-clasica",
    "https://www.libris.ro/literatura-contemporana",
    "https://www.libris.ro/carti/beletristica/literatura-romana",
    "https://www.libris.ro/manga",
    "https://www.libris.ro/nuvele-schite-povestiri-fabule",
    "https://www.libris.ro/carti/beletristica/poezie",
    "https://www.libris.ro/roman-grafic",
    "https://www.libris.ro/sf-fantasy",
    "https://www.libris.ro/romane-gotice",
    "https://www.libris.ro/romane-mitologice-si-istorice",
    "https://www.libris.ro/romane-de-dragoste-carti-romantice",
    "https://www.libris.ro/romane-distopice"
]


if __name__ == "__main__":
    main(default_sites=["libris"], default_out="data/date_libris.csv",
         default_queries=LIBRIS_CATEGORIES, default_no_goodreads=False,
         default_pages=0, default_limit=0, default_per_category_limit=100)

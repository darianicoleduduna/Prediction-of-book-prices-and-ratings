"""Scraper Elefant pentru cele șase categorii, cu export în data/date_elefant.csv.

Exemple:
  python run_elefant_scraper.py
  python run_elefant_scraper.py --per-category-limit 100
  python run_elefant_scraper.py --probe https://www.elefant.ro/...
"""
from run_scraper import main

ELEFANT_CATEGORIES = [
    "https://www.elefant.ro/list/carti/carte/fictiune/moderni-contemporani",
    "https://www.elefant.ro/list/carti/carte/fictiune/young-adult",
    "https://www.elefant.ro/list/carti/carte/fictiune/fantasy",
    "https://www.elefant.ro/list/carti/carte/fictiune/romance",
    "https://www.elefant.ro/list/carti/carte/fictiune/crime-thriller-mistery",
    "https://www.elefant.ro/list/carti/carte/fictiune/clasici",
    "https://www.elefant.ro/list/carti/carte/fictiune/science-fiction",
    "https://www.elefant.ro/list/carti/carte/fictiune/actiune-aventura",
    "https://www.elefant.ro/list/carti/carte/biografii-si-memorii/biografii",
    "https://www.elefant.ro/list/carti/carte/biografii-si-memorii/memorii-si-jurnale",
    "https://www.elefant.ro/list/carti/carte-straina/fiction-related-items/romance",
    "https://www.elefant.ro/list/carti/carte-straina/fiction-related-items/fantasy",
    "https://www.elefant.ro/list/carti/carte-straina/fiction-related-items/science-fiction",
    "https://www.elefant.ro/list/carti/carte-straina/fiction-related-items/thriller-suspense-fiction",
    "https://www.elefant.ro/list/carti/carte-straina/fiction-related-items/fiction-general-literary",
    "https://www.elefant.ro/list/carti/carte-straina/fiction-related-items/horror-supernatural-fiction",
    "https://www.elefant.ro/list/carti/carte-straina/biography-literature-literary-studies",
]


if __name__ == "__main__":
    main(default_sites=["elefant"], default_out="data/date_elefant.csv",
         default_queries=ELEFANT_CATEGORIES, default_no_goodreads=False,
         default_pages=0, default_limit=0, default_per_category_limit=100)

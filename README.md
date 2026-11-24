# Book scraper (carturesti, libris, elefant, bookzone, goodreads)

1. `pip install -r requirements.txt`
2. Verifica fiecare site pe o pagina de produs reala:
   `python run_scraper.py --probe <URL-produs>`
   Daca un camp lipseste sau URL-ul de cautare nu da rezultate, ajusteaza `book_scraper/sites.py`.
3. Ruleaza: `python run_scraper.py --sites libris --queries fantasy --pages 2 --limit 50`

Pentru Bookzone, `python run_bookzone_scraper.py` colectează produsele individuale din cele
șase categorii, exclude pachetele și seriile complete și scrie în `data/carti_bookzone.csv`.
Încearcă să adauge keywords, seria și `original_title` găsite pe Goodreads, cu pauze de
60–120 secunde între cererile Goodreads. Platforma este `online & fizic`, iar sursa `bookzone`.
`--per-category-limit` schimbă limita pe categorie; `0` înseamnă fără limită.

Pentru Elefant, `python run_elefant_scraper.py` parcurge implicit cele 17 categorii
configurate, până la 100 de cărți unice per categorie, exclude pachetele/seriile complete,
adaugă metadatele Goodreads când există potriviri și scrie în `data/date_elefant.csv`.

Pentru Libris, `python run_libris_scraper.py` parcurge paginile categoriilor configurate în
`run_libris_scraper.py`, până la 100 de cărți noi per categorie, și scrie în
`data/date_libris.csv`. Încearcă să completeze ratingul, numărul de evaluări, seria și
keywords din Goodreads. Poți schimba lista din `LIBRIS_CATEGORIES` sau limita cu
`--per-category-limit`; `0` înseamnă fără limită.

Protectii: delay aleator per domeniu (3-9s, goodreads 6-18s), pauze lungi la 20-40 cereri,
backoff exponential + Retry-After, robots.txt, cache pe disc (reluare fara recerere),
stop dupa 3 blocaje (403/429/captcha), rotatie UA/proxy (proxies.txt, optional).

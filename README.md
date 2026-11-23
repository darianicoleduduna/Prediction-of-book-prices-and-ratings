# Book scraper (carturesti, libris, elefant, bookzone, goodreads)

1. `pip install -r requirements.txt`
2. Verifica fiecare site pe o pagina de produs reala:
   `python run_scraper.py --probe <URL-produs>`
   Daca un camp lipseste sau URL-ul de cautare nu da rezultate, ajusteaza `book_scraper/sites.py`.
3. Ruleaza: `python run_scraper.py --sites libris --queries fantasy --pages 2 --limit 50`

Pentru Bookzone, `python run_bookzone_scraper.py` ia implicit până la 300 de cărți unice
din fiecare dintre cele șase categorii configurate și le salvează în `data/date_bookzone.csv`.
Deduplică după ISBN și preț (sau titlu, autor și preț când ISBN-ul lipsește). Opțional,
`--per-category-limit` schimbă limita pe categorie; `0` înseamnă fără limită.

Pentru Elefant, `python run_elefant_scraper.py` parcurge implicit cele 17 categorii
configurate, până la 300 de cărți unice per categorie, și scrie în `data/date_elefant.csv`.

Pentru Cărturești, dacă cererile HTTP simple primesc 403, folosește varianta cu browser:
`python run_carturesti_browser.py --queries fantasy thriller --pages 2 --limit 50`
Aceasta deschide Chrome și folosește HTML-ul randat de browser. Pentru URL-uri date manual,
folosește `--urls-file urls_carturesti.txt`; pentru diagnostic, `--probe <URL-produs>`.
Termenii fantasy, romance, thriller, sf, science fiction și istorie folosesc direct rafturile
de categorii Cărturești; alți termeni folosesc ruta de căutare.
Selenium Manager descarcă automat driverul Chrome la prima rulare, deci este necesară
conexiune la internet. Dacă site-ul afișează refuz sau CAPTCHA, scraperul se oprește.

Rămâne disponibil și `run_carturesti_scraper.py` pentru varianta HTTP simplă.

Protectii: delay aleator per domeniu (3-9s, goodreads 6-18s), pauze lungi la 20-40 cereri,
backoff exponential + Retry-After, robots.txt, cache pe disc (reluare fara recerere),
stop dupa 3 blocaje (403/429/captcha), rotatie UA/proxy (proxies.txt, optional).

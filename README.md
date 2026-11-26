# Colectarea și analiza datelor despre cărți

Proiectul adună informații despre cărți și prețuri de la Bookzone, Elefant, Libris și Libristo. Datele din paginile magazinelor sunt completate, acolo unde se găsește o potrivire suficient de sigură, cu ratinguri, numărul de evaluări, genuri, serii și titluri originale Goodreads.

## Fluxul datelor

Scraperele din `extraction/` parcurg categorii de produse și pagini de carte. Extrag titlul, autorul, editura, anul, numărul de pagini, prețul, moneda și alte detalii disponibile. Înregistrările duplicate dintre categorii sunt reduse, iar pachetele și seriile complete sunt eliminate din colectările Bookzone și Elefant.

Îmbogățirea Goodreads folosește ISBN-ul atunci când este disponibil și valid, apoi titlul și autorul. Potrivirile confirmate adaugă ratingul, numărul de evaluări, genurile, seria și titlul original. Cache-urile și fișierele de stare susțin reluarea procesării și păstrarea progresului.

Scripturile de preprocesare combină datele magazinelor în `data/raw/extracted_data.csv` și pot crea un set separat cu înregistrările care au rating.
Analiza setului filtrat rezumă ratingurile, anii de apariție, limbile și tipurile de copertă, cu grafice salvate separat în `data/preprocessed/figures/`.

## Organizarea proiectului

- `extraction/` — scripturi de colectare, îmbogățire Goodreads, retry și preprocesare, împreună cu pachetul comun `book_scraper/`.
- `data/raw/` — CSV-urile curente pe magazin și setul concatenat.
- `data/preprocessed/` — seturi pregătite pentru analiză, inclusiv fișierul filtrat după existența ratingului.
- `docs/` — materiale de prezentare a proiectului.
- `other/archive/` — exporturi mai vechi și surse intermediare.
- `other/state/` — starea salvată pentru procesele reluabile.
- `other/cache*/` și `other/logs/` — pagini descărcate și loguri de rulare.

Datele păstrează câte un rând pentru fiecare ofertă dintr-o sursă. Astfel, aceeași carte poate apărea de mai multe ori, cu prețurile observate la magazine diferite.

"""Configuratie per site. ATENTIE: search_url si product_re sunt estimari -
verifica-le cu: python run_scraper.py --probe <url-produs>"""
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


@dataclass
class Site:
    name: str
    base: str
    search_url: str                 # {q} = query, {page} = nr pagina
    platform: str
    default_lang: str = ""
    product_re: Optional[str] = None
    genres_selector: Optional[str] = None
    price_selector: Optional[str] = None
    delay: tuple = (3.0, 9.0)


SITES = {
    "carturesti": Site("carturesti", "https://carturesti.ro",
                       "https://carturesti.ro/product/search/{q}?page={page}",
                       "online & fizic", "romana", r"^/carte/"),
    "libris": Site("libris", "https://www.libris.ro",
                   "https://www.libris.ro/?q={q}&page={page}",
                   "online & fizic", "romana", r"-[A-Z0-9]+--p\d+\.html$"),
    "elefant": Site("elefant", "https://www.elefant.ro",
                    "https://www.elefant.ro/search?SearchTerm={q}&PageNumber={page}",
                    "online", "romana", price_selector=".product-price .current-price, .current-price"),
    "bookzone": Site("bookzone", "https://www.bookzone.ro",
                     "https://www.bookzone.ro/cautare?q={q}&page={page}",
                     "online", "romana"),
    "goodreads": Site("goodreads", "https://www.goodreads.com",
                      "https://www.goodreads.com/search?q={q}&page={page}",
                      "", "", r"^/book/show/\d+",
                      genres_selector='[data-testid="genresList"] a.Button--tag, [data-testid="genresList"] a, a.bookPageGenreLink',
                      delay=(6.0, 18.0)),
}

_BAD = ("cos", "cont", "login", "cautare", "search", "blog", "contact", "page", "wishlist",
        "livrare", "termeni", "despre", "ajutor", "help", "user", "list", "shelf", "author")


def _host(u):
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def extract_links(html, page_url, site: Site):
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(page_url, a["href"]).split("#")[0]
        p = urlparse(full)
        if _host(full) != _host(site.base):
            continue
        path = p.path
        if site.product_re:
            ok = re.search(site.product_re, path)
        else:   # euristica: slug lung cu cratime, adancime mica
            segs = [s for s in path.split("/") if s]
            ok = (1 <= len(segs) <= 3 and segs[-1].count("-") >= 3
                  and not any(b == segs[0] for b in _BAD))
        if ok:
            clean = full if "goodreads" not in full else f"{p.scheme}://{p.netloc}{path}"
            if clean not in seen:
                seen.add(clean)
                out.append(clean)
    return out
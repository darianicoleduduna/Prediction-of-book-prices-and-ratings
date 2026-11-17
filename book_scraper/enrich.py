"""Completeaza rating, nr_ratinguri si keywords din Goodreads (nu din magazin)."""
import difflib
import logging
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .extract import parse_product, norm
from .sites import SITES, extract_links

log = logging.getLogger("scraper.enrich")


def _clean(title):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", title or "")
    return norm(t)


def _canonical_book_url(html):
    """Cand cautarea dupa ISBN redirecteaza direct pe cartea din Goodreads."""
    soup = BeautifulSoup(html, "lxml")
    for tag in (soup.find("meta", property="og:url"), soup.find("link", rel="canonical")):
        if tag:
            v = tag.get("content") or tag.get("href") or ""
            if "/book/show/" in v:
                return v
    return None


def enrich_from_goodreads(client, book, min_match=0.6):
    """Suprascrie rating/nr_ratinguri/keywords cu cele de pe Goodreads.
    Returneaza True daca a gasit o potrivire acceptabila."""
    site = SITES["goodreads"]
    book.rating, book.nr_ratinguri, book.keywords = None, None, []   # nu folosim datele magazinului

    first_author = re.split(r"[,;&]| si ", book.autor)[0].strip() if book.autor else ""
    attempts = []
    if book.isbn:
        attempts.append((book.isbn, True))
    attempts.append((f"{_clean(book.titlu)} {first_author}".strip(), False))

    for query, by_isbn in attempts:
        search_url = site.search_url.format(q=quote_plus(query), page=1)
        html = client.get(search_url)
        if not html:
            continue
        book_url = _canonical_book_url(html)
        page = html
        if not book_url:
            links = extract_links(html, search_url, site)
            if not links:
                continue
            book_url = links[0]
            page = client.get(book_url)
            if not page:
                continue
        gr = parse_product(page, book_url, "goodreads", "", "", site.genres_selector)
        if not gr:
            continue
        score = difflib.SequenceMatcher(None, _clean(book.titlu), _clean(gr.titlu)).ratio()
        if by_isbn:
            score = max(score, 0.95)        # potrivire dupa ISBN = de incredere
        if score >= min_match:
            book.rating, book.nr_ratinguri = gr.rating, gr.nr_ratinguri
            book.keywords = gr.keywords[:20]
            book.goodreads_url, book.goodreads_match = book_url, round(score, 2)
            return True
        log.info("Goodreads: potrivire slaba (%.2f) '%s' vs '%s'", score, book.titlu, gr.titlu)
    return False

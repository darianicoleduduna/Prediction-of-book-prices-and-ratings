"""Completeaza rating, nr_ratinguri si keywords din Goodreads (nu din magazin)."""
import difflib
import logging
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .extract import parse_product, norm
from .http import BlockedError
from .sites import SITES, extract_links

log = logging.getLogger("scraper.enrich")


def _clean(title):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", title or "")
    return norm(t)


def _valid_isbn(value):
    """Accept only ISBN-10/13 values with a valid check digit."""
    isbn = re.sub(r"[^0-9Xx]", "", str(value or "")).upper()
    if len(isbn) == 13 and isbn.isdigit():
        checksum = sum(int(digit) * (1 if index % 2 == 0 else 3)
                       for index, digit in enumerate(isbn[:12]))
        return (10 - checksum % 10) % 10 == int(isbn[-1])
    if len(isbn) == 10 and isbn[:9].isdigit() and (isbn[-1].isdigit() or isbn[-1] == "X"):
        checksum = sum(int(digit) * (10 - index) for index, digit in enumerate(isbn[:9]))
        checksum += 10 if isbn[-1] == "X" else int(isbn[-1])
        return checksum % 11 == 0
    return False


def _canonical_book_url(html):
    """Cand cautarea dupa ISBN redirecteaza direct pe cartea din Goodreads."""
    soup = BeautifulSoup(html, "lxml")
    for tag in (soup.find("meta", property="og:url"), soup.find("link", rel="canonical")):
        if tag:
            v = tag.get("content") or tag.get("href") or ""
            if "/book/show/" in v:
                return v
    return None


def enrich_from_goodreads(client, book, min_match=0.6, use_goodreads_series=False):
    """Suprascrie rating/nr_ratinguri/keywords cu cele de pe Goodreads.
    Returneaza True daca a gasit o potrivire acceptabila."""
    site = SITES["goodreads"]
    book.rating, book.nr_ratinguri, book.keywords = None, None, []   # nu folosim datele magazinului

    first_author = re.split(r"[,;&]| si ", book.autor)[0].strip() if book.autor else ""
    attempts = []
    if _valid_isbn(book.isbn):
        isbn = re.sub(r"[^0-9Xx]", "", book.isbn).upper()
        attempts.append((isbn, True))
    attempts.append((f"{_clean(book.titlu)} {first_author}".strip(), False))

    for query, by_isbn in attempts:
        if by_isbn:
            # Goodreads resolves ISBNs directly to a canonical book page on some requests;
            # try this before its /search endpoint, which may return a WAF challenge.
            isbn_url = f"{site.base}/book/isbn/{quote_plus(query)}"
            try:
                html = client.get(isbn_url)
            except BlockedError as e:
                log.warning("Goodreads: opresc imbogatirea dupa blocajul serverului (%s)", e)
                return False
            book_url = _canonical_book_url(html) if html else None
            page = html
        else:
            book_url = None
            page = None

        if not book_url:
            search_url = site.search_url.format(q=quote_plus(query), page=1)
            try:
                html = client.get(search_url)
            except BlockedError as e:
                log.warning("Goodreads: opresc imbogatirea dupa blocajul serverului (%s)", e)
                return False
            if not html:
                continue
            book_url = _canonical_book_url(html)
            page = html
            if not book_url:
                links = extract_links(html, search_url, site)
                if not links:
                    continue
                book_url = links[0]
                try:
                    page = client.get(book_url)
                except BlockedError as e:
                    log.warning("Goodreads: opresc imbogatirea dupa blocajul serverului (%s)", e)
                    return False
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
            if use_goodreads_series:
                book.serie = gr.serie
                book.original_title = gr.original_title
            book.goodreads_url, book.goodreads_match = book_url, round(score, 2)
            return True
        log.info("Goodreads: potrivire slaba (%.2f) '%s' vs '%s'", score, book.titlu, gr.titlu)
    return False

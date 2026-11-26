"""Extractie generica: JSON-LD (schema.org) + tabele de specificatii + breadcrumbs.
Merge pe majoritatea magazinelor fara selectori specifici."""
import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


@dataclass
class Book:
    url: str = ""
    sursa: str = ""
    titlu: str = ""
    original_title: str = ""
    autor: str = ""
    editura: str = ""
    an_aparitie: Optional[int] = None
    gen: str = ""
    subgen: str = ""
    nr_pagini: Optional[int] = None
    platforma_vanzare: str = ""
    serie: str = ""
    editie: str = ""            # simpla / ilustrata / deluxe
    coperta: str = ""           # paperback / hardcover
    keywords: list = field(default_factory=list)
    rating: Optional[float] = None
    nr_ratinguri: Optional[int] = None
    pret: Optional[float] = None
    moneda: str = ""
    limba: str = ""
    isbn: str = ""
    goodreads_url: str = ""
    goodreads_match: Optional[float] = None

    def to_row(self):
        d = asdict(self)
        d["keywords"] = "|".join(self.keywords)
        return d


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower().rstrip(":").strip()


LABELS = {
    "autor": ["autor", "autori", "author", "scris de"],
    "editura": ["editura", "editor", "publisher", "publicat de"],
    "an": ["an aparitie", "anul aparitiei", "an publicare", "anul publicarii",
           "data aparitiei", "aparitie", "data publicarii", "publication date", "year"],
    "pagini": ["nr pagini", "nr. pagini", "numar pagini", "numar de pagini", "pagini", "pages"],
    "limba": ["limba", "limba originala", "language"],
    "coperta": ["coperta", "tip coperta", "legatura", "tip legatura", "format", "binding"],
    "serie": ["serie", "seria", "colectie", "colectia", "series"],
    "original_title": ["original title", "titlu original"],
    "gen": ["gen", "gen literar", "categorie", "categorii", "genre"],
    "isbn": ["isbn", "ean", "cod isbn"],
    "editie": ["editie", "tip editie", "edition"],
}
LABEL_LOOKUP = {norm(v): k for k, vs in LABELS.items() for v in vs}

LANG_MAP = {"ro": "romana", "en": "engleza", "fr": "franceza", "de": "germana",
            "es": "spaniola", "it": "italiana", "hu": "maghiara"}

TROPES = [
    "enemies to lovers", "friends to lovers", "slow burn", "found family", "chosen one",
    "love triangle", "forbidden love", "second chance", "fake dating", "grumpy sunshine",
    "morally grey", "dark academia", "coming of age", "time travel", "post-apocaliptic",
    "dystopi", "magic system", "portal fantasy", "epic fantasy", "urban fantasy",
    "cozy mystery", "serial killer", "psychological thriller", "whodunit", "heist",
    "vampir", "vrajitoare", "dragon", "zane", "razboi", "royal", "mafia", "boarding school",
    "enemies-to-lovers", "romantasy", "space opera", "cyberpunk", "steampunk", "haunted",
]


def _jsonld_nodes(soup):
    out = []

    def walk(x):
        if isinstance(x, list):
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            out.append(x)
            for k in ("@graph", "mainEntity", "itemListElement"):
                if k in x:
                    walk(x[k])
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(tag.string or tag.get_text() or ""))
        except (ValueError, TypeError):
            continue
    return out


def _goodreads_original_title(soup):
    """Read Goodreads' originalTitle from its hydrated page JSON."""
    pattern = re.compile(r'"originalTitle"\s*:\s*("(?:\\.|[^"\\])*")')
    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        match = pattern.search(raw or "")
        if not match:
            continue
        try:
            value = json.loads(match.group(1)).strip()
        except (ValueError, TypeError):
            continue
        if value:
            return value
    return ""


def _types(n):
    t = n.get("@type", [])
    return [t] if isinstance(t, str) else list(t)


def _name(v):
    if isinstance(v, list):
        return ", ".join(filter(None, (_name(i) for i in v)))
    if isinstance(v, dict):
        return str(v.get("name", "")).strip()
    return str(v or "").strip()


def to_int(s):
    m = re.search(r"\d[\d.,]*", str(s or ""))
    if not m:
        return None
    try:
        return int(re.sub(r"[.,]", "", m.group()))
    except ValueError:
        return None


def to_float(s):
    if s is None:
        return None
    s = re.sub(r"[^\d.,]", "", str(s))
    if not s:
        return None
    if "," in s and "." in s:       # 1.299,99 sau 1,299.99
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _spec_pairs(soup):
    pairs = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) == 2:
            pairs.setdefault(norm(cells[0].get_text()), cells[1].get_text(" ", strip=True))
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            pairs.setdefault(norm(dt.get_text()), dd.get_text(" ", strip=True))
    # Unele magazine afișează specificațiile ca perechi alăturate de etichetă și
    # valoare, în loc de tabel sau listă dt/dd; Bookzone folosește acest format.
    for el in soup.find_all(["th", "strong", "label", "span", "div", "p", "li"]):
        label = norm(el.get_text(" ", strip=True))
        if label not in LABEL_LOOKUP:
            continue
        sibling = el.find_next_sibling()
        if sibling:
            value = sibling.get_text(" ", strip=True)
            if value and norm(value) not in LABEL_LOOKUP:
                pairs.setdefault(label, value)
    for el in soup.find_all(["li", "p", "div", "span"]):
        if el.find(["li", "p", "div", "table"]):
            continue
        txt = el.get_text(" ", strip=True)
        if 3 < len(txt) < 150 and ":" in txt:
            k, v = txt.split(":", 1)
            if v.strip():
                pairs.setdefault(norm(k), v.strip())
    return pairs


def _breadcrumbs(soup, nodes, title):
    crumbs = []
    for n in nodes:
        if "BreadcrumbList" in _types(n):
            for it in n.get("itemListElement", []):
                item = it.get("item")
                nm = it.get("name") or (item.get("name") if isinstance(item, dict) else "")
                if nm:
                    crumbs.append(nm.strip())
            break
    if not crumbs:
        bc = soup.select_one('[class*="readcrumb"], nav[aria-label*="readcrumb"], [itemtype*="BreadcrumbList"]')
        if bc:
            crumbs = [a.get_text(strip=True) for a in bc.find_all("a") if a.get_text(strip=True)]
    skip = {"acasa", "home", "carti", "carte", "books", "toate cartile", "librarie online"}
    nt = norm(title)
    return [c for c in crumbs if norm(c) not in skip and norm(c) != nt]


def detect_edition(*texts):
    t = norm(" ".join(texts))
    if re.search(r"deluxe|de lux|collector|editie de colectie|limited", t):
        return "deluxe"
    if re.search(r"ilustrat|illustrated|cu ilustratii", t):
        return "ilustrata"
    return "simpla"


def detect_cover(text):
    t = norm(text)
    if re.search(r"hard|cartonat|rigid|legat|cu supracoperta", t):
        return "hardcover"
    if re.search(r"paper|brosat|soft|mass market|trade", t):
        return "paperback"
    return ""


def find_tropes(text):
    t = norm(text)
    return sorted({k for k in TROPES if k in t})


def parse_product(html, url, source, default_platform="", default_lang="", genres_selector=None,
                  price_selector=None):
    soup = BeautifulSoup(html, "lxml")
    nodes = _jsonld_nodes(soup)
    prod = next((n for n in nodes if {"Book", "Product"} & set(_types(n)) and n.get("name")), {})
    specs = _spec_pairs(soup)
    spec = {}
    for k, v in specs.items():
        if k in LABEL_LOOKUP:
            spec.setdefault(LABEL_LOOKUP[k], v)

    b = Book(url=url, sursa=source, platforma_vanzare=default_platform)
    og = soup.find("meta", property="og:title")
    h1 = soup.find("h1")
    b.titlu = (prod.get("name") or (h1.get_text(strip=True) if h1 else "")
               or (og["content"] if og and og.get("content") else "")).strip()
    b.original_title = (
        _name(prod.get("originalTitle") or prod.get("alternativeHeadline") or prod.get("alternateName"))
        or spec.get("original_title", "")
        or (_goodreads_original_title(soup) if source == "goodreads" else "")
    ) if source == "goodreads" else ""
    b.autor = _name(prod.get("author")) or spec.get("autor", "")
    pub = prod.get("publisher") or prod.get("brand")
    b.editura = _name(pub) or spec.get("editura", "")
    b.isbn = str(prod.get("isbn") or prod.get("gtin13") or spec.get("isbn", "")).strip()
    b.nr_pagini = to_int(prod.get("numberOfPages")) or to_int(spec.get("pagini"))

    date = str(prod.get("datePublished") or spec.get("an") or "")
    # Elefant afișează uneori anii recenți cu separator, de exemplu „2.026”.
    date = re.sub(r"(?<=\d)[.,](?=\d{3}(?:\D|$))", "", date)
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date)
    b.an_aparitie = int(m.group(1)) if m else None

    lang = prod.get("inLanguage") or spec.get("limba") or default_lang
    lang = _name(lang)
    b.limba = LANG_MAP.get(norm(lang)[:2], norm(lang)) if lang else ""

    b.coperta = detect_cover(f"{prod.get('bookFormat', '')} {spec.get('coperta', '')}")

    ar = prod.get("aggregateRating") or {}
    b.rating = to_float(ar.get("ratingValue"))
    b.nr_ratinguri = to_int(ar.get("ratingCount") or ar.get("reviewCount"))

    offers = prod.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        b.pret = to_float(offers.get("price") or offers.get("lowPrice"))
        b.moneda = offers.get("priceCurrency", "")
    # Prețul HTML de la Elefant poate împărți partea zecimală în elemente separate;
    # get_text("") unește „92,” și „99” în valoarea „92,99”.
    for sel in ([price_selector] if price_selector else []):
        el = soup.select_one(sel)
        if el:
            val = to_float(el.get_text("", strip=True))
            if val:
                b.pret, b.moneda = val, "RON" if "lei" in norm(el.get_text()) else b.moneda
                break
    if b.pret is None:
        meta = soup.find("meta", property="product:price:amount")
        if meta:
            b.pret = to_float(meta.get("content"))
            cur = soup.find("meta", property="product:price:currency")
            b.moneda = cur.get("content", "") if cur else ""
    if b.pret is None:
        for sel in (".current-price", "[itemprop=price]", ".product-price", ".price"):
            el = soup.select_one(sel)
            val = to_float(el.get("content") or el.get_text("", strip=True)) if el else None
            if val:
                b.pret = val
                break
    # Unele pagini Bookzone afișează prețul actual după prețul PRP în zona de
    # cumpărare și nu includ oferte Product sau clase de preț standard.
    if b.pret is None and source == "bookzone":
        page_text = soup.get_text(" ", strip=True)
        match = re.search(r"PRP\s*:\s*[\d.,]+\s*Lei.*?(\d+(?:[.,]\d{1,2})?)\s*Lei",
                          page_text, flags=re.IGNORECASE)
        if match:
            b.pret, b.moneda = to_float(match.group(1)), "RON"
    if b.pret is not None and not b.moneda:
        b.moneda = "RON"

    desc_meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    desc = str(prod.get("description") or (desc_meta.get("content") if desc_meta else "") or "")
    b.serie = spec.get("serie", "")
    if not b.serie:
        m = re.search(r"\(([^()]+?),?\s*#\s*[\d.]+\)", b.titlu) or \
            re.search(r"\b[Ss]eria\s+([A-ZĂÂÎȘȚ][^.,;()\n]{2,50})", desc)
        b.serie = m.group(1).strip() if m else ""
    if source == "goodreads":
        series_link = soup.select_one('a[href*="/series/"]')
        if series_link:
            series_name = series_link.get_text(" ", strip=True)
            if series_name and norm(series_name) != "series":
                b.serie = series_name

    crumbs = _breadcrumbs(soup, nodes, b.titlu)
    gen_list = []
    if genres_selector:
        gen_list = [a.get_text(strip=True) for a in soup.select(genres_selector)]
    gen_list = gen_list or crumbs or ([spec["gen"]] if spec.get("gen") else [])
    if prod.get("genre"):
        gen_list = [_name(prod["genre"])] + gen_list
    b.gen = gen_list[0] if gen_list else ""
    b.subgen = gen_list[1] if len(gen_list) > 1 else ""

    b.editie = detect_edition(b.titlu, spec.get("editie", ""), desc[:600])
    if source == "goodreads":
        # Ordinea afișată de Goodreads pentru genuri și taguri este păstrată.
        b.keywords = list(dict.fromkeys(norm(g) for g in gen_list if norm(g)))[:20]
    else:
        b.keywords = sorted(set(find_tropes(f"{b.titlu} {desc}")) | {norm(g) for g in gen_list})

    is_bookzone_product = source == "bookzone" and re.search(r"/carte/[^/]+", urlsplit(url).path)
    if not b.titlu or not (prod or b.pret or b.nr_pagini or is_bookzone_product):
        return None     # pagina nu e de produs
    return b

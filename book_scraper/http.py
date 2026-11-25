"""Client HTTP "politicos": delay aleator per domeniu, backoff, robots.txt,
cache pe disc, rotatie User-Agent/proxy cand apar blocaje."""
import hashlib
import logging
import os
import random
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger("scraper.http")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


class BlockedError(Exception):
    """Domeniul ne-a blocat de prea multe ori; oprim ca sa nu agravam situatia."""


class PoliteClient:
    def __init__(self, min_delay=3.0, max_delay=9.0, domain_delays=None,
                 long_pause_every=(20, 40), long_pause=(30, 90),
                 max_retries=4, block_limit=3, proxies=None,
                 cache_dir="cache", respect_robots=True, timeout=30,
                 ignore_robots_domains=None, fail_fast_403_domains=None,
                 goodreads_block_waits=(300, 600)):
        self.min_delay, self.max_delay = min_delay, max_delay
        self.domain_delays = domain_delays or {}   # {"goodreads.com": (6, 18)}
        self.long_pause_every, self.long_pause = long_pause_every, long_pause
        self.max_retries, self.block_limit = max_retries, block_limit
        self.goodreads_block_waits = tuple(goodreads_block_waits)
        self.proxies = list(proxies or [])
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.respect_robots, self.timeout = respect_robots, timeout
        self.scrapfly_key = os.environ.get("SCRAPFLY_KEY", "").strip()
        self.scrapfly_cost_budget = os.environ.get("SCRAPFLY_COST_BUDGET", "").strip()
        self.ignore_robots_domains = {
            d.lower().removeprefix("www.") for d in (ignore_robots_domains or [])
        }
        self.fail_fast_403_domains = {
            d.lower().removeprefix("www.") for d in (fail_fast_403_domains or [])
        }

        self._sessions, self._last_req, self._count = {}, {}, {}
        self._next_pause, self._blocks, self._robots = {}, {}, {}
        self._proxy_for, self._last_url = {}, {}

    # ---------- helpers ----------
    @staticmethod
    def _domain(url):
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    def _delay_range(self, domain):
        lo, hi = self.domain_delays.get(domain, (self.min_delay, self.max_delay))
        rp = self._robots.get(domain)
        if rp:
            cd = rp.crawl_delay("*")
            if cd:
                lo, hi = max(lo, cd), max(hi, cd * 2)
        return lo, hi

    def _wait(self, domain):
        lo, hi = self._delay_range(domain)
        # distributie neuniforma: uneori pauze mai lungi, ca un om
        delay = random.uniform(lo, hi) * random.choice([1, 1, 1, 1.3, 1.8])
        elapsed = time.time() - self._last_req.get(domain, 0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        # Pause before the next request once the configured number has finished.
        n = self._count.get(domain, 0)
        nxt = self._next_pause.setdefault(domain, random.randint(*self.long_pause_every))
        if n >= nxt:
            pause = random.uniform(*self.long_pause)
            log.info("[%s] pauza lunga %.0fs", domain, pause)
            time.sleep(pause)
            self._count[domain] = 0
            self._next_pause[domain] = random.randint(*self.long_pause_every)
        self._count[domain] = self._count.get(domain, 0) + 1

    def _session(self, domain, fresh=False):
        if fresh or domain not in self._sessions:
            s = requests.Session()
            s.headers.update({
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
                "Upgrade-Insecure-Requests": "1",
            })
            self._sessions[domain] = s
        return self._sessions[domain]

    def _pick_proxy(self, domain, rotate=False):
        if not self.proxies:
            return None
        if rotate or domain not in self._proxy_for:
            self._proxy_for[domain] = random.choice(self.proxies)
        p = self._proxy_for[domain]
        return {"http": p, "https": p}

    def _cache_path(self, url):
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def _allowed(self, url, domain):
        if not self.respect_robots or domain in self.ignore_robots_domains:
            return True
        if domain not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            try:
                r = self._session(domain).get(robots_url, timeout=self.timeout,
                                              proxies=self._pick_proxy(domain))
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[domain] = rp
        ok = self._robots[domain].can_fetch("*", url)
        if not ok:
            log.warning("robots.txt interzice: %s", url)
        return ok

    def _get_via_scrapfly(self, url):
        if not self.scrapfly_key:
            return None
        params = {
            "key": self.scrapfly_key,
            "url": url,
            "unblocker": "true",
            "format": "raw",
            "proxified_response": "true",
        }
        if self.scrapfly_cost_budget:
            params["cost_budget"] = self.scrapfly_cost_budget
        try:
            resp = requests.get("https://api.scrapfly.io/scrape", params=params, timeout=160)
        except requests.RequestException as e:
            log.warning("Scrapfly request failed: %s", e)
            return None
        if resp.status_code != 200:
            reject_code = resp.headers.get("X-Scrapfly-Reject-Code", "")
            log.warning("Scrapfly HTTP %s%s", resp.status_code,
                        f" ({reject_code})" if reject_code else "")
            return None
        html = resp.text
        if not html or (resp.headers.get("x-amzn-waf-action", "").lower() == "challenge"):
            log.warning("Scrapfly did not return usable Goodreads HTML")
            return None
        log.info("Goodreads HTML obtained via Scrapfly Unblocker")
        return html

    # ---------- API ----------
    def get(self, url, use_cache=True, _goodreads_block_retries=0):
        """Returneaza HTML (str) sau None (404 / interzis de robots)."""
        cp = self._cache_path(url)
        if use_cache and cp.exists():
            return cp.read_text(encoding="utf-8")

        domain = self._domain(url)
        if self._blocks.get(domain, 0) >= self.block_limit:
            raise BlockedError(f"{domain}: prea multe blocaje")
        if not self._allowed(url, domain):
            return None

        for attempt in range(self.max_retries):
            self._wait(domain)
            sess = self._session(domain)
            headers = {}
            if domain in self._last_url:
                headers["Referer"] = self._last_url[domain]
            try:
                resp = sess.get(url, headers=headers, timeout=self.timeout,
                                proxies=self._pick_proxy(domain))
                self._last_req[domain] = time.time()
            except requests.RequestException as e:
                self._last_req[domain] = time.time()
                log.warning("eroare retea %s: %s", url, e)
                self._backoff(domain, attempt, None, rotate=True)
                continue

            status, text = resp.status_code, resp.text
            waf_action = resp.headers.get("x-amzn-waf-action", "")
            if "challenge" in waf_action.lower():
                log.warning("[%s] WAF challenge (%s) pe %s", domain, status, url)
                if domain == "goodreads.com" and self.scrapfly_key:
                    html = self._get_via_scrapfly(url)
                    if html:
                        self._blocks[domain] = 0
                        self._last_url[domain] = url
                        cp.write_text(html, encoding="utf-8")
                        return html
                if domain == "goodreads.com" and _goodreads_block_retries < len(self.goodreads_block_waits):
                    wait = self.goodreads_block_waits[_goodreads_block_retries]
                    log.warning("[%s] WAF: pauză %ds, apoi reîncerc aceeași cerere (%d/%d)",
                                domain, wait, _goodreads_block_retries + 1,
                                len(self.goodreads_block_waits))
                    time.sleep(wait)
                    self._blocks[domain] = 0
                    return self.get(url, use_cache=use_cache,
                                    _goodreads_block_retries=_goodreads_block_retries + 1)
                self._blocks[domain] = self.block_limit
                log.warning("[%s] opresc cererile dupa WAF challenge", domain)
                raise BlockedError(f"{domain}: WAF challenge")
            captcha = status == 200 and len(text) < 5000 and "captcha" in text.lower()
            if status == 200 and not captcha:
                self._blocks[domain] = 0
                self._last_url[domain] = url
                cp.write_text(text, encoding="utf-8")
                return text
            if status in (404, 410):
                return None
            if status == 403 and domain in self.fail_fast_403_domains:
                self._blocks[domain] = self.block_limit
                log.error("[%s] acces refuzat (403); opresc fără retry. Verifică mai târziu sau folosește o sursă autorizată.", domain)
                raise BlockedError(f"{domain}: acces refuzat (403)")
            if status in (403, 429) or captcha:
                self._blocks[domain] = self._blocks.get(domain, 0) + 1
                details = []
                for header in ("Server", "Via", "Retry-After", "X-Amzn-Waf-Action", "CF-Ray"):
                    value = resp.headers.get(header)
                    if value:
                        details.append(f"{header}={value}")
                title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:160]
                    if title:
                        details.append(f"title={title!r}")
                suffix = f" ({'; '.join(details)})" if details else ""
                log.warning("[%s] blocat/limitat (%s) pe %s%s", domain, status, url, suffix)
                if self._blocks[domain] >= self.block_limit:
                    if domain == "goodreads.com" and _goodreads_block_retries < len(self.goodreads_block_waits):
                        wait = self.goodreads_block_waits[_goodreads_block_retries]
                        log.warning("[%s] blocaje repetate: pauză %ds, apoi reîncerc aceeași cerere (%d/%d)",
                                    domain, wait, _goodreads_block_retries + 1,
                                    len(self.goodreads_block_waits))
                        time.sleep(wait)
                        self._blocks[domain] = 0
                        return self.get(url, use_cache=use_cache,
                                        _goodreads_block_retries=_goodreads_block_retries + 1)
                    raise BlockedError(f"{domain}: {self._blocks[domain]} blocaje consecutive")
            else:
                detail = f", x-amzn-waf-action={waf_action}" if waf_action else ""
                log.warning("[%s] raspuns HTTP %s pe %s%s", domain, status, url, detail)
            self._backoff(domain, attempt, resp.headers.get("Retry-After"), rotate=True)
        log.error("renunt la %s dupa %d incercari", url, self.max_retries)
        return None

    def _backoff(self, domain, attempt, retry_after, rotate):
        try:
            wait = float(retry_after)
        except (TypeError, ValueError):
            wait = 0
        wait = max(wait, 10 * 2 ** attempt) + random.uniform(0, 8)
        log.info("[%s] backoff %.0fs", domain, wait)
        time.sleep(wait)
        if rotate:
            self._session(domain, fresh=True)          # alt User-Agent + cookie-uri curate
            self._pick_proxy(domain, rotate=True)      # alt proxy (daca exista)

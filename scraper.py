import os
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from tqdm import tqdm

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL    = "https://dharmaebooks.org/tag/tibetan/"
HEADERS     = {"User-Agent": "Mozilla/5.0 (compatible; DharmaEbookScraper/1.0)"}
CRAWL_DELAY = 3          # seconds between requests (respect robots.txt guidance)
DATA_DIR    = "data"
EPUB_DIR    = os.path.join(DATA_DIR, "epub")
PDF_DIR     = os.path.join(DATA_DIR, "pdf")
LOG_FILE    = "scraper.log"

os.makedirs(EPUB_DIR, exist_ok=True)
os.makedirs(PDF_DIR,  exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_get(url: str) -> requests.Response | None:
    """GET a URL with error handling; returns None on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        time.sleep(CRAWL_DELAY)
        return r
    except requests.RequestException as e:
        log.error(f"Request failed for {url}: {e}")
        return None


def slugify(text: str) -> str:
    """Convert a book title to a safe filename-friendly slug."""
    # Keep ASCII alphanumerics, replace everything else with '-'
    slug = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:80]  # cap length


def get_soup(url: str) -> BeautifulSoup | None:
    r = safe_get(url)
    return BeautifulSoup(r.text, "html.parser") if r else None


# ── Core scraping logic ────────────────────────────────────────────────────────

def get_page_url(page: int) -> str:
    """
    Page 1  → https://dharmaebooks.org/tag/tibetan/
    Page 2+ → https://dharmaebooks.org/tag/tibetan/page/2/
    """
    if page == 1:
        return BASE_URL
    return f"{BASE_URL}page/{page}/"


def extract_books_from_listing(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """
    Pull book entries directly from the tag listing page.

    Each <article> contains:
      - The book title in an <h3> or <h2> <a>
      - Direct EPUB / PDF download links as anchor text "EPUB" / "PDF"

    FIX #1 & #2: We detect links by their *visible text* ("EPUB"/"PDF"),
    not by file extension.  The real URLs end in /download — no extension.
    """
    books = []

    for article in soup.find_all("article"):
        # ── Title ──────────────────────────────────────────────────────────
        title_tag = article.find(["h2", "h3"])
        title = title_tag.get_text(strip=True) if title_tag else "untitled"

        # ── Download links ─────────────────────────────────────────────────
        epub_url = None
        pdf_url  = None

        for a in article.find_all("a", href=True):
            link_text = a.get_text(strip=True).upper()
            href = urljoin(page_url, a["href"])

            if link_text == "EPUB" and epub_url is None:
                epub_url = href
            elif link_text == "PDF" and pdf_url is None:
                pdf_url = href

        if epub_url or pdf_url:
            books.append({
                "title":    title,
                "epub_url": epub_url,
                "pdf_url":  pdf_url,
            })
        else:
            # Fall back: visit individual book page
            book_link_tag = article.find("a", href=True)
            if book_link_tag:
                books.append({
                    "title":     title,
                    "epub_url":  None,
                    "pdf_url":   None,
                    "book_page": urljoin(page_url, book_link_tag["href"]),
                })

    log.info(f"  → Found {len(books)} book entries on this page")
    return books


def resolve_book_page(book: dict) -> dict:
    """
    FIX #1 applied to individual book pages:
    Detect EPUB/PDF links by anchor text, not file extension.
    """
    url = book.get("book_page")
    if not url:
        return book

    log.info(f"  Visiting book page: {url}")
    soup = get_soup(url)
    if not soup:
        return book

    for a in soup.find_all("a", href=True):
        link_text = a.get_text(strip=True).upper()
        href = urljoin(url, a["href"])

        if link_text == "EPUB" and not book["epub_url"]:
            book["epub_url"] = href
        elif link_text == "PDF" and not book["pdf_url"]:
            book["pdf_url"] = href

    return book


def choose_file(book: dict) -> tuple[str | None, str | None]:
    """
    Apply priority: EPUB first, PDF as fallback.
    Returns (url, format_label) or (None, None).
    """
    if book.get("epub_url"):
        return book["epub_url"], "epub"
    if book.get("pdf_url"):
        return book["pdf_url"], "pdf"
    return None, None


def download_file(url: str, title: str, fmt: str) -> bool:
    """
    FIX #3: Build a descriptive filename from title + format.
    FIX #4: Stream the download in chunks.
    """
    slug      = slugify(title)
    filename  = f"{slug}.{fmt}"
    out_dir   = EPUB_DIR if fmt == "epub" else PDF_DIR
    filepath  = os.path.join(out_dir, filename)

    if os.path.exists(filepath):
        log.info(f"  [SKIP] Already exists: {filename}")
        return True

    log.info(f"  [DOWNLOADING] {filename}")
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(filepath, "wb") as f:
                for chunk in tqdm(
                    r.iter_content(chunk_size=8192),
                    total=total // 8192 or None,
                    unit="KB",
                    desc=slug[:40],
                    leave=False,
                ):
                    if chunk:
                        f.write(chunk)
        log.info(f"  [SAVED] {filepath}")
        return True
    except requests.RequestException as e:
        log.error(f"  [FAILED] {filename}: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)   # clean up partial file
        return False


# ── Has-next-page check ────────────────────────────────────────────────────────

def has_next_page(soup: BeautifulSoup) -> bool:
    """Return True if a 'Next' pagination link exists."""
    return bool(soup.find("a", string=re.compile(r"next|›|»", re.I)))


# ── Main entry point ───────────────────────────────────────────────────────────

def scrape(max_pages: int = 999):
    """
    Scrape up to `max_pages` pages of the Tibetan tag.
    Set max_pages=1 for a quick test run.
    """
    stats = {"attempted": 0, "downloaded": 0, "skipped": 0, "failed": 0}

    for page in range(1, max_pages + 1):
        page_url = get_page_url(page)
        log.info(f"\n{'='*60}")
        log.info(f"PAGE {page}: {page_url}")
        log.info(f"{'='*60}")

        soup = get_soup(page_url)
        if soup is None:
            log.warning(f"Could not load page {page}. Stopping.")
            break

        books = extract_books_from_listing(soup, page_url)
        if not books:
            log.info("No books found on this page. Stopping pagination.")
            break

        for book in books:
            log.info(f"\n  Book: {book['title'][:80]}")

            # Resolve via individual page only if needed
            if not book.get("epub_url") and not book.get("pdf_url"):
                book = resolve_book_page(book)

            file_url, fmt = choose_file(book)

            if not file_url:
                log.warning("  [NO FILE] No EPUB or PDF found.")
                stats["failed"] += 1
                continue

            log.info(f"  Format selected: {fmt.upper()}")
            stats["attempted"] += 1

            ok = download_file(file_url, book["title"], fmt)
            if ok:
                if "SKIP" in open(LOG_FILE, encoding="utf-8").read().split("\n")[-3]:
                    stats["skipped"] += 1
                else:
                    stats["downloaded"] += 1
            else:
                stats["failed"] += 1

        if not has_next_page(soup):
            log.info("No next page found. Scraping complete.")
            break

    log.info(f"\n{'='*60}")
    log.info("FINAL STATS")
    log.info(f"  Attempted : {stats['attempted']}")
    log.info(f"  Downloaded: {stats['downloaded']}")
    log.info(f"  Skipped   : {stats['skipped']}  (already on disk)")
    log.info(f"  Failed    : {stats['failed']}")
    log.info(f"  Output dirs: {os.path.abspath(EPUB_DIR)}  (epub)")
    log.info(f"               {os.path.abspath(PDF_DIR)}   (pdf)")


if __name__ == "__main__":
    # Change max_pages to a higher number (or remove the arg) to scrape all pages
    scrape(max_pages=1)
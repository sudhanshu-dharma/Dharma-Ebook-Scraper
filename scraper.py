import os
import re
import json
import time
import logging
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from tqdm import tqdm

# ── Configuration ──────────────────────────────────────────────────────────────
BASE_URL    = "https://dharmaebooks.org/tag/tibetan/"
HEADERS     = {"User-Agent": "Mozilla/5.0 (compatible; DharmaEbookScraper/1.0)"}
CRAWL_DELAY = 2          # seconds between requests (be polite)
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_get(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        time.sleep(CRAWL_DELAY)
        return r
    except requests.RequestException as e:
        log.error(f"Request failed — {url}: {e}")
        return None


def get_soup(url: str) -> BeautifulSoup | None:
    r = safe_get(url)
    return BeautifulSoup(r.text, "html.parser") if r else None


def slugify(text: str) -> str:
    """Safe ASCII slug for filenames (max 80 chars)."""
    slug = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:80] or "untitled"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Metadata extraction ────────────────────────────────────────────────────────

def extract_metadata(book_url: str) -> dict:
    """
    Visit a book's individual page and extract every available metadata field.

    Fields extracted:
      title           — main <h1> heading (Tibetan script)
      subtitle        — English translation in parentheses below title
      author          — credited author line below subtitle
      date_published  — ISO date string (e.g. "2025-10-14")
      tags            — all /tag/ hrefs on the page (language, Karmapa refs, etc.)
      category        — WordPress /category/ label (e.g. "Philosophy", "History")
      language        — always "Tibetan" for this corpus
      cover_image_url — og:image meta tag (highest quality)
      description     — first long body paragraph (Tibetan blurb)
      source_url      — canonical URL of the book page
      epub_url        — direct /download link for EPUB
      pdf_url         — direct /download link for PDF
    """
    meta = {
        "title":           None,
        "subtitle":        None,
        "author":          None,
        "date_published":  None,
        "tags":            [],
        "category":        None,
        "language":        "Tibetan",
        "cover_image_url": None,
        "description":     None,
        "source_url":      book_url,
        "epub_url":        None,
        "pdf_url":         None,
    }

    soup = get_soup(book_url)
    if not soup:
        return meta

    # ── Title ──────────────────────────────────────────────────────────────────
    h1 = soup.find("h1")
    if h1:
        meta["title"] = h1.get_text(strip=True)

    # ── Subtitle + Author ──────────────────────────────────────────────────────
    # The book page structure just below the title:
    #   <p>Tibetan subtitle line\n(English subtitle in parentheses)</p>
    #   <p>Author name(s)</p>
    #   <p>[PDF link]  [EPUB link]</p>
    # We scan the first 8 paragraphs to find these fields.
    content_area = soup.find("div", class_=re.compile(r"entry-content|post-content", re.I))
    if not content_area:
        content_area = soup.find("article") or soup

    paragraphs = content_area.find_all("p") if content_area else soup.find_all("p")
    found_subtitle = False

    for p in paragraphs[:10]:
        text = p.get_text(" ", strip=True)
        if not text:
            continue

        # Subtitle — line containing English translation in parens
        if not meta["subtitle"] and "(" in text and ")" in text and len(text) < 300:
            # Extract just the parenthesised part as the subtitle
            match = re.search(r"\(([^)]{10,})\)", text)
            if match:
                meta["subtitle"] = match.group(1).strip()
                found_subtitle = True
            continue

        # Author — short line after subtitle, before the description block
        if (
            found_subtitle
            and not meta["author"]
            and text
            and len(text) < 200
            and "EPUB" not in text.upper()
            and "PDF"  not in text.upper()
        ):
            meta["author"] = text
            continue

        # Description — first substantial block of body text
        if not meta["description"] and len(text) > 120:
            meta["description"] = text

    # ── Download links ─────────────────────────────────────────────────────────
    for a in soup.find_all("a", href=True):
        label = a.get_text(strip=True).upper()
        href  = urljoin(book_url, a["href"])
        if label == "EPUB" and not meta["epub_url"]:
            meta["epub_url"] = href
        elif label == "PDF" and not meta["pdf_url"]:
            meta["pdf_url"]  = href

    # ── Date published ─────────────────────────────────────────────────────────
    # Rendered as plain text "YYYY-MM-DD" near the tag badges
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", soup.get_text())
    if date_match:
        meta["date_published"] = date_match.group(1)

    # ── Tags ──────────────────────────────────────────────────────────────────
    seen_tags = set()
    for a in soup.find_all("a", href=True):
        if "/tag/" in a["href"]:
            tag = a.get_text(strip=True)
            if tag and tag not in seen_tags:
                meta["tags"].append(tag)
                seen_tags.add(tag)

    # ── Category ──────────────────────────────────────────────────────────────
    for a in soup.find_all("a", href=True):
        if "/category/" in a["href"]:
            meta["category"] = a.get_text(strip=True)
            break

    # ── Cover image ────────────────────────────────────────────────────────────
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        meta["cover_image_url"] = og["content"]
    else:
        img = soup.find("img", src=re.compile(r"uploads", re.I))
        if img:
            meta["cover_image_url"] = img.get("src") or img.get("data-src")

    return meta


# ── Listing-page helpers ───────────────────────────────────────────────────────

def get_page_url(page: int) -> str:
    """Page 1 uses the base URL; subsequent pages use /page/N/."""
    return BASE_URL if page == 1 else f"{BASE_URL}page/{page}/"


def get_book_links(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """Extract {title, book_page} for every article on a listing page."""
    entries = []
    for article in soup.find_all("article"):
        title_tag = article.find(["h2", "h3"])
        title     = title_tag.get_text(strip=True) if title_tag else "untitled"
        link_tag  = article.find("a", href=True)
        if link_tag:
            entries.append({
                "title":     title,
                "book_page": urljoin(page_url, link_tag["href"]),
            })
    return entries


def has_next_page(soup):
    # 1. <link rel="next"> in <head>  ← WordPress always adds this
    if soup.find("link", rel="next"):
        return True

    # 2. Any <a href> containing /page/N/  ← structural, never breaks
    for a in soup.find_all("a", href=True):
        if re.search(r"/page/\d+/", a["href"]):
            return True

    # 3. .get_text() to read through child tags  ← catches "Next" regardless
    for a in soup.find_all("a", href=True):
        if re.search(r"next|›|»", a.get_text(), re.I):
            return True

    return False


# ── Download helpers ───────────────────────────────────────────────────────────

def download_file(url: str, slug: str, fmt: str) -> tuple[bool, str]:
    """Stream-download to data/epub/ or data/pdf/. Returns (success, filepath)."""
    out_dir  = EPUB_DIR if fmt == "epub" else PDF_DIR
    filename = f"{slug}.{fmt}"
    filepath = os.path.join(out_dir, filename)

    if os.path.exists(filepath):
        log.info(f"    [SKIP] Already on disk: {filename}")
        return True, filepath

    log.info(f"    [DOWNLOAD] {filename}")
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(filepath, "wb") as f:
                for chunk in tqdm(
                    r.iter_content(chunk_size=8192),
                    total=total // 8192 or None,
                    unit="KB",
                    desc=filename[:40],
                    leave=False,
                ):
                    if chunk:
                        f.write(chunk)
        log.info(f"    [SAVED] {filepath}")
        return True, filepath
    except requests.RequestException as e:
        log.error(f"    [FAILED] {filename}: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)   # remove partial file
        return False, filepath


def save_meta_json(meta: dict, slug: str, fmt: str) -> None:
    """Write <slug>.meta.json sidecar alongside the ebook file."""
    out_dir   = EPUB_DIR if fmt == "epub" else PDF_DIR
    json_path = os.path.join(out_dir, f"{slug}.meta.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log.info(f"    [META] Saved → {json_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def scrape(max_pages: int = 999):
    """
    Scrape all pages of the Tibetan tag listing.
    max_pages=999 means "run until no next page" (site has ~6 pages / 136 books).
    Pass max_pages=1 for a quick single-page test.
    """
    stats = {"total": 0, "downloaded": 0, "failed": 0}

    for page in range(1, max_pages + 1):
        page_url = get_page_url(page)
        log.info(f"\n{'='*60}")
        log.info(f"PAGE {page}  —  {page_url}")
        log.info(f"{'='*60}")

        soup = get_soup(page_url)
        if soup is None:
            log.warning("Could not fetch page. Stopping.")
            break

        entries = get_book_links(soup, page_url)
        if not entries:
            log.info("No books found on page. Stopping pagination.")
            break

        log.info(f"  {len(entries)} books found")

        for entry in entries:
            stats["total"] += 1
            log.info(f"\n  [{stats['total']}] {entry['title'][:70]}")

            # Full metadata from the individual book page
            meta = extract_metadata(entry["book_page"])
            if not meta["title"]:
                meta["title"] = entry["title"]

            # Priority: EPUB first, PDF fallback
            if meta["epub_url"]:
                file_url, fmt = meta["epub_url"], "epub"
            elif meta["pdf_url"]:
                file_url, fmt = meta["pdf_url"], "pdf"
            else:
                log.warning("    [SKIP] No downloadable file found.")
                stats["failed"] += 1
                continue

            log.info(f"    Format : {fmt.upper()}")
            slug = slugify(meta["title"])

            # Download the ebook
            ok, filepath = download_file(file_url, slug, fmt)

            # Always write meta.json (even on skip — keeps metadata fresh)
            meta["downloaded_format"]   = fmt
            meta["downloaded_filename"] = os.path.basename(filepath)
            meta["scraped_at"]          = now_utc()
            save_meta_json(meta, slug, fmt)

            if ok:
                stats["downloaded"] += 1
            else:
                stats["failed"] += 1

        if not has_next_page(soup):
            log.info("\nNo further pages — scraping complete.")
            break

    # ── Final summary ──────────────────────────────────────────────────────────
    log.info(f"\n{'='*60}")
    log.info("SCRAPE COMPLETE")
    log.info(f"  Total books  : {stats['total']}")
    log.info(f"  Downloaded   : {stats['downloaded']}")
    log.info(f"  Failed/missed: {stats['failed']}")
    log.info(f"  EPUB dir     : {os.path.abspath(EPUB_DIR)}")
    log.info(f"  PDF dir      : {os.path.abspath(PDF_DIR)}")
    log.info(f"  Log file     : {os.path.abspath(LOG_FILE)}")


if __name__ == "__main__":
    scrape()   # runs all pages by default

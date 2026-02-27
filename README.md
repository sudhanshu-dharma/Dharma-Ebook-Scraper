# Dharma Scraper

A Python web scraper for downloading Buddhist texts (ebooks) from [dharmaebooks.org](https://dharmaebooks.org), specifically from the Tibetan language collection. The scraper automatically downloads available EPUB and PDF formats and organizes them by file type.

## Features

- **Intelligent link detection**: Detects download links by anchor text ("EPUB"/"PDF") rather than file extensions for more reliable extraction
- **Multi-format support**: Downloads both EPUB and PDF editions of texts
- **Respectful crawling**: Implements configurable delays between requests to respect server resources
- **Comprehensive logging**: Logs all activities and errors to both console and file
- **Graceful error handling**: Continues processing even when individual book downloads fail
- **Tibetan text support**: Handles Tibetan Unicode filenames correctly
- **Progress tracking**: Uses progress bars to visualize download progress

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd dharma_scraper
```

2. Set up a Python virtual environment (recommended):
```bash
python -m venv web_scrapper
web_scrapper\Scripts\activate  # On Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Dependencies

- **requests** - HTTP library for fetching web pages
- **beautifulsoup4** - HTML parsing and extraction
- **tqdm** - Progress bar visualization

## Usage

Run the scraper:
```bash
python scraper.py
```

The scraper will:
1. Crawl the Tibetan language tag page on dharmaebooks.org
2. Extract book titles and download links from all available pages
3. Download EPUB or PDF files (prioritizing EPUB when both are available)
4. Save files to organized directories:
   - `data/epub/` - EPUB format books
   - `data/pdf/` - PDF format books

## Configuration

Edit the configuration section at the top of `scraper.py` to customize:

```python
BASE_URL    = "https://dharmaebooks.org/tag/tibetan/"  # Target URL
CRAWL_DELAY = 3          # Seconds between requests
DATA_DIR    = "data"     # Root directory for downloads
LOG_FILE    = "scraper.log"  # Log file location
```

## Output

Downloaded files are organized as:
```
data/
├── epub/
│   ├── དབངསཅནདགའབ.epub
│   └── ...
└── pdf/
    ├── ཕགཆནཆསསམཛབཚགས.epub
    └── ...
```

Activity is logged to:
- **Console**: Real-time progress and status messages
- **scraper.log**: Complete record of all operations and errors

## Controlling Extraction Pages

To limit the number of pages extracted, modify the `scrape()` function call in `scraper.py`. Use the `max_pages` parameter to control how many pages are crawled (e.g., `scrape(max_pages=1)` to extract only the first page, or increase the value for more pages).

## 📦 Download Dataset

## Latest Dataset Release

- **v2.0.0**
- File: tibetan-ebooks-corpus_v2.zip
- Includes additional books and improved metadata
- [Download]: (https://github.com/sudhanshu-dharma/Dharma-Ebook-Scraper/releases/tag/v2.0.0)
Includes 127 books with `meta.json`, scraped from dharmaebooks.org.


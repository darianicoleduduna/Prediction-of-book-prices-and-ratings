"""Entry point separat pentru scraperul Cărturești.

Exemple:
  python run_carturesti_scraper.py --queries fantasy thriller --pages 3 --limit 100
  python run_carturesti_scraper.py --probe https://carturesti.ro/carte/...
  python run_carturesti_scraper.py --urls-file urls_carturesti.txt --out data/carturesti.csv

Opțiunile de scraping sunt aceleași ca în run_scraper.py, dar sursa implicită
este doar Cărturești.
"""
from run_scraper import main


if __name__ == "__main__":
    main(default_sites=["carturesti"])

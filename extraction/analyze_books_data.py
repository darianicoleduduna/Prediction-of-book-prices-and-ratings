"""Summarize and plot ratings, prices, publication years, languages, and cover types."""
import argparse
import csv
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path


def parse_decimal(value):
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_year(value):
    match = re.search(r"\b(1[45]\d{2}|1[5-9]\d{2}|20\d{2}|2100)\b", str(value or ""))
    return int(match.group(1)) if match else None


def normalize_text(value):
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(char for char in text if not unicodedata.combining(char)).strip()


def language_group(value):
    text = normalize_text(value)
    if not text:
        return "Missing"
    if "rom" in text:
        return "Romanian"
    if "eng" in text:
        return "English"
    return "Other languages"


def cover_group(value):
    text = normalize_text(value)
    if not text:
        return "Missing"
    if "hardcover" in text or "hard cover" in text:
        return "Hardcover"
    if "paperback" in text or "softcover" in text or "soft cover" in text:
        return "Paperback"
    return "Other types"


def save_histogram(plt, values, output, title, xlabel, bins=20, value_range=None,
                   x_limits=None):
    figure, axis = plt.subplots(figsize=(9, 5))
    axis.hist(values, bins=bins, range=value_range, color="#4776a8", edgecolor="white")
    if x_limits is not None:
        axis.set_xlim(*x_limits)
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel("Number of books")
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def save_bar_chart(plt, counts, output, title, xlabel):
    labels = list(counts.keys())
    values = list(counts.values())
    figure, axis = plt.subplots(figsize=(8, 5))
    bars = axis.bar(labels, values, color="#4776a8")
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel("Number of books")
    axis.tick_params(axis="x", rotation=20)
    axis.grid(axis="y", alpha=0.25)
    axis.bar_label(bars, padding=3)
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input", default="data/preprocessed/books_extracted_with_rating.csv")
    parser.add_argument("--out-dir", default="data/preprocessed/figures")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.out_dir)
    if not input_path.is_file():
        raise SystemExit(f"Nu există fișierul de intrare: {input_path}")

    with input_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        required = {"rating", "pret", "an_aparitie", "limba", "coperta"}
        missing = required - set(fields)
        if missing:
            raise SystemExit(f"Lipsesc coloanele necesare: {', '.join(sorted(missing))}")
        rows = list(reader)

    ratings = [value for row in rows if (value := parse_decimal(row.get("rating"))) is not None
               and 0 <= value <= 5]
    prices = [value for row in rows if (value := parse_decimal(row.get("pret"))) is not None
              and value >= 0]
    years = [value for row in rows if (value := parse_year(row.get("an_aparitie"))) is not None]
    languages = Counter(language_group(row.get("limba")) for row in rows)
    covers = Counter(cover_group(row.get("coperta")) for row in rows)
    decades = Counter(f"{(year // 10) * 10}s" for year in years)

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("Este necesar matplotlib. Dependența este inclusă în requirements.txt.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    save_histogram(plt, ratings, output_dir / "rating_distribution.png",
                   "Goodreads Rating Distribution", "Rating", bins=25, value_range=(0, 5))
    price_limits = None
    if prices:
        price_min, price_max = min(prices), max(prices)
        if price_min == price_max:
            padding = max(abs(price_min) * 0.01, 0.5)
            price_limits = (price_min - padding, price_max + padding)
        else:
            price_limits = (price_min, price_max)
    save_histogram(plt, prices, output_dir / "price_distribution.png",
                   "Price Distribution", "Price (as listed)",
                   value_range=price_limits, x_limits=price_limits)
    save_histogram(plt, years, output_dir / "publication_year_distribution.png",
                   "Publication Year Distribution", "Publication year", bins=35)
    save_bar_chart(plt, languages, output_dir / "language_distribution.png",
                   "Language Distribution", "Language")
    save_bar_chart(plt, covers, output_dir / "cover_type_distribution.png",
                   "Cover Type Distribution", "Cover type")

    print(f"Records analyzed: {len(rows)}")
    print(f"Valid ratings: {len(ratings)}")
    print(f"Valid prices: {len(prices)}")
    price_ranges = [
        ("Under 25", 0, 25), ("25-49.99", 25, 50), ("50-74.99", 50, 75),
        ("75-99.99", 75, 100), ("100-149.99", 100, 150),
        ("150-199.99", 150, 200), ("200-299.99", 200, 300),
        ("300-499.99", 300, 500), ("500+", 500, float("inf")),
    ]
    if prices:
        print("Price ranges:")
        for label, lower, upper in price_ranges:
            count = sum(lower <= price < upper for price in prices)
            percentage = count / len(prices) * 100
            print(f"  {label}: {count} ({percentage:.1f}%)")
    if ratings:
        print(f"Average rating: {statistics.mean(ratings):.2f}")
        print(f"Median rating: {statistics.median(ratings):.2f}")
    print(f"Valid publication years: {len(years)}")
    if years:
        print(f"Publication year range: {min(years)}–{max(years)}")
    print("Languages:")
    for label, count in languages.most_common():
        print(f"  {label}: {count}")
    print("Cover types:")
    for label, count in covers.most_common():
        print(f"  {label}: {count}")
    print("Publication years by decade:")
    for label, count in sorted(decades.items()):
        print(f"  {label}: {count}")
    print(f"Charts saved to: {output_dir}")


if __name__ == "__main__":
    main()

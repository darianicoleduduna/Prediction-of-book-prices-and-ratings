"""Keep only rows with a populated rating from the combined book dataset."""
import argparse
import csv
from pathlib import Path


EXCLUDED_COLUMNS = {
    "url",
    "goodreads_url",
    "nr_ratinguri",
    "moneda",
    "isbn",
    "goodreads_match",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input", default="data/raw/extracted_data.csv")
    parser.add_argument("--out", default="data/preprocessed/books_extracted_with_rating.csv")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.out)
    if not input_path.is_file():
        raise SystemExit(f"Nu există fișierul de intrare: {input_path}")
    if input_path.resolve() == output_path.resolve():
        raise SystemExit("Fișierul rezultat trebuie să fie separat de fișierul sursă.")

    with input_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if "rating" not in fields:
            raise SystemExit(f"CSV-ul nu are coloana 'rating': {input_path}")
        output_fields = [field for field in fields if field not in EXCLUDED_COLUMNS]
        rows = list(reader)

    rated_rows = [row for row in rows if (row.get("rating") or "").strip()]
    for row in rated_rows:
        if not (row.get("coperta") or "").strip():
            row["coperta"] = "paperback"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=output_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rated_rows)
    temp_path.replace(output_path)

    print(f"Rânduri citite: {len(rows)}")
    print(f"Rânduri păstrate cu rating: {len(rated_rows)}")
    print(f"Rânduri fără rating eliminate: {len(rows) - len(rated_rows)}")
    print(f"Fișier rezultat: {output_path}")


if __name__ == "__main__":
    main()

"""Combine the store-specific book CSV files into one dataset."""
import argparse
import csv
from pathlib import Path


DEFAULT_INPUTS = [
    "data/raw/carti_elefant.csv",
    "data/raw/carti_bookzone.csv",
    "data/raw/date_libris2.csv",
    "data/raw/date_libristo.csv",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", nargs="+", default=DEFAULT_INPUTS,
        help="CSV-urile de combinat (implicit: fișierele Elefant, Bookzone, Libris și Libristo)",
    )
    parser.add_argument("--out", default="data/raw/extracted_data.csv",
                        help="fișierul rezultat (implicit: data/raw/extracted_data.csv)")
    args = parser.parse_args()

    input_paths = [Path(path) for path in args.inputs]
    output_path = Path(args.out)
    output_resolved = output_path.resolve()
    for path in input_paths:
        if not path.is_file():
            raise SystemExit(f"Nu există fișierul de intrare: {path}")
        if path.resolve() == output_resolved:
            raise SystemExit("Fișierul rezultat nu poate fi unul dintre fișierele de intrare.")

    fieldnames = []
    all_rows = []
    source_counts = []
    for path in input_paths:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise SystemExit(f"CSV-ul nu are antet: {path}")
            for field in reader.fieldnames:
                if field not in fieldnames:
                    fieldnames.append(field)
            rows = list(reader)
            all_rows.extend(rows)
            source_counts.append((path, len(rows)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    temp_path.replace(output_path)

    for path, count in source_counts:
        print(f"{path}: {count} cărți")
    print(f"Gata: {output_path} — {len(all_rows)} rânduri în total.")


if __name__ == "__main__":
    main()

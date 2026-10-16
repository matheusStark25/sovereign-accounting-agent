from __future__ import annotations
import csv
from pathlib import Path
from typing import Iterator, Dict


class CSVHandler:
    """Robust CSV reader/writer for input and output directories.

    - Reads all CSV files in `input_dir`
    - Writes aggregated results to `output_path` (creates folder if needed)
    """

    def __init__(self, input_dir: str = "data/input", output_dir: str = "data/output") -> None:
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def read_rows(self) -> Iterator[Dict[str, str]]:
        for path in sorted(self.input_dir.glob("*.csv")):
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        yield dict(row)
            except Exception:
                # Continue on file-level errors; individual row errors are handled elsewhere
                continue

    def write_results(self, filename: str, fieldnames: list, rows: Iterator[Dict[str, str]]) -> None:
        out_path = self.output_dir / filename
        try:
            with out_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
        except Exception:
            # Let caller audit/log errors
            raise

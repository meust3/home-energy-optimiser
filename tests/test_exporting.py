import csv

from energy_optimizer.exporting import export_rows_to_csv


def test_csv_export_preserves_null_and_values(tmp_path):
    output = tmp_path / "export.csv"
    rows = [
        {"slot_utc": "2026-08-01T00:00:00+00:00", "house_consumption_w": 1200},
        {"slot_utc": "2026-08-01T00:05:00+00:00", "house_consumption_w": None},
    ]
    count = export_rows_to_csv(rows, output)
    with output.open(newline="", encoding="utf-8") as handle:
        exported = list(csv.DictReader(handle))
    assert count == 2
    assert exported[0]["house_consumption_w"] == "1200"
    assert exported[1]["house_consumption_w"] == ""

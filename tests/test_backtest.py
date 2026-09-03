import csv
import json
from pathlib import Path

from fdt.eval.backtest import run_all


def test_run_all_writes_json_and_profile_csvs(tmp_path, monkeypatch):
    """§11.4 JSON·CSV 경로, 열·행 수, UTF-8 계약을 확인한다."""
    monkeypatch.chdir(tmp_path)
    report = run_all(Path(__file__).parents[1] / "data" / "seed")

    output_dir = tmp_path / "data" / "out" / "eval"
    report_path = output_dir / "backtest.json"
    assert report_path.is_file()
    assert json.loads(report_path.read_text(encoding="utf-8")) == report

    csv_paths = sorted(output_dir.glob("backtest_*.csv"))
    assert len(csv_paths) == report["count"] == 3
    for csv_path in csv_paths:
        csv_path.read_bytes().decode("utf-8")
        with csv_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            assert reader.fieldnames == ["date", "p10", "median", "p90", "truth"]
            rows = list(reader)
        assert len(rows) == 30

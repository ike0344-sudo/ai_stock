import os
import time

from backtesting.backtest_results import list_results, read_result


def test_list_results_returns_empty_when_dir_missing(tmp_path):
    results = list_results(str(tmp_path / "nonexistent"))

    assert results == []


def test_list_results_sorted_by_created_at_descending(tmp_path):
    (tmp_path / "old.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    time.sleep(0.01)
    (tmp_path / "new.csv").write_text("a,b\n3,4\n", encoding="utf-8")

    results = list_results(str(tmp_path))

    assert [r["filename"] for r in results] == ["new.csv", "old.csv"]


def test_list_results_ignores_non_csv_files(tmp_path):
    (tmp_path / "result.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")

    results = list_results(str(tmp_path))

    assert [r["filename"] for r in results] == ["result.csv"]


def test_read_result_parses_columns_and_rows(tmp_path):
    (tmp_path / "ma_crossover_20260720_143000.csv").write_text(
        "stock_code,total_return_pct\n005930,12.5\n000660,-3.2\n", encoding="utf-8"
    )

    result = read_result(str(tmp_path), "ma_crossover_20260720_143000.csv")

    assert result["filename"] == "ma_crossover_20260720_143000.csv"
    assert result["columns"] == ["stock_code", "total_return_pct"]
    assert result["rows"] == [
        {"stock_code": "005930", "total_return_pct": "12.5"},
        {"stock_code": "000660", "total_return_pct": "-3.2"},
    ]


def test_read_result_returns_none_for_missing_file(tmp_path):
    result = read_result(str(tmp_path), "does_not_exist.csv")

    assert result is None


def test_read_result_rejects_path_traversal_attempts(tmp_path):
    secret = tmp_path.parent / "secret.csv"
    secret.write_text("leak\n", encoding="utf-8")

    result = read_result(str(tmp_path), "../secret.csv")

    assert result is None

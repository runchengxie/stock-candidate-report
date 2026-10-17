import hashlib
from zipfile import ZipFile

import pytest

from stock_candidate_report.watchlist import import_watchlist, save_watchlist


def fixture_sheet(path, rows):
    # A small OOXML fixture, not a delivered workbook.
    content = "".join(
        '<row r="{}">{}</row>'.format(
            i,
            "".join(
                f'<c r="{chr(65 + j)}{i}" t="inlineStr"><is><t>{v}</t></is></c>'
                for j, v in enumerate(row)
            ),
        )
        for i, row in enumerate(rows, 1)
    )
    with ZipFile(path, "w") as z:
        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>" + content + "</sheetData></worksheet>",
        )


def test_import_groups_and_input_unchanged(tmp_path):
    p = tmp_path / "input.xlsx"
    fixture_sheet(
        p,
        [
            ["", "Symbol", "Name"],
            ["AI", "GOOG", "Alphabet"],
            ["", "BRK-B", "Berkshire"],
            ["", "", ""],
            ["", "说明：测试", ""],
        ],
    )
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    items = import_watchlist(p)
    assert [(x.symbol, x.group) for x in items] == [("GOOG", "AI"), ("BRK-B", "AI")]
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    dest = tmp_path / "watchlist.json"
    save_watchlist(items, dest)
    with pytest.raises(FileExistsError):
        save_watchlist(items, dest)


def test_duplicates_report_both_rows(tmp_path):
    p = tmp_path / "input.xlsx"
    fixture_sheet(p, [["", "Symbol", "Name"], ["", "GOOG", ""], ["", "goog", ""]])
    with pytest.raises(ValueError, match=r"2.*3"):
        import_watchlist(p)


def test_invalid_ticker_in_stock_row(tmp_path):
    p = tmp_path / "input.xlsx"
    fixture_sheet(p, [["", "Symbol", "Name"], ["AI", "bad ticker", "Company"]])
    with pytest.raises(ValueError, match="row 2"):
        import_watchlist(p)

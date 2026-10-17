import builtins
import json

import pytest

from stock_candidate_report.export import export_report
from stock_candidate_report.models import RunResult


def test_default_json_export_needs_no_excel_dependency(tmp_path, monkeypatch):
    original_import = builtins.__import__

    def without_excel(name, *args, **kwargs):
        if name == "openpyxl" or name.startswith("openpyxl."):
            raise ModuleNotFoundError("No module named 'openpyxl'", name="openpyxl")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_excel)
    result = RunResult("json-only", [], [], [], {"prices_available": 0})
    workbook, manifest = export_report(result, 2026, tmp_path)
    assert workbook is None
    assert json.loads(manifest.read_text(encoding="utf-8"))["report_year"] == 2026
    assert [p.name for p in tmp_path.iterdir()] == ["候选股-json-only.json"]
    with pytest.raises(FileExistsError):
        export_report(result, 2026, tmp_path)


def test_missing_excel_extra_keeps_json_and_explains_install(tmp_path, monkeypatch):
    original_import = builtins.__import__

    def without_excel(name, *args, **kwargs):
        if name == "openpyxl":
            raise ModuleNotFoundError("No module named 'openpyxl'", name="openpyxl")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_excel)
    result = RunResult("missing-extra", [], [], [], {})
    with pytest.raises(RuntimeError, match="uv sync --extra excel"):
        export_report(result, 2026, tmp_path, excel=True)
    assert (tmp_path / "候选股-missing-extra.json").is_file()
    assert not list(tmp_path.glob("*.xlsx"))

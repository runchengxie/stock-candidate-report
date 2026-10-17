import json
import re
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .models import WatchItem

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-^=]{0,19}\Z")


def import_watchlist(path: Path) -> list[WatchItem]:
    with ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = [
                "".join(node.itertext()) for node in ET.fromstring(z.read("xl/sharedStrings.xml"))
            ]
        files = [x for x in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+.xml", x)]
        for filename in files:
            rows = ET.fromstring(z.read(filename)).findall("m:sheetData/m:row", NS)
            header, items, seen, group = None, [], {}, ""
            for row in rows:
                cells = {}
                for c in row:
                    column = re.sub(r"\d", "", c.get("r", ""))
                    value = c.find("m:v", NS)
                    value = value.text if value is not None else ""
                    if c.get("t") == "s":
                        value = strings[int(value)]
                    elif c.get("t") == "inlineStr":
                        node = c.find("m:is", NS)
                        value = "".join(node.itertext()) if node is not None else ""
                    cells[column] = str(value or "").strip()
                if header is None:
                    symbols = [k for k, v in cells.items() if v.casefold() == "symbol"]
                    if symbols:
                        names = [k for k, v in cells.items() if v.casefold() == "name"]
                        header = symbols[0], names[0] if names else "C"
                    continue
                raw = cells.get(header[0], "")
                name = cells.get(header[1], "")
                if not raw:
                    continue
                symbol = raw.upper()
                number = row.get("r", "?")
                if not TICKER.fullmatch(symbol):
                    if not name and not cells.get("A", ""):
                        continue  # A non-stock note without a company or grouping.
                    raise ValueError(f"Invalid Symbol at row {number}: {raw}")
                if symbol in seen:
                    raise ValueError(f"Duplicate {symbol} at rows {seen[symbol]} and {number}")
                seen[symbol] = number
                group = cells.get("A", "") or group
                items.append(WatchItem(symbol, name, group))
            if header is not None:
                if not items:
                    raise ValueError("No candidate stocks under Symbol header")
                return items
    raise ValueError("Workbook requires a Symbol header")


def save_watchlist(items: list[WatchItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump([asdict(x) for x in items], f, ensure_ascii=False, indent=2)


def load_watchlist(path: Path) -> list[WatchItem]:
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    items, seen = [], set()
    for row in rows:
        item = WatchItem(**row)
        if not TICKER.fullmatch(item.symbol) or item.symbol in seen:
            raise ValueError(f"Invalid or duplicate Symbol: {item.symbol}")
        seen.add(item.symbol)
        items.append(item)
    if not items:
        raise ValueError("Empty watchlist")
    return items

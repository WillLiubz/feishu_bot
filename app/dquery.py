import csv
import re
import tempfile
from pathlib import Path


def write_csv_to(rows, path):
    """Write list[dict] to path as UTF-8 BOM CSV. Overwrites if exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("(no data)\n", encoding="utf-8-sig")
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(rows):
    """Write to a temp file, return file path string. Used by reports."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline=""
    ) as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return f.name


def _sheet_name(sql, index):
    """Derive a short sheet name from SQL and query index."""
    # Extract first table name after FROM/JOIN
    m = re.search(r'\bFROM\s+(\S+)', sql, re.IGNORECASE)
    if not m:
        m = re.search(r'\bJOIN\s+(\S+)', sql, re.IGNORECASE)
    if m:
        # Keep only the last part (after dot) and trim to 20 chars
        tbl = m.group(1).split('.')[-1].strip('`"\' ')[:20]
        name = f"查询{index}_{tbl}"
    else:
        name = f"查询{index}"
    # Excel sheet names max 31 chars, no special chars
    name = re.sub(r'[\\/*?\[\]:]', '_', name)
    return name[:31]


def combine_to_excel(result_dir):
    """
    Combine all query_N.csv files in result_dir into a multi-sheet Excel.
    Returns the path to the generated xlsx file, or None if no query files found.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    result_dir = Path(result_dir)
    # Collect query_N.csv files in order
    query_files = sorted(
        result_dir.glob("query_*.csv"),
        key=lambda p: int(re.search(r'query_(\d+)', p.stem).group(1))
    )
    if not query_files:
        return None

    wb = Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")

    for i, csv_path in enumerate(query_files, 1):
        # Read CSV
        rows = []
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Read SQL label from adjacent .sql file if exists, else parse from csv name
        sql_file = csv_path.with_suffix('.sql')
        sql_text = sql_file.read_text(encoding="utf-8") if sql_file.exists() else ""
        sheet_name = _sheet_name(sql_text, i)

        ws = wb.create_sheet(title=sheet_name)

        if not rows or (len(rows) == 1 and list(rows[0].values()) == ["(no data)"]):
            ws.cell(1, 1, "(no data)")
            continue

        headers = list(rows[0].keys())

        # Header row with styling
        for ci, h in enumerate(headers, 1):
            cell = ws.cell(1, ci, h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        # Data rows
        for ri, row in enumerate(rows, 2):
            for ci, h in enumerate(headers, 1):
                ws.cell(ri, ci, row.get(h, ""))

        # Auto column width (max 40)
        for ci, h in enumerate(headers, 1):
            max_len = max(len(str(h)), max((len(str(r.get(h, ""))) for r in rows), default=0))
            ws.column_dimensions[get_column_letter(ci)].width = min(max_len + 2, 40)

        # Append SQL at the bottom (separated by a blank row)
        if sql_text:
            sql_row = len(rows) + 3  # data ends at len(rows)+1, blank row at +2
            label_cell = ws.cell(sql_row, 1, "【SQL】")
            label_cell.font = Font(bold=True, color="595959")
            sql_cell = ws.cell(sql_row + 1, 1, sql_text.strip())
            sql_cell.font = Font(name="Courier New", size=9, color="595959")
            sql_cell.alignment = Alignment(wrap_text=True)
            ws.row_dimensions[sql_row + 1].height = min(15 * (sql_text.count('\n') + 1), 200)

    if not wb.sheetnames:
        return None

    out_path = result_dir / "result.xlsx"
    wb.save(out_path)
    return str(out_path)


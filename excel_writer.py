"""
Excel export: one .xlsx per run, named <keyword>_<location>_<timestamp>,
with a Listings sheet and a per-directory Summary sheet.

Cells are written via openpyxl as plain strings on purpose: pandas-style
writers coerce digit strings (phone numbers) into numbers, which mangles
them into scientific notation and drops leading zeros.
"""
import re
import time

from openpyxl import Workbook
from openpyxl.styles import Font

COLUMNS = ["Business Name", "Website", "Email", "Description",
           "Contact Number", "Address", "Category", "Source"]
FIELD_FOR_COLUMN = {
    "Business Name": "name", "Website": "website", "Email": "email",
    "Description": "description", "Contact Number": "phone",
    "Address": "address", "Category": "category", "Source": "source",
}

SUMMARY_HEADERS = ["Directory", "Status", "Found", "Exported",
                   "Of those, no email", "Duplicates removed",
                   "Failed/blocked pages", "Notes"]

STATUS_LABELS = {
    "ok": "OK",
    "blocked": "BLOCKED - review separately",
    "skipped_robots": "Skipped (robots.txt)",
    "out_of_region": "Skipped (out of region)",
    "error": "Error",
    "pending": "Not run",
    "running": "Interrupted",
}


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def build_filename(keyword, location):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{slugify(keyword)}_{slugify(location)}_{stamp}.xlsx"


def _autosize(ws, cap=60):
    for idx, column_cells in enumerate(ws.columns, start=1):
        width = max((len(str(c.value)) for c in column_cells if c.value), default=10)
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = min(width + 2, cap)


def write_excel(listings, state, filepath):
    wb = Workbook()

    ws = wb.active
    ws.title = "Listings"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    phone_col = COLUMNS.index("Contact Number") + 1
    for listing in listings:
        ws.append([str(getattr(listing, FIELD_FOR_COLUMN[col], "") or "")
                   for col in COLUMNS])
        # Text format so Excel never reinterprets the number, even on re-save
        ws.cell(row=ws.max_row, column=phone_col).number_format = "@"
    _autosize(ws)

    summary = wb.create_sheet("Summary")
    snapshot = state.snapshot()
    summary.append(["Keyword", snapshot["keyword"]])
    summary.append(["Location", snapshot["location"]])
    summary.append(["Run finished", time.strftime("%Y-%m-%d %H:%M:%S")])
    summary.append(["Businesses exported", len(listings)])
    summary.append([])
    summary.append(SUMMARY_HEADERS)
    header_row = summary.max_row
    for cell in summary[header_row]:
        cell.font = Font(bold=True)
    for d in snapshot["directories"]:
        summary.append([
            d["label"],
            STATUS_LABELS.get(d["status"], d["status"]),
            d["found"], d["kept"], d["no_email"], d["duplicates"],
            d["failed_pages"], d["note"],
        ])
    totals = ["TOTAL", "",
              sum(d["found"] for d in snapshot["directories"]),
              sum(d["kept"] for d in snapshot["directories"]),
              sum(d["no_email"] for d in snapshot["directories"]),
              sum(d["duplicates"] for d in snapshot["directories"]),
              sum(d["failed_pages"] for d in snapshot["directories"]), ""]
    summary.append(totals)
    for cell in summary[summary.max_row]:
        cell.font = Font(bold=True)
    _autosize(summary, cap=70)

    wb.save(filepath)
    return filepath

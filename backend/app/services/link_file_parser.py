import csv
import io

import openpyxl

MAX_ROWS = 10_000


def parse_links_file(filename: str, content: bytes) -> list[str]:
    if filename.lower().endswith(".csv"):
        return _parse_csv(content)
    if filename.lower().endswith(".xlsx"):
        return _parse_xlsx(content)
    raise ValueError("Unsupported file type, expected .csv or .xlsx")


def _parse_csv(content: bytes) -> list[str]:
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    urls = []
    for row in reader:
        if not row:
            continue
        value = row[0].strip()
        if value:
            urls.append(value)
        if len(urls) >= MAX_ROWS:
            break
    return urls


def _parse_xlsx(content: bytes) -> list[str]:
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    urls = []
    for row in sheet.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        value = str(row[0]).strip()
        if value:
            urls.append(value)
        if len(urls) >= MAX_ROWS:
            break
    workbook.close()
    return urls

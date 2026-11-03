"""Manual official-data retrieval only. Never print credentials or request URLs."""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "work/data/local_only/round07c_ecos"


def local_key():
    path = ROOT / ".env"
    if not path.is_file():
        raise ValueError("LOCAL_KEY_NOT_CONFIGURED")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep and name.strip() == "ECOS_API_KEY":
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                return value
    raise ValueError("LOCAL_KEY_NOT_CONFIGURED")


def fetch_pages(service, parameters, key, page_size=1000):
    rows, responses, total, first = [], [], None, 1
    while total is None or first <= total:
        last = first + page_size - 1 if total is None else min(first + page_size - 1, total)
        parts = [service, key, "json", "kr", str(first), str(last), *parameters]
        url = "https://ecos.bok.or.kr/api/" + "/".join(quote(x, safe="") for x in parts)
        try:
            with urlopen(Request(url), timeout=30) as response:
                payload = response.read().decode("utf-8-sig")
        except Exception:
            raise RuntimeError("TRANSPORT_ERROR_REDACTED") from None
        if key in payload:
            raise RuntimeError("RESPONSE_CONTAINED_CREDENTIAL_NOT_SAVED")
        try:
            data = json.loads(payload)
        except Exception:
            raise RuntimeError("NON_JSON_RESPONSE_REDACTED") from None
        if service not in data:
            code = str(data.get("RESULT", {}).get("CODE", "UNKNOWN"))
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", code):
                code = "REDACTED"
            raise RuntimeError("ECOS_RESPONSE_CODE_" + code)
        block = data[service]
        total = int(block["list_total_count"])
        page = block.get("row", [])
        if total < 0 or total > 20000 or not page:
            raise RuntimeError("UNEXPECTED_PAGE_SIZE")
        rows.extend(page)
        responses.append({"page_start": first, "page_end": last, "response": data})
        first = last + 1
    if len(rows) != total:
        raise RuntimeError("PAGINATION_ROW_COUNT_MISMATCH")
    return rows, responses


def main():
    key = local_key()
    mode, *args = sys.argv[1:]
    service = {"tables": "StatisticTableList", "items": "StatisticItemList", "search": "StatisticSearch"}[mode]
    if mode == "tables" and args:
        raise ValueError("TABLE_LIST_TAKES_NO_EXTRA_ARGUMENTS")
    if mode == "items" and len(args) != 1:
        raise ValueError("ITEM_LIST_REQUIRES_TABLE_CODE")
    if mode == "search" and len(args) < 5:
        raise ValueError("SEARCH_REQUIRES_TABLE_CYCLE_START_END_ITEMS")
    page_size = int(os.environ.get("ECOS_PAGE_SIZE", "1000"))
    if not 1 <= page_size <= 1000:
        raise ValueError("PAGE_SIZE_OUT_OF_RANGE")
    rows, responses = fetch_pages(service, args, key, page_size)
    OUT.mkdir(parents=True, exist_ok=True)
    name = "_".join([mode, *args]) + ".json"
    text = json.dumps({"service": service, "parameters_without_key": args,
                       "row_count": len(rows), "pages": responses}, ensure_ascii=False, indent=2)
    if key in text:
        raise RuntimeError("CREDENTIAL_WRITE_BLOCKED")
    (OUT / name).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"authentication": "accepted", "service": service,
                      "rows": len(rows), "pages": len(responses), "local_file": name}, ensure_ascii=False))
    if mode == "tables":
        for row in rows:
            if "기업경기" in str(row.get("STAT_NAME", "")):
                print(json.dumps(row, ensure_ascii=False))
    elif mode == "items":
        for row in rows:
            if any(word in str(row.get("ITEM_NAME", "")) for word in ["자동차", "제조업", "신규수주", "전망"]):
                print(json.dumps(row, ensure_ascii=False))
    else:
        for row in (rows[0], rows[-1]):
            print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No traceback, exception message or urllib URL can expose the API key.
        safe = str(error) if re.fullmatch(r"[A-Z0-9_-]{1,100}", str(error)) else type(error).__name__
        print("COLLECTION_STOPPED: " + safe)
        sys.exit(1)

"""Offline checks of the ROUND 07-C official API snapshot; no model fitting."""
import hashlib
import json
import math
from datetime import datetime, timezone

from collect_round07c_ecos import OUT, ROOT, local_key


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    expected = [f"{2023 + (11 + i) // 12}{(11 + i) % 12 + 1:02}" for i in range(36)]
    samples = load(ROOT / "work/data/local_only/round07_bsi/verified_sample.json")
    sample_index = {(r["sector"], r["forecast_target_month"]): r for r in samples}
    normalized, summaries = [], []
    for code, sector in [("C3000", "automobile"), ("C0000", "manufacturing")]:
        path = OUT / f"search_512Y008_M_202312_202611_BD_{code}.json"
        data = load(path)
        pages = data["pages"]
        assert [(p["page_start"], p["page_end"]) for p in pages] == [(1, 20), (21, 36)]
        rows = [r for p in pages for r in p["response"]["StatisticSearch"]["row"]]
        assert data["row_count"] == len(rows) == 36
        assert all(p["response"]["StatisticSearch"]["list_total_count"] == 36 for p in pages)
        assert [r["TIME"] for r in rows] == expected, "Missing, duplicate or unordered month"
        for r in rows:
            assert (r["STAT_CODE"], r["ITEM_CODE1"], r["ITEM_CODE2"]) == ("512Y008", "BD", code)
            assert r["ITEM_CODE3"] is None and r["ITEM_CODE4"] is None
            value = float(r["DATA_VALUE"])
            assert math.isfinite(value) and 0 <= value <= 200
            assert r["UNIT_NAME"] is None  # Preserve API null; do not invent a returned unit.
            target = r["TIME"][:4] + "-" + r["TIME"][4:]
            year, month = map(int, target.split("-"))
            survey = f"{year - (month == 1):04}-{month - 1 if month > 1 else 12:02}"
            sample = sample_index.get((sector, target))
            if sample:
                assert value == sample["value"] and survey == sample["survey_month"]
            normalized.append({
                "table_code": "512Y008", "item_code1": "BD", "item_code2": code,
                "sector": sector, "api_time": r["TIME"],
                "forecast_target_month": target, "survey_month": survey,
                "value": value, "raw_unit_name": None, "semantic_unit": "index",
                "semantic_unit_basis": "BOK September/October 2026 survey methodology PDFs",
                "comparison_basis": "year_on_year_direction",
                "publication_date": sample["publication_date"] if sample else None,
                "available_at": sample["available_at"] if sample else None,
                "available_policy": "conservative_next_day_KST" if sample else "unverified_do_not_impute",
                "revision_history_verified": False,
                "vintage": "current_ECOS_snapshot_collected_2026-11-03_not_original_release_vintage",
                "sample_break_at_target_month": target == "2026-11",
                "regime": "new_sample_KSIC11" if target >= "2026-11" else "before_2026_10_survey_break",
                "historical_methodology_fully_verified": False,
                "source": "https://ecos.bok.or.kr/", "data_kind": "public_observed_aggregate",
            })
        values = [float(r["DATA_VALUE"]) for r in rows]
        summaries.append({"sector": sector, "item_code2": code, "rows": len(rows),
                          "first": expected[0], "last": expected[-1], "pages": 2,
                          "missing_months": 0, "duplicates": 0, "min": min(values), "max": max(values),
                          "api_unit_null_rows": 36, "pdf_crosschecked_rows": 2})
    checks = {"series": summaries, "total_rows": len(normalized), "pdf_value_checks_passed": 4,
              "publication_date_verified_rows": sum(r["publication_date"] is not None for r in normalized),
              "publication_date_unverified_rows": sum(r["publication_date"] is None for r in normalized),
              "historical_revision_history_verified": False,
              "time_correct_historical_backtest_ready": False}
    key = local_key()
    for name, data in [("normalized_snapshot.json", normalized), ("validation.json", checks)]:
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        assert key not in text, "Credential write blocked"
        (OUT / name).write_text(text, encoding="utf-8")
    manifest = []
    for path in sorted(OUT.glob("*.json")):
        if path.name == "manifest.json":
            continue
        raw = path.read_bytes()
        assert key.encode() not in raw, "Credential detected"
        manifest.append({"file": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                         "file_saved_at_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    print("Local JSON credential scan: PASS")


if __name__ == "__main__":
    main()

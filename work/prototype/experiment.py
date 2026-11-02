"""Synthetic-only one-month FCST. Python standard library; no API/LLM calls."""
import argparse
import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean

UNITS = {"order_lc": "tonnes", "shipment_lc": "tonnes",
         "inventory_report": "tonnes", "production_proxy": "units"}
ASSUMPTIONS = {"prior_mean_t": 100.0, "prior_variance": 2500.0,
               "process_variance": 36.0, "order_noise_sd_t": 45.0,
               "proxy_noise_sd_t": 12.0, "kg_per_unit": 2.0,
               "shares": [0.30, 0.45, 0.60], "primary_share": 0.45,
               "months": 48, "eval_origins": list(range(35, 47))}


def generate(seed, contaminated=False):
    """Truth is simulator-only. A-B attribution is assumed 100%, all synthetic."""
    rng = random.Random(seed)
    truth, events, pipeline, history = [], [], [], []
    inventory = 400.0
    for t in range(48):
        opening = inventory
        receipts = sum(q for due, q, share in pipeline if due == t)
        shipment_lc = sum(q * share for due, q, share in pipeline if due == t + 1)
        pipeline = [(due, q, share) for due, q, share in pipeline if due > t]
        desired = max(0, 100 + 0.5 * t + 18 * math.sin(2 * math.pi * t / 12)
                      + (30 if 38 <= t <= 41 else 0) + rng.gauss(0, 6))
        consumption = min(desired, opening + receipts)
        inventory = opening + receipts - consumption
        history.append(consumption)
        # Customer batches every two months; a two-month receipt lead time.
        outstanding = sum(q for _, q, _ in pipeline)
        order = max(0, 3 * mean(history[-3:]) + 150 - inventory - outstanding) if t % 2 == 0 else 0
        true_share = 0.45
        pipeline.append((t + 2, order, true_share))
        units = max(0, consumption * 1000 / 2 + rng.gauss(0, 3500))
        if contaminated and t >= 30:
            units *= 1.50  # Proxy bias persists; no change to hidden consumption.
        records = [("order_lc", order * true_share, t),
                   ("shipment_lc", shipment_lc, t + 1),
                   ("production_proxy", units, t + 1)]
        if t % 3 == 2:
            records.append(("inventory_report", max(0, inventory + rng.gauss(0, 5)), t + 2))
        for metric, value, available in records:
            events.append({"period": t, "available_at": available, "metric": metric,
                           "value": value, "unit": UNITS[metric], "data_kind": "synthetic"})
        truth.append({"period": t, "C": consumption, "desired_C": desired,
                      "I_open": opening, "R_total": receipts, "I_close": inventory,
                      "O_total": order, "O_LC": order * true_share,
                      "S_LC": shipment_lc, "supplier_share_true": true_share,
                      "W_close": sum(q for _, q, _ in pipeline),
                      "M": 0, "L": 0, "data_kind": "synthetic"})
    return events, truth


def validate(events):
    seen = set()
    for row in events:
        metric = row.get("metric")
        if metric not in UNITS or row.get("unit") != UNITS[metric]:
            raise ValueError("Unknown metric or incorrect unit")
        if row.get("data_kind") != "synthetic":
            raise ValueError("This CLI only accepts explicitly synthetic observations")
        if any(type(row.get(k)) is not int or row[k] < 0 for k in ("period", "available_at")):
            raise ValueError("Periods must be nonnegative integer month indexes")
        if row["available_at"] < row["period"]:
            raise ValueError("Observation cannot be available before its period")
        if not isinstance(row.get("value"), (int, float)) or not math.isfinite(row["value"]) or row["value"] < 0:
            raise ValueError("Observation must be finite and nonnegative")
        key = (metric, row["period"])
        if key in seen:
            raise ValueError("Duplicate metric/period; resolve vintage explicitly")
        seen.add(key)


def forecast(events, origin, share=0.45):
    """No truth argument. Replays ONLY the as-of snapshot, no smoother."""
    validate(events)
    if not 0 < share <= 1:
        raise ValueError("Supply share must be in (0, 1]")
    visible = [e for e in events if e["period"] <= origin and e["available_at"] <= origin]
    orders = sorted((e for e in visible if e["metric"] == "order_lc"), key=lambda e: e["period"])
    if len(orders) < 3 or [e["period"] for e in orders[-3:]] != list(range(origin - 2, origin + 1)):
        raise ValueError("Need three consecutive available LC order months")
    order_mean = mean(e["value"] for e in orders[-3:]) / share
    proxies = sorted((e for e in visible if e["metric"] == "production_proxy"), key=lambda e: e["period"])
    reports = sum(e["metric"] == "inventory_report" for e in visible)
    base = {"data_kind": "synthetic", "origin": origin, "target": origin + 1, "assumed_share": share,
            "order_3ma": order_mean, "proxy_count": len(proxies),
            "ignored_inventory_reports": reports,
            "max_used_available": max(e["available_at"] for e in orders),
            "direct": None, "with_state": None, "state_mean": None,
            "state_sd": None, "state_forecast_low": None, "state_forecast_high": None,
            "max_used_period": origin, "innovation_flags": 0}
    if not proxies or origin - proxies[-1]["period"] > 3:
        return dict(base, status="NOT_IDENTIFIED", warning="No recent proxy; order policy/share insufficient")
    direct = 0.5 * order_mean + 0.5 * mean(e["value"] * ASSUMPTIONS["kg_per_unit"] / 1000 for e in proxies[-3:])
    by_period = defaultdict(list)
    for e in orders + proxies:
        by_period[e["period"]].append(e)
    state, variance = ASSUMPTIONS["prior_mean_t"], ASSUMPTIONS["prior_variance"]
    flags = 0
    for t in range(origin + 1):
        if t:
            variance += ASSUMPTIONS["process_variance"]
        for e in by_period[t]:
            if e["metric"] == "order_lc":
                y, noise = e["value"] / share, ASSUMPTIONS["order_noise_sd_t"] ** 2
            else:
                y = e["value"] * ASSUMPTIONS["kg_per_unit"] / 1000
                noise = ASSUMPTIONS["proxy_noise_sd_t"] ** 2
            gain = variance / (variance + noise)
            if abs(y - state) > 2.5 * math.sqrt(variance + noise):
                flags += 1
            state += gain * (y - state)
            variance *= 1 - gain
    sd_next = math.sqrt(variance + ASSUMPTIONS["process_variance"])
    # ponytail: fixed fusion weights, no tuning on hidden C; validate before deployment.
    return dict(base, direct=direct, with_state=0.5 * direct + 0.5 * state,
                state_mean=state, state_sd=math.sqrt(variance),
                state_forecast_low=state - 1.96 * sd_next,
                state_forecast_high=state + 1.96 * sd_next,
                max_used_available=max(e["available_at"] for e in orders + proxies),
                innovation_flags=flags,
                status="CONDITIONAL", warning="Share/BOM/policy assumed; inventory without total receipts ignored")


def evaluate(events, truth, seed, scenario, share):
    # Truth is only joined AFTER forecast() returns; no hidden target fitting.
    rows = []
    for origin in ASSUMPTIONS["eval_origins"]:
        result = forecast(events, origin, share)
        actual = truth[origin + 1]["C"]
        for model in ("order_3ma", "direct", "with_state"):
            prediction = result[model]
            if prediction is None:
                continue
            rows.append({"data_kind": "synthetic", "scenario": scenario, "seed": seed, "share": share,
                         "origin": origin, "target": origin + 1, "model": model,
                         "prediction": prediction, "actual_C": actual,
                         "error": prediction - actual,
                         "state_error_current": (result["state_mean"] - truth[origin]["C"]) if result["state_mean"] is not None else None,
                         "state_forecast_low": result["state_forecast_low"],
                         "state_forecast_high": result["state_forecast_high"],
                         "max_used_available": result["max_used_available"],
                         "max_used_period": result["max_used_period"],
                         "status": result["status"]})
    return rows


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["scenario"], row["share"], row["model"])].append(row)
    metrics = []
    for (scenario, share, model), group in sorted(groups.items()):
        errors = [r["error"] for r in group]
        seed_maes = [mean(abs(r["error"]) for r in group if r["seed"] == s) for s in sorted({r["seed"] for r in group})]
        metrics.append({"data_kind": "synthetic", "scenario": scenario, "share": share, "model": model,
                        "n": len(group), "MAE_t": mean(abs(e) for e in errors),
                        "bias_t": mean(errors), "seed_MAE_min": min(seed_maes),
                        "seed_MAE_max": max(seed_maes)})
    return metrics


def run(out, seeds):
    if seeds < 1:
        raise ValueError("seeds must be positive")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for scenario in ("base", "proxy_contaminated"):
        for seed in range(seeds):
            events, truth = generate(seed, scenario != "base")
            validate(events)
            for share in ASSUMPTIONS["shares"]:
                rows.extend(evaluate(events, truth, seed, scenario, share))
            if seed == 0:
                write_csv(out / f"{scenario}_observations.csv", events)
                write_csv(out / f"{scenario}_truth_EVALUATION_ONLY.csv", truth)
    metrics = summarize(rows)
    write_csv(out / "predictions.csv", rows)
    write_csv(out / "metrics.csv", metrics)
    (out / "assumptions.json").write_text(json.dumps(dict(ASSUMPTIONS, seeds=seeds), indent=2) + "\n", encoding="utf-8")
    report = ["# Synthetic-only FCST experiment", "", "No real customer performance evidence. Fixed parameters; no fitting to hidden C.",
              "48 months/seed; target months 36..47 (0-based), 12 one-month forecasts/seed.",
              "Bias = prediction - actual C. All amounts/MAE/bias in tonnes.", "",
              "| scenario | assumed share | method | n | MAE | bias | seed MAE min..max |",
              "|---|---:|---|---:|---:|---:|---|"]
    for m in metrics:
        report.append(f"| {m['scenario']} | {m['share']:.2f} | {m['model']} | {m['n']} | {m['MAE_t']:.3f} | {m['bias_t']:.3f} | {m['seed_MAE_min']:.3f}..{m['seed_MAE_max']:.3f} |")
    report += ["", "## Added-state value (MAE_with_state - MAE_direct; positive is worse)"]
    for scenario in ("base", "proxy_contaminated"):
        g = {m["model"]: m for m in metrics if m["scenario"] == scenario and m["share"] == 0.45}
        report.append(f"- {scenario}: {g['with_state']['MAE_t'] - g['direct']['MAE_t']:+.3f} tonnes.")
    current = [r for r in rows if r["share"] == 0.45 and r["model"] == "with_state"]
    report += ["", "## State estimation and conditional interval diagnostics"]
    for scenario in ("base", "proxy_contaminated"):
        group = [r for r in current if r["scenario"] == scenario]
        coverage = mean(r["state_forecast_low"] <= r["actual_C"] <= r["state_forecast_high"] for r in group)
        report.append(f"- {scenario}: current-C estimation MAE={mean(abs(r['state_error_current']) for r in group):.3f} t; state-only next-C nominal 95% Gaussian interval coverage={coverage:.1%}.")
    worst = max(current, key=lambda r: abs(r["error"]))
    report += ["", "## Failure and uncertainty report",
               f"- Worst with_state case at assumed share .45: scenario={worst['scenario']}, seed={worst['seed']}, origin={worst['origin']}, error={worst['error']:+.3f} t.",
               "- Proxy contaminated: all production proxy reports for period >=30 are biased upward by 50%.",
               "- Conditional intervals exclude supply-share uncertainty, systematic proxy bias and model misspecification; they are NOT calibrated guarantees or intervals for the fused forecast.",
               "- Order-only/no recent proxy: NOT_IDENTIFIED; no state estimate/interval is fabricated. The order baseline is still an assumed-share scenario.",
               "- Inventory reports arrive two months late without total receipts: ignored as consumption measurements. LC shipments are not total customer receipts.",
               "- Same observations feed direct/with_state. Any gain is a structural-prior effect, not new information or proof that Kalman dominates.",
               "- LC order scenario only: share * fused C forecast, steady inventory, no pipeline adjustment, no order-timing forecast; not scored against actual LC orders.",
               "", "## Rule-based review request (not an LLM or autonomous agent)",
               "- Confirm customer attribution, all-supplier share and BOM; verify report availability and explain proxy contamination before acting.",
               "- Check uncertainty, negative state bounds and sensitivity .30/.45/.60; do not auto-order or auto-schedule production."]
    (out / "RESULTS.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    # Reviewable final snapshot and separate LC order scenarios, without truth.
    events, _ = generate(0)
    scenarios = []
    for share in ASSUMPTIONS["shares"]:
        snapshot = forecast(events, 47, share)
        snapshot["lc_order_scenario_t"] = share * snapshot["with_state"]
        scenarios.append(snapshot)
    write_csv(out / "latest_scenarios.csv", scenarios)
    abstention = forecast([e for e in events if e["metric"] != "production_proxy"], 47)
    (out / "order_only_status.json").write_text(json.dumps(abstention, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"seeds": seeds, "prediction_rows": len(rows), "report": str(out / "RESULTS.md")}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--seeds", type=int, default=20)
    args = parser.parse_args()
    run(args.out, args.seeds)

# Synthetic-only FCST experiment

No real customer performance evidence. Fixed parameters; no fitting to hidden C.
48 months/seed; target months 36..47 (0-based), 12 one-month forecasts/seed.
Bias = prediction - actual C. All amounts/MAE/bias in tonnes.

| scenario | assumed share | method | n | MAE | bias | seed MAE min..max |
|---|---:|---|---:|---:|---:|---|
| base | 0.30 | direct | 240 | 48.652 | 31.631 | 45.738..51.277 |
| base | 0.30 | order_3ma | 240 | 86.161 | 65.011 | 81.834..89.615 |
| base | 0.30 | with_state | 240 | 33.684 | 18.227 | 30.983..35.830 |
| base | 0.45 | direct | 240 | 32.495 | -1.032 | 29.439..37.842 |
| base | 0.45 | order_3ma | 240 | 49.872 | -0.314 | 44.016..52.373 |
| base | 0.45 | with_state | 240 | 28.282 | -1.584 | 24.490..33.871 |
| base | 0.60 | direct | 240 | 32.406 | -17.363 | 27.148..36.784 |
| base | 0.60 | order_3ma | 240 | 48.024 | -32.977 | 44.041..51.419 |
| base | 0.60 | with_state | 240 | 27.892 | -11.490 | 23.624..34.042 |
| proxy_contaminated | 0.30 | direct | 240 | 68.411 | 63.934 | 65.235..74.395 |
| proxy_contaminated | 0.30 | order_3ma | 240 | 86.161 | 65.011 | 81.834..89.615 |
| proxy_contaminated | 0.30 | with_state | 240 | 65.199 | 62.664 | 61.408..72.459 |
| proxy_contaminated | 0.45 | direct | 240 | 42.127 | 31.272 | 39.694..45.214 |
| proxy_contaminated | 0.45 | order_3ma | 240 | 49.872 | -0.314 | 44.016..52.373 |
| proxy_contaminated | 0.45 | with_state | 240 | 47.447 | 42.852 | 43.326..54.364 |
| proxy_contaminated | 0.60 | direct | 240 | 32.770 | 14.941 | 29.288..37.773 |
| proxy_contaminated | 0.60 | order_3ma | 240 | 48.024 | -32.977 | 44.041..51.419 |
| proxy_contaminated | 0.60 | with_state | 240 | 39.440 | 32.947 | 36.099..45.316 |

## Added-state value (MAE_with_state - MAE_direct; positive is worse)
- base: -4.213 tonnes.
- proxy_contaminated: +5.320 tonnes.

## State estimation and conditional interval diagnostics
- base: current-C estimation MAE=19.047 t; state-only next-C nominal 95% Gaussian interval coverage=45.0%.
- proxy_contaminated: current-C estimation MAE=55.337 t; state-only next-C nominal 95% Gaussian interval coverage=21.7%.

## Failure and uncertainty report
- Worst with_state case at assumed share .45: scenario=proxy_contaminated, seed=3, origin=42, error=+133.933 t.
- Proxy contaminated: all production proxy reports for period >=30 are biased upward by 50%.
- Conditional intervals exclude supply-share uncertainty, systematic proxy bias and model misspecification; they are NOT calibrated guarantees or intervals for the fused forecast.
- Order-only/no recent proxy: NOT_IDENTIFIED; no state estimate/interval is fabricated. The order baseline is still an assumed-share scenario.
- Inventory reports arrive two months late without total receipts: ignored as consumption measurements. LC shipments are not total customer receipts.
- Same observations feed direct/with_state. Any gain is a structural-prior effect, not new information or proof that Kalman dominates.
- LC order scenario only: share * fused C forecast, steady inventory, no pipeline adjustment, no order-timing forecast; not scored against actual LC orders.

## Rule-based review request (not an LLM or autonomous agent)
- Confirm customer attribution, all-supplier share and BOM; verify report availability and explain proxy contamination before acting.
- Check uncertainty, negative state bounds and sensitivity .30/.45/.60; do not auto-order or auto-schedule production.

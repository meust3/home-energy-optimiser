"""Read-only historical EV candidate report; never annotates observations."""

import argparse
import json
from datetime import UTC, datetime, timedelta

from energy_optimizer.ev_annotation import parse_aware_timestamp
from energy_optimizer.historical_ev import (
    HistoricalEVCandidateConfig,
    detect_historical_ev_candidates,
)
from energy_optimizer.persistence import configured_repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--before", type=parse_aware_timestamp)
    parser.add_argument("--after", type=parse_aware_timestamp)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--minimum-house-load-w", type=float, default=5000)
    parser.add_argument("--minimum-duration-minutes", type=int, default=60)
    parser.add_argument("--maximum-internal-gap-minutes", type=int, default=10)
    parser.add_argument("--minimum-session-energy-kwh", type=float, default=5)
    parser.add_argument("--plateau-variability-threshold", type=float, default=0.15)
    args = parser.parse_args()
    if args.days <= 0 or (args.after and args.before and args.after >= args.before):
        parser.error("days/range must describe a positive interval")
    end = args.before or datetime.now(UTC)
    start = args.after or end - timedelta(days=args.days)
    columns = (
        "slot_utc",
        "telemetry_is_healthy",
        "baseline_training_eligible",
        "baseline_house_consumption_w",
        "grid_power_w",
        "battery_power_w",
        "pv_power_w",
        "ev_source",
        "ev_charging_active",
        "ev_detection_confidence",
        "ev_telemetry_fresh",
        "baseline_exclusion_reason",
    )
    with configured_repository() as repository:
        rows = repository.observation_rows(start=start, end=end, columns=columns)
    candidates = detect_historical_ev_candidates(
        rows,
        config=HistoricalEVCandidateConfig(
            minimum_house_load_w=args.minimum_house_load_w,
            minimum_duration_minutes=args.minimum_duration_minutes,
            maximum_internal_gap_minutes=args.maximum_internal_gap_minutes,
            minimum_session_energy_kwh=args.minimum_session_energy_kwh,
            plateau_variability_threshold=args.plateau_variability_threshold,
        ),
    )
    payload = [item.model_dump(mode="json") for item in candidates]
    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.markdown:
        print("| Candidate | Start UTC | End UTC | Minutes | kWh | Median W | Score |")
        print("|---|---|---|---:|---:|---:|---:|")
        for item in candidates:
            print(
                f"| {item.candidate_id} | {item.start_utc.isoformat()} | "
                f"{item.end_utc.isoformat()} | {item.duration_minutes:g} | "
                f"{item.estimated_energy_kwh:.2f} | {item.median_house_power_w:.0f} | "
                f"{item.candidate_score} |"
            )
    else:
        print(f"historical EV candidates: {len(candidates)} (read-only, unreviewed)")
        for item in candidates:
            print(
                item.candidate_id,
                item.start_utc.isoformat(),
                item.end_utc.isoformat(),
                f"{item.estimated_energy_kwh:.2f} kWh",
                f"score={item.candidate_score}",
            )
        print(
            "No observation was labelled or excluded. This tool has no apply mode; "
            "use the audited annotation workflow after review."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

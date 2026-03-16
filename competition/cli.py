#!/usr/bin/env python3
"""
Competition CLI — Manage the model competition from the command line.

Usage:
    python -m competition.cli status
    python -m competition.cli enroll-baseline [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
    python -m competition.cli backfill-actuals
    python -m competition.cli leaderboard [--window 30]
    python -m competition.cli run-daily [--forecast-path PATH]
    python -m competition.cli train <challenger_id>
    python -m competition.cli predict <challenger_id> [--dates YYYY-MM-DD,...]
    python -m competition.cli create-challenger <id> --name "Name" --description "Desc" [--params '{"max_depth": 8}']
    python -m competition.cli list-challengers [--all]
    python -m competition.cli blend-analysis [--window 30]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def cmd_status(args):
    """Show competition status."""
    from .ledger import ledger_stats
    from .baseline import get_baseline_status
    from .challenger import discover_challengers

    stats = ledger_stats()
    baseline = get_baseline_status()
    challengers = discover_challengers(status_filter=None)

    print("\n🏆 BAM-BAM MODEL COMPETITION STATUS")
    print("=" * 50)

    print(f"\n📊 Ledger: {stats['total_rows']:,} total predictions")
    if stats['total_rows'] > 0:
        print(f"   Date range: {stats['date_range']['start']} → {stats['date_range']['end']}")
        print(f"   Entities: {stats['entities']}")
        print(f"   With actuals: {stats['rows_with_actuals']:,}")
        print(f"   Pending actuals: {stats['rows_without_actuals']:,}")

    print(f"\n🏠 Baseline: {'✅ Registered' if baseline['registered'] else '❌ Not registered'}")
    if baseline.get('ledger_rows', 0) > 0:
        print(f"   Ledger rows: {baseline['ledger_rows']:,}")
        print(f"   Date range: {baseline['date_range']['start']} → {baseline['date_range']['end']}")
        print(f"   Entities: {baseline['entities']}")

    print(f"\n⚔️  Challengers: {len(challengers)} registered")
    for c in challengers:
        status_icon = "🟢" if c.status == "active" else "🔴"
        print(f"   {status_icon} {c.id} — {c.name} [{c.status}]")

    print()


def cmd_enroll_baseline(args):
    """Enroll baseline predictions from archives."""
    from .baseline import enroll_baseline_from_archives

    n = enroll_baseline_from_archives(
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(f"\n✅ Enrolled {n:,} baseline predictions")


def cmd_backfill_actuals(args):
    """Backfill actual wait times."""
    from .baseline import backfill_baseline_actuals

    n = backfill_baseline_actuals()
    print(f"\n✅ Backfilled {n:,} actual values")


def cmd_leaderboard(args):
    """Show current leaderboard."""
    from .evaluation import generate_leaderboard

    lb = generate_leaderboard(window_days=args.window)

    print(f"\n🏆 LEADERBOARD (rolling {args.window}-day window)")
    print(f"   Evaluation date: {lb['evaluation_date']}")
    print("=" * 70)

    if lb["overall_rankings"]:
        print(f"\n{'Rank':<5} {'Challenger':<25} {'MAE':<8} {'Bias Coverage':<15} {'Entities':<8}")
        print("-" * 70)
        for r in lb["overall_rankings"]:
            print(
                f"  {r['overall_rank']:<3} {r['challenger_id']:<25} "
                f"{r['mean_mae']:<8.2f} {r['entity_coverage']:>5.1f}%       "
                f"{r['n_entities']:<8}"
            )
    else:
        print("\n   No rankings available yet (need actuals to score)")

    if lb["blend_opportunities"]:
        print(f"\n🔀 Blend Opportunities:")
        for b in lb["blend_opportunities"]:
            print(
                f"   {b['challenger_1']} + {b['challenger_2']} "
                f"(r={b['error_correlation']:.3f}, potential={b['blend_potential']})"
            )

    print()


def cmd_run_daily(args):
    """Run daily competition cycle."""
    from .orchestrator import run_daily_competition

    forecast_path = Path(args.forecast_path) if args.forecast_path else None
    summary = run_daily_competition(
        forecast_path=forecast_path,
        skip_blends=args.skip_blends,
    )

    print(f"\n✅ Daily competition completed in {summary['elapsed_seconds']}s")
    if summary["errors"]:
        print(f"⚠️  {len(summary['errors'])} errors:")
        for e in summary["errors"]:
            print(f"   - {e}")


def cmd_train(args):
    """Train a specific challenger."""
    from .challenger import train_challenger

    result = train_challenger(args.challenger_id)
    print(f"\n{'✅' if result['status'] == 'success' else '❌'} Training: {result}")


def cmd_predict(args):
    """Run predictions for a specific challenger."""
    from .challenger import run_challenger_predictions

    dates = args.dates.split(",") if args.dates else None
    predictions = run_challenger_predictions(args.challenger_id, prediction_dates=dates)
    print(f"\n✅ Generated {len(predictions)} predictions")


def cmd_create_challenger(args):
    """Create a new challenger from template."""
    from .challenger import create_challenger_from_template

    params = json.loads(args.params) if args.params else None
    path = create_challenger_from_template(
        challenger_id=args.challenger_id,
        name=args.name,
        description=args.description,
        xgb_params=params,
        approach=args.approach,
        notes=args.notes,
    )
    print(f"\n✅ Created challenger at {path}")


def cmd_list_challengers(args):
    """List all challengers."""
    from .challenger import discover_challengers

    status = None if args.all else "active"
    challengers = discover_challengers(status_filter=status)

    print(f"\n⚔️  {'All' if args.all else 'Active'} Challengers:")
    print("-" * 60)
    for c in challengers:
        icon = "🟢" if c.status == "active" else "🔴"
        print(f"  {icon} {c.id}")
        print(f"     Name: {c.name}")
        print(f"     Approach: {c.approach} | Category: {c.category}")
        print(f"     Status: {c.status} | Created: {c.created}")
        if c.notes:
            print(f"     Notes: {c.notes}")
        print()


def cmd_blend_analysis(args):
    """Run blend analysis."""
    from .evaluation import find_blend_opportunities

    results = find_blend_opportunities(window_days=args.window)
    if results.empty:
        print("\n   No blend analysis possible (need 2+ challengers with actuals)")
        return

    # Show top improvements
    top = results.nlargest(20, "improvement_pct")
    print(f"\n🔀 Top Blend Opportunities (window={args.window}d)")
    print("-" * 80)
    for _, row in top.iterrows():
        print(
            f"  {row['entity_code']:>6} | "
            f"{row['challenger_1']} ({row['weight_1']:.0%}) + "
            f"{row['challenger_2']} ({row['weight_2']:.0%}) → "
            f"MAE {row['blended_mae']:.1f} (was {row['best_individual_mae']:.1f}, "
            f"{row['improvement_pct']:+.1f}%)"
        )
    print()


def main():
    parser = argparse.ArgumentParser(
        description="🏆 Bam-Bam Model Competition Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # status
    subparsers.add_parser("status", help="Show competition status")

    # enroll-baseline
    p = subparsers.add_parser("enroll-baseline", help="Enroll baseline predictions")
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)

    # backfill-actuals
    subparsers.add_parser("backfill-actuals", help="Backfill actual wait times")

    # leaderboard
    p = subparsers.add_parser("leaderboard", help="Show leaderboard")
    p.add_argument("--window", type=int, default=30)

    # run-daily
    p = subparsers.add_parser("run-daily", help="Run daily competition cycle")
    p.add_argument("--forecast-path", default=None)
    p.add_argument("--skip-blends", action="store_true")

    # train
    p = subparsers.add_parser("train", help="Train a challenger")
    p.add_argument("challenger_id")

    # predict
    p = subparsers.add_parser("predict", help="Run challenger predictions")
    p.add_argument("challenger_id")
    p.add_argument("--dates", default=None)

    # create-challenger
    p = subparsers.add_parser("create-challenger", help="Create new challenger")
    p.add_argument("challenger_id")
    p.add_argument("--name", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--params", default=None, help="JSON XGBoost params")
    p.add_argument("--approach", default="hyperparameter_variant")
    p.add_argument("--notes", default="")

    # list-challengers
    p = subparsers.add_parser("list-challengers", help="List challengers")
    p.add_argument("--all", action="store_true")

    # blend-analysis
    p = subparsers.add_parser("blend-analysis", help="Run blend analysis")
    p.add_argument("--window", type=int, default=30)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    commands = {
        "status": cmd_status,
        "enroll-baseline": cmd_enroll_baseline,
        "backfill-actuals": cmd_backfill_actuals,
        "leaderboard": cmd_leaderboard,
        "run-daily": cmd_run_daily,
        "train": cmd_train,
        "predict": cmd_predict,
        "create-challenger": cmd_create_challenger,
        "list-challengers": cmd_list_challengers,
        "blend-analysis": cmd_blend_analysis,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()

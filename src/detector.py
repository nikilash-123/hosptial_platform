"""
detector.py
===========
CLI entry point for the Hospital Appointment Query Regression Detector.

Commands:
  python src/detector.py baseline --release v1.0
  python src/detector.py run      --release v1.1
  python src/detector.py analyse  --baseline v1.0 --run v1.1
  python src/detector.py report
  python src/detector.py history
"""

import argparse
import json
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import rules_loader, plan_extractor, timing_runner, stats_collector
from src.core import snapshot_store, regression_analyser, baseline_engine

HOSPITAL_DB  = os.path.join(BASE_DIR, "data", "hospital.db")
DETECTOR_DB  = os.path.join(BASE_DIR, "data", "detector_store.db")
QUERIES_YAML = os.path.join(BASE_DIR, "config", "probe_queries.yaml")
RULES_YAML   = os.path.join(BASE_DIR, "config", "rules.yaml")

import yaml


def load_probe_queries():
    with open(QUERIES_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["queries"]


def cmd_baseline(args):
    if getattr(args, "from_dataset", False):
        print(f"\n[DETECTOR] Generating multi-dimensional baseline from synthetic dataset for {args.release}...")
        baselines = baseline_engine.generate_baseline(source="dataset", baseline_tag=args.release, store_path=DETECTOR_DB)
        print(f"[DETECTOR] Created {len(baselines)} query baseline fingerprints.")
        for qid, b in sorted(baselines.items()):
            print(f"  >> {qid:12s} median={b['median_exec_ms']:.2f}ms  p95={b['p95_exec_ms']:.2f}ms  plan_hash={b['plan_hash']}  indexes={b['indexes']}")
        print(f"[DETECTOR] Baseline {args.release} registered and active.\n")
    else:
        _capture_snapshot(args.release, "BASELINE", args.runs)
        baseline_engine.generate_baseline(source="live", baseline_tag=args.release, store_path=DETECTOR_DB, runs=args.runs)


def cmd_baselines(args):
    baseline_engine.init_baseline_store(DETECTOR_DB)
    baselines = baseline_engine.get_baseline(store_path=DETECTOR_DB)
    if not baselines:
        print("\n[DETECTOR] No active query baselines found. Run 'detector.py baseline --release v1.0'\n")
        return
    print(f"\n-- Active Query Baselines ({len(baselines)}) ----------------------------------------")
    for qid, b in sorted(baselines.items()):
        print(f"  {qid:12s} | p50={b['median_exec_ms']:6.2f}ms | p95={b['p95_exec_ms']:6.2f}ms | rows={b['rows_examined']:4d} | plan={b['plan_hash']} | indexes={b['indexes']}")
    print()


def cmd_run(args):
    _capture_snapshot(args.release, "RUN", args.runs)


def _capture_snapshot(release_tag: str, snap_type: str, runs: int):
    print(f"\n[DETECTOR] Capturing {snap_type} snapshot for release: {release_tag}")
    print(f"[DETECTOR] Hospital DB : {HOSPITAL_DB}")

    if not os.path.exists(HOSPITAL_DB):
        print(f"[ERROR] hospital.db not found. Run: python src/synthetic_data_generator.py")
        sys.exit(1)

    snapshot_store.init_store(DETECTOR_DB)
    rules = rules_loader.load_rules(RULES_YAML)
    queries = load_probe_queries()

    app_conn = sqlite3.connect(HOSPITAL_DB)
    app_conn.row_factory = sqlite3.Row

    # Collect DB-level stats
    stats = stats_collector.collect_stats(app_conn, HOSPITAL_DB)
    row_counts = {t: v["row_count"] for t, v in stats["tables"].items()}

    snap_id = snapshot_store.save_snapshot(
        release_tag=release_tag,
        snapshot_type=snap_type,
        db_size_bytes=stats["db_size_bytes"],
        row_counts=row_counts,
        store_path=DETECTOR_DB,
    )
    print(f"[DETECTOR] Snapshot ID: {snap_id}")

    for q in queries:
        qid   = q["id"]
        label = q["label"]
        sql   = q["sql"].strip()

        print(f"  >> {qid}: {label[:60]}...")

        plan    = plan_extractor.extract_plan(app_conn, sql)
        timing  = timing_runner.run_timed(app_conn, sql, runs=runs)
        tbl_stats = {
            "indexes": stats["indexes"],
            "sqlite_stat1": stats["sqlite_stat1"],
        }

        snapshot_store.save_query_execution(
            snapshot_id=snap_id,
            query_id=qid,
            query_label=label,
            sql_text=sql,
            plan=plan,
            timing=timing,
            stats=tbl_stats,
            store_path=DETECTOR_DB,
        )

        uses = "INDEX" if plan["uses_index"] else "FULL-SCAN"
        print(f"     p95={timing['p95_ms']:.2f}ms  access={uses}  indexes={plan['index_names']}")

    # Record release in history
    snapshot_store.record_release(
        release_tag=release_tag,
        description=f"{snap_type} snapshot captured",
        changes=[f"{snap_type} captured at {release_tag}"],
        store_path=DETECTOR_DB,
    )

    app_conn.close()
    print(f"\n[DETECTOR] {snap_type} snapshot complete. {len(queries)} queries captured.\n")


def cmd_analyse(args):
    baseline_tag = args.baseline
    run_tag      = args.run

    print(f"\n[DETECTOR] Analysing: baseline={baseline_tag}  vs  run={run_tag}")

    snapshot_store.init_store(DETECTOR_DB)
    rules = rules_loader.load_rules(RULES_YAML)

    baseline_snap = snapshot_store.get_snapshot_by_tag(baseline_tag, "BASELINE", DETECTOR_DB)
    run_snap      = snapshot_store.get_snapshot_by_tag(run_tag, "RUN", DETECTOR_DB)

    if not baseline_snap:
        print(f"[ERROR] No BASELINE snapshot found for release: {baseline_tag}")
        sys.exit(1)
    if not run_snap:
        print(f"[ERROR] No RUN snapshot found for release: {run_tag}")
        sys.exit(1)

    baseline_execs = snapshot_store.get_executions_for_snapshot(baseline_snap["snapshot_id"], DETECTOR_DB)
    run_execs      = snapshot_store.get_executions_for_snapshot(run_snap["snapshot_id"], DETECTOR_DB)

    findings = regression_analyser.analyse(
        baseline_execs, run_execs, baseline_snap, run_snap, rules
    )

    # Persist regressions
    saved = 0
    for f in findings:
        if f["severity"] != "OK" or f.get("regression_types"):
            snapshot_store.save_regression(
                baseline_snap_id=baseline_snap["snapshot_id"],
                run_snap_id=run_snap["snapshot_id"],
                query_id=f["query_id"],
                query_label=f.get("query_label", f["query_id"]),
                severity=f["severity"],
                regression_types=f.get("regression_types", []),
                delta_ms_p95=f.get("delta_ms_p95", 0),
                pct_change=f.get("pct_change", 0),
                plan_changed=f.get("plan_changed", False),
                index_lost=f.get("index_lost", False),
                has_new_scan=f.get("has_new_scan", False),
                evidence=f.get("evidence", {}),
                store_path=DETECTOR_DB,
            )
            saved += 1

    # Print report
    print(f"\n{'='*70}")
    print(f"  REGRESSION ANALYSIS REPORT")
    print(f"  Baseline: {baseline_tag}  ->  Run: {run_tag}")
    print(f"{'='*70}")

    SEVERITY_ICON = {
        "CRITICAL": "[CRITICAL]",
        "HIGH":     "[HIGH]    ",
        "MEDIUM":   "[MEDIUM]  ",
        "LOW":      "[LOW]     ",
        "OK":       "[OK]      ",
    }

    for f in findings:
        icon = SEVERITY_ICON.get(f["severity"], f["severity"])
        types = ",".join(f.get("regression_types", ["-"]))
        print(
            f"  {icon}  {f['query_id']:8s}  dp95={f['delta_ms_p95']:+8.2f}ms "
            f"({f['pct_change']:+.1f}%)  types=[{types}]"
        )
        if f["severity"] in ("CRITICAL", "HIGH") and f.get("plan_diff_summary"):
            print(f"           -> {f['plan_diff_summary']}")

    non_ok = [f for f in findings if f["severity"] != "OK"]
    print(f"\n  Total findings: {len(findings)}  |  Regressions: {len(non_ok)}  |  Saved: {saved}")
    print(f"{'='*70}\n")

    if any(f["severity"] == "CRITICAL" for f in findings):
        print("[DETECTOR] *** CRITICAL regressions found - recommend BLOCKING this release.\n")
        return 2
    elif any(f["severity"] == "HIGH" for f in findings):
        print("[DETECTOR] ^^^ HIGH regressions found - review before deploying.\n")
        return 1
    else:
        print("[DETECTOR] *** No blocking regressions detected.\n")
        return 0


def cmd_history(args):
    snapshot_store.init_store(DETECTOR_DB)
    snapshots = snapshot_store.get_all_snapshots(DETECTOR_DB)
    releases  = snapshot_store.get_release_history(DETECTOR_DB)

    print("\n-- Release History -------------------------------------------")
    for r in releases:
        print(f"  {r['release_tag']:10s}  {r['released_at'][:19]}  {r['description']}")

    print("\n-- Snapshots --------------------------------------------------")
    for s in snapshots:
        rc = json.loads(s.get('row_counts') or '{}')
        appts = rc.get('appointments', '?')
        print(
            f"  #{s['snapshot_id']:3d}  {s['release_tag']:10s}  {s['snapshot_type']:8s}"
            f"  {s['captured_at'][:19]}  appts={appts}"
        )
    print()


def cmd_report(args):
    snapshot_store.init_store(DETECTOR_DB)
    regressions = snapshot_store.get_regressions(store_path=DETECTOR_DB)

    ICONS = {"CRITICAL": "[C]", "HIGH": "[H]", "MEDIUM": "[M]", "LOW": "[L]", "OK": "[OK]"}

    print(f"\n-- All Regression Findings ({len(regressions)}) ------------------")
    for r in regressions:
        icon = ICONS.get(r["severity"], "?")
        types = r.get("regression_types", "[]")
        if isinstance(types, str):
            types = json.loads(types)
        fp_note = " [FP]" if r.get("is_false_pos") else ""
        fn_note = " [FN]" if r.get("is_false_neg") else ""
        print(
            f"  {icon} #{r['regression_id']:3d}  {r['query_id']:8s}  {r['severity']:8s}"
            f"  Δp95={r['delta_ms_p95']:+8.2f}ms  types={types}{fp_note}{fn_note}"
        )
    print()


def cmd_evaluate(args):
    from src.core import evaluation_engine
    print("\n[DETECTOR] Running Phase 10 Systematic Benchmark Evaluation...")
    evaluations = evaluation_engine.run_full_evaluation()
    cm = evaluation_engine.compute_confusion_matrix(evaluations)
    impact = evaluation_engine.compute_detection_before_impact_metrics(evaluations)
    legacy = evaluation_engine.evaluate_legacy_baseline(evaluations)
    evidence_audit = evaluation_engine.audit_high_priority_evidence(evaluations)

    if getattr(args, "export", True):
        paths = evaluation_engine.export_evaluation_data(evaluations)
        print("[DETECTOR] Exported evaluation artifacts:")
        for k, p in paths.items():
            print(f"  - {k:18s}: {p}")

    print("\n-- Phase 10 Evaluation Summary -------------------------------------")
    print(f"  Total Records:      {cm['total_records']}")
    print(f"  TP: {cm['true_positives']} | FP: {cm['false_positives']} | TN: {cm['true_negatives']} | FN: {cm['false_negatives']}")
    print(f"  Precision:          {cm['precision_pct']:.1f}%")
    print(f"  Recall:             {cm['recall_pct']:.1f}%")
    print(f"  F1-Score:           {cm['f1_pct']:.1f}%")
    print(f"  Core Success Metric (Detected Before User Impact):")
    print(f"    - Baseline:       {legacy['legacy_detection_before_impact_rate_pct']:.1f}%")
    print(f"    - Target:         {impact['project_target_pct']:.1f}%")
    print(f"    - Measured:       {impact['detection_before_user_impact_rate_pct']:.1f}% (Target Met: {impact['target_met']})")
    print(f"    - Avg Lead Time:  {impact['lead_time_minutes']['average']} min ({impact['lead_time_seconds']['average']:.0f} sec)")
    print(f"  Evidence Audit:     {evidence_audit['high_priority_evidence_completeness_rate_pct']:.1f}% completeness")
    print("--------------------------------------------------------------------\n")


def main():
    parser = argparse.ArgumentParser(
        description="Hospital Appointment Query Regression Detector"
    )
    sub = parser.add_subparsers(dest="command")

    p_baseline = sub.add_parser("baseline", help="Capture a baseline snapshot")
    p_baseline.add_argument("--release", required=True, help="Release tag (e.g. v1.0)")
    p_baseline.add_argument("--runs", type=int, default=10, help="Timing runs per query")
    p_baseline.add_argument("--from-dataset", action="store_true", help="Build baseline from reproducible synthetic dataset")

    sub.add_parser("baselines", help="Display all active multi-dimensional query baselines")

    p_run = sub.add_parser("run", help="Capture a post-change run snapshot")
    p_run.add_argument("--release", required=True)
    p_run.add_argument("--runs", type=int, default=10)

    p_analyse = sub.add_parser("analyse", help="Compare baseline vs run")
    p_analyse.add_argument("--baseline", required=True, help="Baseline release tag")
    p_analyse.add_argument("--run", required=True, help="Run release tag")

    sub.add_parser("report", help="Show all regression findings")
    sub.add_parser("history", help="Show snapshot and release history")

    p_eval = sub.add_parser("evaluate", help="Run systematic Phase 10 measurable benchmark evaluation")
    p_eval.add_argument("--export", action="store_true", default=True, help="Export CSV and JSON evaluation results")
    p_eval.add_argument("--no-export", dest="export", action="store_false")

    args = parser.parse_args()

    if args.command == "baseline":
        cmd_baseline(args)
    elif args.command == "baselines":
        cmd_baselines(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "analyse":
        rc = cmd_analyse(args)
        sys.exit(rc)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

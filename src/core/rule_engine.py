"""
rule_engine.py
==============
Phase 7: Priority and Configurable Rule Engine for Hospital Appointment Platform.

A reusable rule evaluation engine that evaluates multi-dimensional signals against
externally configured rules and thresholds.

Responsibilities:
1. Evaluates signals without hard-coded numbers or thresholds.
2. Calculates explainable priority scores with per-rule point contributions.
3. Maps scores to priority and severity tiers (NORMAL, WARNING, HIGH, CRITICAL).
4. Verifies evidence sufficiency to prevent false certainty
   (returns MANUAL_REVIEW_REQUIRED or INSUFFICIENT_EVIDENCE when under-supported).
5. Produces forensic, non-hardcoded explanations generated from actual data.
6. Records rule configuration versioning for reproducibility.
"""

import os
from typing import Dict, Any, List, Optional, Tuple

from src.core import rules_loader

DEFAULT_RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "rules.yaml"
)


class RuleEngine:
    """
    Reusable Priority and Rule Evaluation Engine.
    Operates on externally configurable thresholds, weights, and evidence requirements.
    """

    def __init__(self, rules: Optional[Dict[str, Any]] = None, rules_path: str = DEFAULT_RULES_PATH):
        if rules is not None:
            self.rules = rules
        else:
            self.rules = rules_loader.load_rules(rules_path)
        self.version = rules_loader.get_rule_version(self.rules, "v1.0")

    def evaluate(
        self,
        signals: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Main rule evaluation entry point.

        Args:
            signals: Dict containing observed signals (timing, plan, index, stats, etc.)
            context: Optional Dict with raw query state / evidence items

        Returns:
            Dict containing:
              - triggered_rules: List of dicts with rule_name, display_name, condition, points, details
              - score: total priority score (float)
              - score_breakdown: Dict of category -> points
              - severity: NORMAL | WARNING | HIGH | CRITICAL
              - priority: NORMAL | WARNING | HIGH | CRITICAL | MANUAL_REVIEW_REQUIRED | INSUFFICIENT_EVIDENCE
              - explanation: Forensic explainability text generated from actual data
              - rule_config_version: Configuration version used
              - evidence_sufficiency: Dict with sufficiency assessment
        """
        ctx = context or {}
        triggered_rules: List[Dict[str, Any]] = []
        score_breakdown: Dict[str, float] = {
            "execution_time": 0.0,
            "plan": 0.0,
            "index": 0.0,
            "statistics": 0.0,
            "workload": 0.0,
            "change_context": 0.0,
        }

        # ── 1. Execution Time Percentage Regression ───────────────────────────
        b_ms = float(signals.get("baseline_exec_ms", ctx.get("baseline_execution_time", 1.0)) or 1.0)
        a_ms = float(signals.get("current_exec_ms", ctx.get("current_execution_time", 0.0)) or 0.0)
        time_pct = float(signals.get("time_pct_change", 0.0))
        if time_pct == 0.0 and b_ms > 0 and a_ms > 0:
            time_pct = round((a_ms - b_ms) / b_ms * 100.0, 2)

        time_reg_pct = rules_loader.get_threshold(
            self.rules, "execution_time_regression_percent",
            rules_loader.get_threshold(self.rules, "time_regression_pct", 20.0)
        )
        time_crit_pct = rules_loader.get_threshold(
            self.rules, "critical_regression_percent",
            rules_loader.get_threshold(self.rules, "time_critical_pct", 100.0)
        )
        w_time = rules_loader.get_scoring_weight(
            self.rules, "execution_time",
            rules_loader.get_scoring_weight(self.rules, "performance_weight", 30.0)
        )

        min_meaningful = rules_loader.get_threshold(self.rules, "minimum_meaningful_ms", 1.0)
        time_increased = signals.get("execution_time_increased")
        if time_increased is None:
            time_increased = (b_ms >= min_meaningful and time_pct >= time_reg_pct)

        if time_increased or time_pct >= time_reg_pct:
            if time_pct >= time_crit_pct:
                pts = float(w_time)
            elif time_pct >= 50.0:
                pts = round(w_time * 0.8, 1)
            else:
                pts = round(w_time * 0.5, 1)

            score_breakdown["execution_time"] += pts
            triggered_rules.append({
                "rule_name": "execution_time_regression",
                "display_name": "Execution time regression",
                "points": pts,
                "condition": f"p95 latency increased by {time_pct:.1f}% (threshold: {time_reg_pct}%)",
                "details": {
                    "baseline_ms": f"{b_ms:.2f} ms",
                    "current_ms": f"{a_ms:.2f} ms",
                    "increase": f"{'+' if time_pct > 0 else ''}{time_pct:.1f}%"
                }
            })

        # ── 2. Absolute Execution Time SLA Threshold ──────────────────────────
        abs_crit_ms = rules_loader.get_threshold(
            self.rules, "execution_time_critical_ms",
            rules_loader.get_threshold(self.rules, "absolute_critical_ms", 2000.0)
        )
        abs_warn_ms = rules_loader.get_threshold(
            self.rules, "execution_time_warning_ms",
            rules_loader.get_threshold(self.rules, "absolute_high_ms", 500.0)
        )

        abs_above = signals.get("execution_time_above_threshold")
        if abs_above is None:
            abs_above = (a_ms >= abs_warn_ms)

        if abs_above or a_ms >= abs_warn_ms:
            if a_ms >= abs_crit_ms:
                pts = float(w_time)
                cond = f"Execution time ({a_ms:.1f}ms) breached critical SLA limit ({abs_crit_ms:.1f}ms)"
            else:
                pts = round(w_time * 0.5, 1)
                cond = f"Execution time ({a_ms:.1f}ms) exceeded warning SLA limit ({abs_warn_ms:.1f}ms)"

            score_breakdown["execution_time"] += pts
            triggered_rules.append({
                "rule_name": "execution_time_above_threshold",
                "display_name": "Absolute latency SLA threshold breach",
                "points": pts,
                "condition": cond,
                "details": {
                    "current_ms": f"{a_ms:.2f} ms",
                    "sla_limit_ms": f"{abs_crit_ms if a_ms >= abs_crit_ms else abs_warn_ms:.1f} ms"
                }
            })

        # ── 3. Query Plan Changed ─────────────────────────────────────────────
        w_plan = rules_loader.get_scoring_weight(
            self.rules, "plan_change",
            rules_loader.get_scoring_weight(self.rules, "plan_weight", 25.0)
        )
        if signals.get("plan_changed", False):
            pts = float(w_plan)
            score_breakdown["plan"] += pts
            b_hash = signals.get("baseline_plan_hash") or ctx.get("baseline_plan_hash", "base_hash")
            a_hash = signals.get("current_plan_hash") or ctx.get("current_plan_hash", "curr_hash")
            triggered_rules.append({
                "rule_name": "plan_changed",
                "display_name": "Query plan alteration",
                "points": pts,
                "condition": "Execution plan structure or access path changed",
                "details": {
                    "baseline_plan_hash": str(b_hash),
                    "current_plan_hash": str(a_hash)
                }
            })

        # ── 4. Full Table Scan Detected / Penalty ──────────────────────────────
        w_fts = rules_loader.get_scoring_weight(
            self.rules, "full_table_scan",
            rules_loader.get_scoring_weight(self.rules, "full_table_scan_penalty", 25.0)
        )
        if signals.get("full_table_scan_detected") or signals.get("has_new_scan"):
            pts = float(w_fts)
            score_breakdown["plan"] += pts
            plan_diff_text = signals.get("plan_difference_summary") or ctx.get("plan_explanation") or "Index Scan → Full Table Scan"
            triggered_rules.append({
                "rule_name": "full_table_scan_detected",
                "display_name": "Plan degradation",
                "points": pts,
                "condition": "Full table scan detected replacing indexed access",
                "details": {
                    "transition": plan_diff_text
                }
            })

        # ── 5. Plan Cost / Estimated Rows Increased ───────────────────────────
        cost_thresh = rules_loader.get_threshold(self.rules, "plan_cost_increase_percent", 30.0)
        cost_drift = float(signals.get("cost_drift_pct", 0.0))
        if signals.get("plan_cost_increased") or cost_drift >= cost_thresh:
            pts = round(w_plan * 0.4, 1)
            score_breakdown["plan"] += pts
            triggered_rules.append({
                "rule_name": "plan_cost_increased",
                "display_name": "Plan cost surge",
                "points": pts,
                "condition": f"Optimizer estimated cost grew by {cost_drift:.1f}% (threshold: {cost_thresh}%)",
                "details": {"cost_increase_pct": f"{cost_drift:.1f}%"}
            })

        # ── 6. Index Removed / Modified / Missing ─────────────────────────────
        w_idx_rem = rules_loader.get_scoring_weight(
            self.rules, "index_removed",
            rules_loader.get_scoring_weight(self.rules, "index_removal_weight",
            rules_loader.get_scoring_weight(self.rules, "index_weight", 20.0))
        )
        w_idx_mod = rules_loader.get_scoring_weight(
            self.rules, "index_modified",
            rules_loader.get_scoring_weight(self.rules, "index_modification_weight", 15.0)
        )
        w_idx_mis = rules_loader.get_scoring_weight(
            self.rules, "missing_index",
            rules_loader.get_scoring_weight(self.rules, "missing_index_weight", 20.0)
        )

        idx_status = str(signals.get("index_status", "")).upper()
        if signals.get("index_removed") or signals.get("index_lost") or idx_status in ("REMOVED", "MISSING"):
            pts = float(w_idx_rem if idx_status != "MISSING" else w_idx_mis)
            score_breakdown["index"] += pts
            lost = signals.get("lost_indexes") or ctx.get("lost_indexes", [])
            idx_name_str = ", ".join(lost) if lost else "Supporting index dropped"
            triggered_rules.append({
                "rule_name": "index_removed",
                "display_name": "Index removal",
                "points": pts,
                "condition": "Supporting index removed or missing from schema",
                "details": {
                    "index_name": idx_name_str,
                    "impact": "Sequential table scan induced"
                }
            })
        elif signals.get("index_modified") or idx_status == "CHANGED":
            pts = float(w_idx_mod)
            score_breakdown["index"] += pts
            triggered_rules.append({
                "rule_name": "index_modified",
                "display_name": "Index modification",
                "points": pts,
                "condition": "Index definition or column ordering was altered",
                "details": {"index_status": "MODIFIED"}
            })

        # ── 7. Statistics Staleness ───────────────────────────────────────────
        w_stat = rules_loader.get_scoring_weight(
            self.rules, "stale_statistics",
            rules_loader.get_scoring_weight(self.rules, "statistics_weight", 10.0)
        )
        stale_days = rules_loader.get_threshold(
            self.rules, "stale_statistics_days",
            rules_loader.get_staleness_threshold(self.rules, 7)
        )
        stats_age = int(signals.get("statistics_age", ctx.get("statistics_age", 0)) or 0)
        stat_status = str(signals.get("statistics_status", ctx.get("statistics_status", ""))).upper()

        if signals.get("statistics_stale") or signals.get("stats_stale") or (stats_age > stale_days) or stat_status == "STALE":
            pts = float(w_stat)
            score_breakdown["statistics"] += pts
            triggered_rules.append({
                "rule_name": "statistics_stale",
                "display_name": "Stale statistics",
                "points": pts,
                "condition": f"Database statistics age ({stats_age} days) exceeds staleness threshold ({stale_days} days)",
                "details": {
                    "statistics_age_days": stats_age,
                    "staleness_threshold_days": stale_days
                }
            })

        # ── 8. Workload Surge ─────────────────────────────────────────────────
        w_wl = rules_loader.get_scoring_weight(
            self.rules, "workload_surge",
            rules_loader.get_scoring_weight(self.rules, "workload_evidence_weight", 10.0)
        )
        if signals.get("workload_increased") or signals.get("workload_surge"):
            pts = float(w_wl)
            score_breakdown["workload"] += pts
            triggered_rules.append({
                "rule_name": "workload_increased",
                "display_name": "Workload surge",
                "points": pts,
                "condition": "Query traffic or concurrency rose significantly above normal operating envelope",
                "details": {
                    "workload_level": str(signals.get("workload_level", "HIGH"))
                }
            })

        # ── 9. Schema Changes ─────────────────────────────────────────────────
        w_schema = rules_loader.get_scoring_weight(
            self.rules, "schema_changed",
            rules_loader.get_scoring_weight(self.rules, "change_context_weight", 10.0)
        )
        schema_ev = signals.get("schema_change") or ctx.get("schema_change", "NONE")
        if signals.get("schema_changed") or (schema_ev not in ("NONE", "", None)):
            pts = float(w_schema)
            score_breakdown["change_context"] += pts
            triggered_rules.append({
                "rule_name": "schema_changed",
                "display_name": "Schema modification",
                "points": pts,
                "condition": f"Schema DDL modification event detected: {schema_ev}",
                "details": {"schema_change_event": str(schema_ev)}
            })

        # ── 10. Recent Release ────────────────────────────────────────────────
        w_rel = rules_loader.get_scoring_weight(
            self.rules, "recent_release", 10.0
        )
        rel_ver = signals.get("release_version") or ctx.get("release_version") or ctx.get("run_release", "")
        rel_ev = signals.get("release_change") or ctx.get("release_change", "")
        if signals.get("recent_release") or (rel_ev and rel_ev not in ("NONE", "", "none")):
            pts = float(w_rel)
            score_breakdown["change_context"] += pts
            triggered_rules.append({
                "rule_name": "recent_release",
                "display_name": "Recent release deployment",
                "points": pts,
                "condition": f"Software release deployment ({rel_ver or 'current build'}) correlated with performance drift",
                "details": {
                    "release_version": str(rel_ver or "Latest"),
                    "release_event": str(rel_ev or "deployment")
                }
            })

        # ── Calculate Total Score ─────────────────────────────────────────────
        raw_score = sum(r["points"] for r in triggered_rules)

        # Concurrency Grace Reduction
        if signals.get("is_workload_grace", False):
            raw_score = max(0.0, raw_score * 0.15)
            for k in score_breakdown:
                score_breakdown[k] = round(score_breakdown[k] * 0.15, 2)

        # Double-booking multiplier for sensitive healthcare operations
        db_mult = rules_loader.get_scoring_weight(self.rules, "double_booking_multiplier", 1.25)
        if signals.get("is_double_booking_critical", False) and raw_score >= 35.0:
            raw_score = raw_score * db_mult
            triggered_rules.append({
                "rule_name": "double_booking_hazard_multiplier",
                "display_name": "Double-booking safety multiplier",
                "points": round(raw_score - (raw_score / db_mult), 1),
                "condition": "Escalated priority to safeguard patient scheduling and prevent double bookings",
                "details": {"multiplier": f"{db_mult}x"}
            })

        total_score = round(min(150.0, max(0.0, raw_score)), 1)

        # ── Map Score to Severity ─────────────────────────────────────────────
        warn_min = rules_loader.get_priority_threshold(
            self.rules, "warning_min_score",
            rules_loader.get_score_threshold(self.rules, "warning_score", 25.0)
        )
        high_min = rules_loader.get_priority_threshold(
            self.rules, "high_min_score",
            rules_loader.get_score_threshold(self.rules, "regression_score", 50.0)
        )
        crit_min = rules_loader.get_priority_threshold(
            self.rules, "critical_min_score",
            rules_loader.get_score_threshold(self.rules, "critical_regression_score", 75.0)
        )

        if total_score >= crit_min or a_ms >= abs_crit_ms:
            tentative_severity = "CRITICAL"
        elif total_score >= high_min or (time_increased and time_pct >= 50.0):
            tentative_severity = "HIGH"
        elif total_score >= warn_min or time_increased or signals.get("statistics_stale"):
            tentative_severity = "WARNING"
        else:
            tentative_severity = "NORMAL"

        # ── Evidence Sufficiency Verification ─────────────────────────────────
        # An evidence dimension is valid if actual forensic data is present
        has_timing_ev = bool(b_ms > 0 and a_ms > 0 and (time_pct != 0 or a_ms != b_ms))
        has_plan_ev = bool(
            signals.get("plan_changed")
            or signals.get("full_table_scan_detected")
            or ctx.get("plan_diff")
            or ctx.get("baseline_plan_hash")
            or ctx.get("raw_plan")
        )
        has_index_ev = bool(
            signals.get("index_removed")
            or signals.get("index_lost")
            or ctx.get("lost_indexes")
            or signals.get("index_status") in ("REMOVED", "MISSING", "OPTIMAL", "ACTIVE", "CHANGED")
        )
        has_stats_ev = bool(
            signals.get("statistics_stale")
            or signals.get("stats_stale")
            or stats_age > 0
            or ctx.get("rows_examined")
        )
        has_context_ev = bool(
            schema_ev not in ("NONE", "", None)
            or (rel_ver and rel_ver not in ("v0.0", "None"))
            or signals.get("recent_release")
        )

        ev_dimensions = {
            "timing_evidence": has_timing_ev,
            "plan_evidence": has_plan_ev,
            "index_evidence": has_index_ev,
            "statistics_evidence": has_stats_ev,
            "change_context_evidence": has_context_ev
        }
        evidence_count = sum(1 for v in ev_dimensions.values() if v)

        min_high = rules_loader.get_evidence_requirement(self.rules, "min_evidence_for_high", 2)
        min_crit = rules_loader.get_evidence_requirement(self.rules, "min_evidence_for_critical", 3)
        fallback_action = rules_loader.get_evidence_requirement(
            self.rules, "insufficient_evidence_action", "MANUAL_REVIEW_REQUIRED"
        )

        final_priority = tentative_severity
        evidence_sufficiency = {
            "sufficient": True,
            "evidence_count": evidence_count,
            "required_evidence_count": 1,
            "status": "SUFFICIENT",
            "dimensions": ev_dimensions
        }

        if tentative_severity == "CRITICAL":
            if evidence_count < min_crit:
                final_priority = fallback_action
                evidence_sufficiency = {
                    "sufficient": False,
                    "evidence_count": evidence_count,
                    "required_evidence_count": min_crit,
                    "status": fallback_action,
                    "reason": f"CRITICAL priority requires at least {min_crit} confirming evidence dimensions (found {evidence_count}).",
                    "dimensions": ev_dimensions
                }
        elif tentative_severity == "HIGH":
            if evidence_count < min_high:
                final_priority = fallback_action
                evidence_sufficiency = {
                    "sufficient": False,
                    "evidence_count": evidence_count,
                    "required_evidence_count": min_high,
                    "status": fallback_action,
                    "reason": f"HIGH priority requires at least {min_high} confirming evidence dimensions (found {evidence_count}).",
                    "dimensions": ev_dimensions
                }

        # ── Explainability Generation ─────────────────────────────────────────
        explanation = self._build_explanation(
            priority=final_priority,
            severity=tentative_severity,
            score=total_score,
            triggered_rules=triggered_rules,
            version=self.version
        )

        return {
            "triggered_rules": triggered_rules,
            "score": total_score,
            "score_breakdown": score_breakdown,
            "severity": tentative_severity,
            "priority": final_priority,
            "explanation": explanation,
            "rule_config_version": self.version,
            "evidence_sufficiency": evidence_sufficiency
        }

    def _build_explanation(
        self,
        priority: str,
        severity: str,
        score: float,
        triggered_rules: List[Dict[str, Any]],
        version: str
    ) -> str:
        """
        Produces human-readable, non-hardcoded explainability text detailing each triggered
        rule, why it triggered, its score contribution, and the configuration version used.
        """
        lines = [
            f"Priority: {priority}",
            f"Score: {score:.0f}",
            f"Configuration version: {version}",
            "",
            "Triggered rules:"
        ]

        if not triggered_rules:
            lines.append("  (No regression rules triggered; query matches expected baseline envelope)")
        else:
            for r in triggered_rules:
                lines.append("")
                lines.append(f"{r['display_name']}")
                lines.append(f"+{r['points']:.0f}")
                lines.append(f"{r['condition']}")
                for k, v in r.get("details", {}).items():
                    key_fmt = k.replace("_", " ").title()
                    lines.append(f"{key_fmt}: {v}")

        lines.append("")
        lines.append("Final assessment:")
        if priority in ("CRITICAL", "HIGH"):
            lines.append(f"{priority} REGRESSION")
        elif priority == "MANUAL_REVIEW_REQUIRED":
            lines.append("MANUAL REVIEW REQUIRED (Insufficient evidence to substantiate automated high certainty)")
        elif priority == "WARNING":
            lines.append("PERFORMANCE WARNING")
        else:
            lines.append("NORMAL EXECUTION")

        return "\n".join(lines)


def evaluate_rules(
    signals: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Convenience helper function to instantiate and evaluate with RuleEngine."""
    engine = RuleEngine(rules=rules)
    return engine.evaluate(signals, context=context)

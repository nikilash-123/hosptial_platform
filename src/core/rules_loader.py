"""
rules_loader.py
================
Loads and validates rules.yaml. All detection thresholds come from here.
No hard-coded detection or priority decisions in Python code.
"""

import os
import yaml
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")

REQUIRED_KEYS = [
    "thresholds",
    "plan_rules",
    "stats_rules",
    "severity_matrix",
    "false_positive_grace",
    "roles",
]


class RulesValidationError(Exception):
    """Raised when rules.yaml is missing required keys or has invalid values."""


def validate_rules_dict(rules: Dict[str, Any]) -> None:
    """
    Validates a loaded rules mapping.
    Raises RulesValidationError if any key is missing or values violate constraints:
      - Required sections must exist
      - All thresholds, percentages, and weights must be non-negative numbers
      - Score thresholds must be logically ordered: warning <= high <= critical
      - Critical execution time threshold cannot be lower than warning threshold
      - Evidence requirements must be non-negative integers with high <= critical
    """
    if not isinstance(rules, dict):
        raise RulesValidationError("rules must be a dictionary/mapping at the top level.")

    missing = [k for k in REQUIRED_KEYS if k not in rules]
    if missing:
        raise RulesValidationError(f"rules is missing required sections: {missing}")

    th = rules.get("thresholds", {})
    if not isinstance(th, dict):
        raise RulesValidationError("thresholds must be a mapping of threshold names to values.")

    required_th_keys = (
        "time_regression_pct", "time_critical_pct", "time_high_pct",
        "absolute_critical_ms", "absolute_high_ms"
    )
    for key in required_th_keys:
        if key not in th:
            raise RulesValidationError(f"thresholds.{key} is required in rules.")

    # Validate all numeric thresholds are non-negative
    for k, v in th.items():
        if isinstance(v, bool):
            continue
        if not isinstance(v, (int, float)):
            raise RulesValidationError(f"thresholds.{k} must be a number, got {type(v).__name__}.")
        if v < 0:
            raise RulesValidationError(f"thresholds.{k} must be non-negative (>= 0), got {v}.")

    # Logical ordering of execution time thresholds
    warn_ms = th.get("execution_time_warning_ms", th.get("absolute_high_ms", 500.0))
    crit_ms = th.get("execution_time_critical_ms", th.get("absolute_critical_ms", 2000.0))
    if warn_ms > crit_ms:
        raise RulesValidationError(
            f"Execution time warning threshold ({warn_ms}ms) cannot exceed critical threshold ({crit_ms}ms)."
        )

    # Logical ordering of percentage thresholds
    warn_pct = th.get("time_regression_pct", 20.0)
    crit_pct = th.get("time_critical_pct", 100.0)
    if warn_pct > crit_pct:
        raise RulesValidationError(
            f"Timing regression warning % ({warn_pct}%) cannot exceed critical % ({crit_pct}%)."
        )

    # Validate scoring weights
    weights = rules.get("scoring_weights", {})
    if isinstance(weights, dict):
        for wk, wv in weights.items():
            if not isinstance(wv, (int, float)):
                raise RulesValidationError(f"scoring_weights.{wk} must be numeric, got {type(wv).__name__}.")
            if wv < 0:
                raise RulesValidationError(f"scoring_weights.{wk} must be >= 0, got {wv}.")

    # Validate score / priority thresholds
    p_thresh = rules.get("priority_thresholds") or rules.get("score_thresholds") or {}
    if isinstance(p_thresh, dict):
        warn_score = p_thresh.get("warning_min_score", p_thresh.get("warning_score", 25.0))
        high_score = p_thresh.get("high_min_score", p_thresh.get("regression_score", 50.0))
        crit_score = p_thresh.get("critical_min_score", p_thresh.get("critical_regression_score", 75.0))

        for sk, sv in p_thresh.items():
            if not isinstance(sv, (int, float)):
                raise RulesValidationError(f"score threshold {sk} must be numeric, got {type(sv).__name__}.")
            if sv < 0:
                raise RulesValidationError(f"score threshold {sk} must be >= 0, got {sv}.")

        if not (warn_score <= high_score <= crit_score):
            raise RulesValidationError(
                f"Priority score thresholds must be logically ordered: "
                f"warning ({warn_score}) <= high ({high_score}) <= critical ({crit_score})."
            )

    # Validate evidence requirements
    ev_req = rules.get("evidence_requirements", {})
    if isinstance(ev_req, dict):
        min_high = ev_req.get("min_evidence_for_high", 2)
        min_crit = ev_req.get("min_evidence_for_critical", 3)
        if not isinstance(min_high, int) or min_high < 0:
            raise RulesValidationError(f"min_evidence_for_high must be a non-negative integer, got {min_high}.")
        if not isinstance(min_crit, int) or min_crit < 0:
            raise RulesValidationError(f"min_evidence_for_critical must be a non-negative integer, got {min_crit}.")
        if min_high > min_crit:
            raise RulesValidationError(
                f"min_evidence_for_high ({min_high}) cannot exceed min_evidence_for_critical ({min_crit})."
            )

    fp = rules.get("false_positive_grace", {})
    if fp.get("noise_band_pct", 0) < 0:
        raise RulesValidationError("false_positive_grace.noise_band_pct must be >= 0.")


def load_rules(path: str = DEFAULT_RULES_PATH) -> Dict[str, Any]:
    """Load and validate rules.yaml. Returns the parsed dict."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"rules.yaml not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        rules = yaml.safe_load(f)

    validate_rules_dict(rules)
    return rules


def get_rule_version(rules: Dict[str, Any], default: str = "v1.0") -> str:
    """Returns rule configuration version string."""
    return str(rules.get("rule_config_version", default))


def get_threshold(rules: Dict[str, Any], key: str, default: float = 0.0) -> float:
    return float(rules.get("thresholds", {}).get(key, default))


def get_plan_rule(rules: Dict[str, Any], key: str, default: bool = True) -> bool:
    return bool(rules.get("plan_rules", {}).get(key, default))


def get_stats_rule(rules: Dict[str, Any], key: str, default: float = 50.0) -> float:
    return float(rules.get("stats_rules", {}).get(key, default))


def get_workload_rule(rules: Dict[str, Any], key: str, default: Any = None) -> Any:
    return rules.get("workload_rules", {}).get(key, default)


def get_index_rule(rules: Dict[str, Any], key: str, default: bool = True) -> bool:
    return bool(rules.get("index_rules", {}).get(key, default))


def get_staleness_threshold(rules: Dict[str, Any], default: int = 30) -> int:
    return int(rules.get("stats_rules", {}).get("stats_staleness_days_threshold", default))


def get_scoring_weight(rules: Dict[str, Any], key: str, default: float = 10.0) -> float:
    return float(rules.get("scoring_weights", {}).get(key, default))


def get_score_threshold(rules: Dict[str, Any], key: str, default: float = 50.0) -> float:
    # Check priority_thresholds first, then score_thresholds
    if "priority_thresholds" in rules:
        val = rules["priority_thresholds"].get(key)
        if val is not None:
            return float(val)
    return float(rules.get("score_thresholds", {}).get(key, default))


def get_priority_threshold(rules: Dict[str, Any], key: str, default: float = 50.0) -> float:
    return get_score_threshold(rules, key, default)


def get_evidence_requirement(rules: Dict[str, Any], key: str, default: Any = None) -> Any:
    return rules.get("evidence_requirements", {}).get(key, default)


def get_noise_band(rules: Dict[str, Any]) -> float:
    return float(rules.get("false_positive_grace", {}).get("noise_band_pct", 10.0))


def get_role_caps(rules: Dict[str, Any], role: str) -> Dict[str, bool]:
    return rules.get("roles", {}).get(role, {})


def get_change_context_rule(rules: Dict[str, Any], key: str, default: Any = None) -> Any:
    return rules.get("change_context", {}).get(key, default)

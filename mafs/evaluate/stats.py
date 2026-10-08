"""통계 분석 모듈 — RQ1~RQ3 공통 사용.

측정 지표
─────────
  score_total  (0~20) : C1~C5 + M1~M5 합계 (기준당 0/1/2)
  score_trigger(0~8)  : C1·C2·M1·M4 (재합성 트리거 기준) 합계
  score_ref    (0~12) : C3·C4·C5·M2·M3·M5 (참고 기준) 합계
  per_criterion       : 각 기준별 평균 점수 (0.0~2.0)

RQ1 / RQ2 (쌍대 비교, 동일 에세이)
  - Wilcoxon 부호 순위 검정 (비모수, 쌍대)
  - 효과 크기: r = Z / √N  (rank-biserial)
  - 4조건 이상이면 Friedman 검정 후 쌍대 Bonferroni 사후 검정

RQ3 (독립 집단, 교과·목적·학년별)
  - Kruskal-Wallis 검정
  - η² = (H - k + 1) / (N - k)  효과 크기
  - 사후 검정: Mann-Whitney U + Bonferroni
"""

from __future__ import annotations
import math
from typing import Sequence
from collections import defaultdict

import numpy as np
from scipy import stats as sp_stats

CRITERIA       = ["C1", "C2", "C3", "C4", "C5", "M1", "M2", "M3", "M4", "M5"]
TRIGGER_CRIT   = ["C1", "C2", "M1", "M4"]
REF_CRIT       = [c for c in CRITERIA if c not in TRIGGER_CRIT]
SCORE_KEYS     = ["score_total", "score_trigger", "score_ref"]


# ──────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────

def _extract(scores_list: list[dict], key: str) -> np.ndarray:
    return np.array([s[key] for s in scores_list if s is not None], dtype=float)


def _desc(arr: np.ndarray) -> dict:
    return {
        "n":      int(len(arr)),
        "mean":   float(np.mean(arr)),
        "sd":     float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
        "median": float(np.median(arr)),
        "min":    float(np.min(arr)),
        "max":    float(np.max(arr)),
    }


def _pass_rates(scores_list: list[dict]) -> dict[str, float]:
    valid = [s for s in scores_list if s is not None]
    if not valid:
        return {c: float("nan") for c in CRITERIA}
    return {c: sum(s[c] for s in valid) / len(valid) for c in CRITERIA}


def _wilcoxon(a: np.ndarray, b: np.ndarray) -> dict:
    """Wilcoxon 부호 순위 검정 + 효과 크기 r."""
    diff = a - b
    if np.all(diff == 0):
        return {"W": float("nan"), "p": float("nan"), "r": 0.0, "note": "모든 값 동일"}
    try:
        res = sp_stats.wilcoxon(a, b, alternative="two-sided", zero_method="wilcox")
        n   = len(a)
        # z 근사: W → z 변환
        z   = sp_stats.norm.ppf(res.pvalue / 2) * (-1 if res.statistic > n*(n+1)/4 else 1)
        r   = abs(z) / math.sqrt(n)
        return {"W": float(res.statistic), "p": float(res.pvalue), "r": round(r, 3)}
    except Exception as e:
        return {"W": float("nan"), "p": float("nan"), "r": float("nan"), "note": str(e)}


def _friedman(groups: list[np.ndarray]) -> dict:
    """Friedman 검정 (≥3 조건, 동일 N)."""
    try:
        res = sp_stats.friedmanchisquare(*groups)
        k, n = len(groups), len(groups[0])
        W = (res.statistic / (n * (k - 1))) if n * (k - 1) > 0 else float("nan")
        return {"chi2": float(res.statistic), "p": float(res.pvalue),
                "df": k - 1, "kendall_W": round(W, 3)}
    except Exception as e:
        return {"chi2": float("nan"), "p": float("nan"), "note": str(e)}


def _kruskal(groups: dict[str, np.ndarray]) -> dict:
    """Kruskal-Wallis 검정 + η² 효과 크기."""
    arrs = list(groups.values())
    if len(arrs) < 2:
        return {"H": float("nan"), "p": float("nan"), "note": "집단 < 2"}
    try:
        res  = sp_stats.kruskal(*arrs)
        n    = sum(len(a) for a in arrs)
        k    = len(arrs)
        eta2 = (res.statistic - k + 1) / (n - k) if n > k else float("nan")
        return {"H": float(res.statistic), "p": float(res.pvalue),
                "df": k - 1, "eta2": round(eta2, 3)}
    except Exception as e:
        return {"H": float("nan"), "p": float("nan"), "note": str(e)}


def _pairwise_wilcoxon(groups: dict[str, np.ndarray], alpha: float = 0.05) -> list[dict]:
    """모든 쌍에 대해 Mann-Whitney U (독립) 또는 Wilcoxon (쌍대) + Bonferroni 보정."""
    names = list(groups.keys())
    m = len(names) * (len(names) - 1) // 2      # 비교 쌍 수 (Bonferroni 분모)
    results = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = groups[names[i]], groups[names[j]]
            try:
                res  = sp_stats.mannwhitneyu(a, b, alternative="two-sided")
                p_adj = min(float(res.pvalue) * m, 1.0)
                n1, n2 = len(a), len(b)
                r    = 1 - (2 * res.statistic) / (n1 * n2) if n1 * n2 > 0 else float("nan")
            except Exception as e:
                p_adj, r = float("nan"), float("nan")
            results.append({
                "group_a": names[i], "group_b": names[j],
                "U": float(res.statistic) if "res" in dir() else float("nan"),
                "p_adj": round(p_adj, 4), "r": round(r, 3),
                "sig": p_adj < alpha,
            })
    return results


# ──────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────

def paired_comparison(
    scores_a: list[dict],
    scores_b: list[dict],
    label_a: str = "A",
    label_b: str = "B",
    metric: str = "score_total",
) -> dict:
    """두 조건의 쌍대 비교 (RQ1 / RQ2 두 조건 비교).

    Returns:
        {
          "descriptive": {label_a: {...}, label_b: {...}},
          "pass_rates":  {label_a: {C1:0.8,...}, label_b: {...}},
          "wilcoxon":    {"W":..., "p":..., "r":...},
          "metric":      "score_total"
        }
    """
    a = _extract(scores_a, metric)
    b = _extract(scores_b, metric)
    n = min(len(a), len(b))
    return {
        "metric":      metric,
        "descriptive": {label_a: _desc(a[:n]), label_b: _desc(b[:n])},
        "pass_rates":  {label_a: _pass_rates(scores_a), label_b: _pass_rates(scores_b)},
        "wilcoxon":    _wilcoxon(a[:n], b[:n]),
    }


def multi_condition_comparison(
    scores_dict: dict[str, list[dict]],
    metric: str = "score_total",
) -> dict:
    """N개 조건의 쌍대 비교 (RQ2 4조건).

    scores_dict: {"A_mafs_full": [...], "B_single_llm": [...], ...}
    각 리스트는 동일 에세이 순서로 정렬되어 있어야 한다.

    Returns:
        {
          "descriptive": {조건명: {...}, ...},
          "pass_rates":  {조건명: {C1:..., ...}, ...},
          "friedman":    {"chi2":..., "p":..., "kendall_W":...},
          "pairwise":    [{group_a, group_b, W, p_adj, r, sig}, ...]
        }
    """
    arrays  = {k: _extract(v, metric) for k, v in scores_dict.items()}
    n       = min(len(a) for a in arrays.values())
    trimmed = {k: a[:n] for k, a in arrays.items()}

    return {
        "metric":      metric,
        "descriptive": {k: _desc(a) for k, a in trimmed.items()},
        "pass_rates":  {k: _pass_rates(v) for k, v in scores_dict.items()},
        "friedman":    _friedman(list(trimmed.values())),
        "pairwise":    _pairwise_wilcoxon(trimmed),
    }


def group_comparison(
    records: list[dict],
    group_by: str,
    metric: str = "score_total",
) -> dict:
    """독립 집단 비교 (RQ3 교과·목적·학교급).

    records: [{"subject":"국어", "judge_scores":{...}, ...}, ...]
    group_by: "subject" | "purpose" | "grade_level"

    Returns:
        {
          "group_by":    "subject",
          "metric":      "score_total",
          "descriptive": {집단명: {...}, ...},
          "pass_rates":  {집단명: {C1:..., ...}, ...},
          "kruskal":     {"H":..., "p":..., "eta2":...},
          "pairwise":    [...]
        }
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        scores = r.get("judge_scores")
        if not scores:
            continue
        key = r.get(group_by, "?") or "?"
        grouped[key].append(scores)

    arrays = {k: _extract(v, metric) for k, v in grouped.items() if v}
    return {
        "group_by":    group_by,
        "metric":      metric,
        "descriptive": {k: _desc(a) for k, a in arrays.items()},
        "pass_rates":  {k: _pass_rates(v) for k, v in grouped.items()},
        "kruskal":     _kruskal(arrays),
        "pairwise":    _pairwise_wilcoxon(arrays),
    }


# ──────────────────────────────────────────────────
# 출력 헬퍼
# ──────────────────────────────────────────────────

def _sig_stars(p: float) -> str:
    if math.isnan(p): return ""
    if p < 0.001: return "***"
    if p < 0.01:  return "**"
    if p < 0.05:  return "*"
    return "n.s."


def print_paired_result(result: dict) -> None:
    """paired_comparison / multi_condition_comparison 출력."""
    metric = result["metric"]
    desc   = result["descriptive"]
    pr     = result["pass_rates"]

    print(f"\n{'━'*65}")
    print(f"  비교 지표: {metric}   (LLM 판사 채점, 0~20점)")
    print(f"{'━'*65}")
    print(f"  {'조건':<22} {'N':>4}  {'평균':>6}  {'SD':>5}  {'중앙값':>7}")
    print(f"  {'-'*55}")
    for cond, d in desc.items():
        print(f"  {cond:<22} {d['n']:>4}  {d['mean']:>6.2f}  {d['sd']:>5.2f}  {d['median']:>7.1f}")

    # Wilcoxon (두 조건)
    if "wilcoxon" in result:
        w = result["wilcoxon"]
        stars = _sig_stars(w.get("p", float("nan")))
        print(f"\n  Wilcoxon: W={w.get('W',float('nan')):.1f}  p={w.get('p',float('nan')):.4f}{stars}"
              f"  r={w.get('r',float('nan')):.3f}")

    # Friedman (N조건)
    if "friedman" in result:
        f = result["friedman"]
        stars = _sig_stars(f.get("p", float("nan")))
        print(f"\n  Friedman: χ²({f.get('df','?')})={f.get('chi2',float('nan')):.3f}"
              f"  p={f.get('p',float('nan')):.4f}{stars}"
              f"  Kendall W={f.get('kendall_W',float('nan')):.3f}")
        if result.get("pairwise"):
            print(f"\n  사후 검정 (Bonferroni 보정):")
            for pw in result["pairwise"]:
                sig = "●" if pw["sig"] else "○"
                print(f"    {sig} {pw['group_a']} vs {pw['group_b']:<22}"
                      f"  p={pw['p_adj']:.4f}  r={pw['r']:.3f}")

    # 기준별 평균 점수 비교 (0~2)
    conds = list(pr.keys())
    print(f"\n  기준별 평균 점수 (0~2):")
    print(f"  {'기준':<6}" + "".join(f"  {c:>10}" for c in conds))
    print(f"  {'-'*55}")
    for c in CRITERIA:
        tag = " ←" if c in TRIGGER_CRIT else ""
        row = f"  {c:<6}"
        for cond in conds:
            avg = pr[cond].get(c, float("nan"))
            row += f"  {avg:>10.2f}"
        print(row + tag)
    print(f"{'━'*65}")


def print_group_result(result: dict) -> None:
    """group_comparison 출력."""
    metric   = result["metric"]
    group_by = result["group_by"]
    desc     = result["descriptive"]
    kr       = result["kruskal"]
    pr       = result["pass_rates"]

    print(f"\n{'━'*65}")
    print(f"  집단 구분: {group_by}   지표: {metric}")
    print(f"{'━'*65}")
    print(f"  {'집단':<14} {'N':>4}  {'평균':>6}  {'SD':>5}  {'중앙값':>7}")
    print(f"  {'-'*50}")
    for g, d in sorted(desc.items()):
        print(f"  {g:<14} {d['n']:>4}  {d['mean']:>6.2f}  {d['sd']:>5.2f}  {d['median']:>7.1f}")

    stars = _sig_stars(kr.get("p", float("nan")))
    print(f"\n  Kruskal-Wallis: H({kr.get('df','?')})={kr.get('H',float('nan')):.3f}"
          f"  p={kr.get('p',float('nan')):.4f}{stars}"
          f"  η²={kr.get('eta2',float('nan')):.3f}")

    sig_pairs = [pw for pw in result.get("pairwise", []) if pw["sig"]]
    if sig_pairs:
        print(f"\n  유의한 쌍대 비교 (Bonferroni 보정, p<.05):")
        for pw in sig_pairs:
            print(f"    {pw['group_a']} vs {pw['group_b']:<14}"
                  f"  p={pw['p_adj']:.4f}  r={pw['r']:.3f}")
    else:
        print(f"\n  유의한 쌍대 차이 없음 (Bonferroni 보정 후)")

    groups = list(pr.keys())
    print(f"\n  기준별 평균 점수 (0~2, 교과별):")
    print(f"  {'기준':<6}" + "".join(f"  {g:>10}" for g in sorted(groups)))
    print(f"  {'-'*55}")
    for c in CRITERIA:
        tag = " ←" if c in TRIGGER_CRIT else ""
        row = f"  {c:<6}"
        for g in sorted(groups):
            avg = pr.get(g, {}).get(c, float("nan"))
            row += f"  {avg:>10.2f}"
        print(row + tag)
    print(f"{'━'*65}")

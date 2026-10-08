"""교차검증 분석 — gemini 채점 vs GPT-4o 채점의 일치도.

sample_cross_check.py가 만든 cross_check_key.jsonl(gemini 점수, 조건 라벨)과
cross_check_score.py가 만든 cross_check_gpt4o.jsonl(GPT-4o 점수)을 item_id로
결합하여 다음을 계산한다.

  1) ICC (급내상관계수) — score_total(0~20)에 대한 gemini-GPT4o 일치도
  2) 기준별(C1~M5) 일치율 + Spearman 상관
  3) 조건(A/B/C)별 평균 점수 비교 — 두 채점자에서 순위(A>B, A>C)가
     동일하게 유지되는지 확인 (연구 결론의 모델 독립성 근거)

실행 예시 (MISCA/ 루트에서):
    python mafs/evaluate/cross_check_analysis.py \\
        --key mafs/evaluate/results/cross_check_key.jsonl \\
        --gpt4o mafs/evaluate/results/cross_check_gpt4o.jsonl
"""

import sys
import json
import argparse
import collections
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from scipy import stats as sp_stats

CRITERIA = ["C1", "C2", "C3", "C4", "C5", "M1", "M2", "M3", "M4", "M5"]


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main(key_path: str, gpt4o_path: str) -> None:
    key_records = {r["item_id"]: r for r in _load_jsonl(Path(key_path))}
    gpt4o_records = {r["item_id"]: r for r in _load_jsonl(Path(gpt4o_path))}

    joined = []
    for item_id, key_rec in key_records.items():
        g_rec = gpt4o_records.get(item_id)
        if g_rec is None or g_rec.get("gpt4o_scores") is None:
            continue
        joined.append({
            "item_id": item_id,
            "condition": key_rec["condition"],
            "gemini": key_rec["gemini_scores"],
            "gpt4o": g_rec["gpt4o_scores"],
        })

    n_total = len(key_records)
    n_joined = len(joined)
    print(f"[교차검증분석] 결합된 건수: {n_joined} / {n_total}")
    if n_joined < n_total:
        missing = set(key_records) - {j["item_id"] for j in joined}
        print(f"  [경고] GPT-4o 채점 누락/실패: {sorted(missing)}")
    if n_joined < 5:
        print("[교차검증분석] 표본이 너무 적어 통계 산출을 생략합니다.")
        return

    # ── 1) ICC (score_total) ──
    print(f"\n{'='*60}")
    print("[1] ICC — score_total (0~20), gemini vs GPT-4o")
    print(f"{'='*60}")
    try:
        import pandas as pd
        import pingouin as pg

        rows = []
        for j in joined:
            rows.append({"item": j["item_id"], "rater": "gemini", "score": j["gemini"]["score_total"]})
            rows.append({"item": j["item_id"], "rater": "gpt4o", "score": j["gpt4o"]["score_total"]})
        df = pd.DataFrame(rows)
        icc_table = pg.intraclass_corr(data=df, targets="item", raters="rater", ratings="score")
        print(icc_table.to_string(index=False))
        icc2 = icc_table[icc_table["Type"] == "ICC2"]
        if not icc2.empty:
            row = icc2.iloc[0]
            print(f"\n  → ICC2(단일 평정자, 절대일치) = {row['ICC']:.3f}"
                  f"  95% CI [{row['CI95%'][0]:.3f}, {row['CI95%'][1]:.3f}]  p={row['pval']:.4f}")
    except ImportError:
        print("  [건너뜀] pingouin/pandas 미설치 — `pip install pingouin` 필요")

    # ── 2) 기준별 일치율 + Spearman ──
    print(f"\n{'='*60}")
    print("[2] 기준별(C1~M5) 일치율 및 상관")
    print(f"{'='*60}")
    print(f"  {'기준':<6} {'정확일치율':>10} {'±1이내':>8} {'Spearman ρ':>12}")
    print(f"  {'-'*45}")
    for c in CRITERIA:
        g_vals = np.array([j["gemini"][c] for j in joined])
        o_vals = np.array([j["gpt4o"][c] for j in joined])
        exact = float(np.mean(g_vals == o_vals))
        within1 = float(np.mean(np.abs(g_vals - o_vals) <= 1))
        if np.std(g_vals) == 0 or np.std(o_vals) == 0:
            rho = float("nan")
        else:
            rho, _ = sp_stats.spearmanr(g_vals, o_vals)
        print(f"  {c:<6} {exact:>9.1%} {within1:>8.1%} {rho:>12.3f}")

    # ── 3) 조건(A/B/C)별 평균 — 순위 일치 확인 ──
    print(f"\n{'='*60}")
    print("[3] 조건별 score_total 평균 — 채점자 간 순위 일치 확인")
    print(f"{'='*60}")
    by_cond_gemini: dict[str, list[float]] = collections.defaultdict(list)
    by_cond_gpt4o: dict[str, list[float]] = collections.defaultdict(list)
    for j in joined:
        by_cond_gemini[j["condition"]].append(j["gemini"]["score_total"])
        by_cond_gpt4o[j["condition"]].append(j["gpt4o"]["score_total"])

    print(f"  {'조건':<6} {'N':>4} {'gemini 평균':>12} {'GPT-4o 평균':>12}")
    print(f"  {'-'*40}")
    means_gemini = {}
    means_gpt4o = {}
    for cond in sorted(by_cond_gemini):
        g_mean = float(np.mean(by_cond_gemini[cond]))
        o_mean = float(np.mean(by_cond_gpt4o[cond]))
        means_gemini[cond] = g_mean
        means_gpt4o[cond] = o_mean
        print(f"  {cond:<6} {len(by_cond_gemini[cond]):>4} {g_mean:>12.2f} {o_mean:>12.2f}")

    if "A" in means_gemini and "B" in means_gemini:
        g_order = means_gemini["A"] > means_gemini["B"]
        o_order = means_gpt4o["A"] > means_gpt4o["B"]
        match = "일치 ✓" if g_order == o_order else "불일치 ✗"
        print(f"\n  A vs B (RQ1): gemini A>B={g_order}, GPT-4o A>B={o_order} → {match}")
    if "A" in means_gemini and "C" in means_gemini:
        g_order = means_gemini["A"] > means_gemini["C"]
        o_order = means_gpt4o["A"] > means_gpt4o["C"]
        match = "일치 ✓" if g_order == o_order else "불일치 ✗"
        print(f"  A vs C (RQ2): gemini A>C={g_order}, GPT-4o A>C={o_order} → {match}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gemini vs GPT-4o 채점 일치도 분석")
    parser.add_argument("--key", default="mafs/evaluate/results/cross_check_key.jsonl")
    parser.add_argument("--gpt4o", default="mafs/evaluate/results/cross_check_gpt4o.jsonl")
    args = parser.parse_args()
    main(args.key, args.gpt4o)

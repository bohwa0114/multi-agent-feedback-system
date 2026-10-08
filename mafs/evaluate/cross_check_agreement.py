"""교차검증 채점자 간 일치도 — 스탠퍼드 리뷰 "circularity" 대응 (IV장 4절).

cross_check_key.jsonl(gemini 점수) + cross_check_gpt4o.jsonl(GPT-4o 점수)을
item_id로 결합하여, 45건 x 10개 기준(C1~C5, M1~M5) = 450쌍의 채점을 풀링해
전체 일치율 · Spearman ρ · 이차가중 카파(QWK)를 산출한다.

기존 cross_check_analysis.py는 기준별 분해(per-criterion breakdown)와
score_total(0~20) 수준의 ICC를 보여준다. 이 스크립트는 그 위에 "채점자 간
전반적 일치도"를 하나의 숫자 세트로 요약해 논문 본문 문장에 바로 쓸 수 있게
한다.

실행 예시 (MISCA/ 루트에서):
    python mafs/evaluate/cross_check_agreement.py
"""

import sys
import json
import argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from scipy import stats as sp_stats
from sklearn.metrics import cohen_kappa_score

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

    g_all, o_all = [], []
    g_total, o_total = [], []
    n_items = 0
    for item_id, key_rec in key_records.items():
        g_rec = gpt4o_records.get(item_id)
        if g_rec is None or g_rec.get("gpt4o_scores") is None:
            continue
        gemini_scores = key_rec["gemini_scores"]
        gpt4o_scores = g_rec["gpt4o_scores"]
        n_items += 1
        for c in CRITERIA:
            g_all.append(gemini_scores[c])
            o_all.append(gpt4o_scores[c])
        g_total.append(gemini_scores["score_total"])
        o_total.append(gpt4o_scores["score_total"])

    g_all = np.array(g_all)
    o_all = np.array(o_all)
    n_pairs = len(g_all)

    print(f"[교차채점 일치도] 결합 문항: {n_items}건 x 기준 {len(CRITERIA)}개 = {n_pairs}쌍\n")

    # ── 풀링 수준 (450쌍): 기준-점수 단위 ──
    exact_agree = float(np.mean(g_all == o_all))
    within1 = float(np.mean(np.abs(g_all - o_all) <= 1))
    rho, rho_p = sp_stats.spearmanr(g_all, o_all)
    qwk = cohen_kappa_score(g_all, o_all, weights="quadratic")
    kappa_unweighted = cohen_kappa_score(g_all, o_all)

    print("=" * 60)
    print(f"[풀링 수준] 기준-점수 단위 (N={n_pairs}, 45건 x 10기준)")
    print("=" * 60)
    print(f"  {'지표':<24} {'값'}")
    print(f"  {'-'*45}")
    print(f"  {'정확 일치율':<24} {exact_agree:.1%}")
    print(f"  {'±1 이내 일치율':<24} {within1:.1%}")
    print(f"  {'Spearman ρ':<24} {rho:.3f}  (p={rho_p:.4f})")
    print(f"  {'Cohen κ (unweighted)':<24} {kappa_unweighted:.3f}")
    print(f"  {'Cohen κ (quadratic, QWK)':<24} {qwk:.3f}")

    # ── item 수준 (45쌍): score_total(0~20) ──
    g_total = np.array(g_total, dtype=float)
    o_total = np.array(o_total, dtype=float)
    rho_t, rho_t_p = sp_stats.spearmanr(g_total, o_total)
    pearson_r, pearson_p = sp_stats.pearsonr(g_total, o_total)

    print(f"\n{'='*60}")
    print(f"[문항 수준] score_total 0~20점 (N={n_items})")
    print(f"{'='*60}")
    print(f"  {'지표':<24} {'값'}")
    print(f"  {'-'*45}")
    print(f"  {'Spearman ρ':<24} {rho_t:.3f}  (p={rho_t_p:.4f})")
    print(f"  {'Pearson r':<24} {pearson_r:.3f}  (p={pearson_p:.4f})")
    print(f"  {'gemini 평균':<24} {np.mean(g_total):.2f}")
    print(f"  {'GPT-4o 평균':<24} {np.mean(o_total):.2f}")
    print(f"  {'평균차 (gemini-GPT4o)':<24} {np.mean(g_total - o_total):.2f}")

    # ── 논문 문장 템플릿 ──
    print(f"\n{'='*60}")
    print("[논문 문장 템플릿]")
    print(f"{'='*60}")
    print(
        f"  \"45건 교차채점(450쌍, 10기준)에서 두 채점자 간 정확 일치율은 "
        f"{exact_agree:.1%}, Spearman ρ = {rho:.2f}, "
        f"이차가중 카파(QWK) = {qwk:.2f}였다.\""
    )
    print(
        f"  \"문항 수준(score_total, N={n_items})에서는 두 채점자 간 순위 상관이 "
        f"Spearman ρ = {rho_t:.2f}(p{'<.001' if rho_t_p < .001 else f'={rho_t_p:.3f}'})로 "
        f"나타났다.\""
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gemini vs GPT-4o 교차채점 풀링 일치도 (percent agreement/Spearman/QWK)")
    parser.add_argument("--key", default="mafs/evaluate/results/cross_check_key.jsonl")
    parser.add_argument("--gpt4o", default="mafs/evaluate/results/cross_check_gpt4o.jsonl")
    args = parser.parse_args()
    main(args.key, args.gpt4o)

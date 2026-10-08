"""교차검증용 표본 추출 — gemini 채점의 계열 독립성 확인.

목적:
  gemini가 채점자 역할을 겸하는 것에 대한 "single-model judge 편향" 우려에
  대응하기 위해, 이미 채점된 A/B/C 세 조건의 피드백 중 일부를 무작위로 뽑아
  라벨을 제거(블라인드)하고 2차 모델(GPT-4o)로 재채점할 수 있게 준비한다.

조건 정의 (연구 설계 관점):
  A. MAFS 완전판   — rq1_200.jsonl 의 condition_a  (검증 루프 포함)
  B. Baseline      — rq1_200.jsonl 의 condition_b  (RQ1: 교육이론 설계 효과)
  C. 검증 전 초안  — rq2_200.jsonl 의 conditions.B_no_verify
                      (= rq1의 synthesis_0, 단 채점은 rq2에서 별도 수행됨)
                      (RQ2: 반복 검증 효과)

표본 설계:
  verify_rounds >= 2 인 essay(재생성이 실제로 일어난 70건)에서만 essay를
  선택한다. 이 경우에만 condition_a.feedback != synthesis_0 이 보장되어
  A와 C가 실제로 다른 표본이 된다. 선택된 essay마다 A/B/C 세 조건을 모두
  포함시켜 RQ1(A vs B)·RQ2(A vs C) 비교 구조를 그대로 보존한 paired 표본을
  만든다. (--n_essays 15 → 15문항 x 3조건 = 45건)

출력 (2개 파일, 절대 함께 GPT-4o에 보내지 않는다):
  results/cross_check_blind.jsonl  — item_id, essay, prompt, grade, feedback만
                                       (조건 라벨·gemini 점수 없음 → 2차 채점 입력용)
  results/cross_check_key.jsonl    — item_id, file, condition(A/B/C), gemini 점수
                                       (정답지 — 분석 단계에서만 사용)

실행 예시 (MISCA/ 루트에서):
    python mafs/evaluate/sample_cross_check.py \\
        --rq1 mafs/evaluate/results/rq1_200.jsonl \\
        --rq2 mafs/evaluate/results/rq2_200.jsonl \\
        --n_essays 15 --seed 42 \\
        --out_dir mafs/evaluate/results
"""

import json
import random
import argparse
import collections
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _stratified_pick(eligible: list[dict], n: int, seed: int) -> list[dict]:
    """학년별로 고르게 essay를 뽑는다 (가능한 만큼)."""
    rng = random.Random(seed)
    by_grade: dict[str, list[dict]] = collections.defaultdict(list)
    for rec in eligible:
        by_grade[rec["grade"]].append(rec)
    for grade in by_grade:
        rng.shuffle(by_grade[grade])

    grades = sorted(by_grade.keys())
    picked: list[dict] = []
    i = 0
    while len(picked) < n and any(by_grade[g] for g in grades):
        g = grades[i % len(grades)]
        if by_grade[g]:
            picked.append(by_grade[g].pop())
        i += 1
    return picked[:n]


def main(rq1_path: str, rq2_path: str, n_essays: int, seed: int, out_dir: str) -> None:
    rq1_records = {r["file"]: r for r in _load_jsonl(Path(rq1_path))}
    rq2_records = {r["file"]: r for r in _load_jsonl(Path(rq2_path))}

    eligible = []
    for file, rec in rq1_records.items():
        if rec.get("verify_rounds", 0) < 2:
            continue
        if "condition_b" not in rec or not rec["condition_b"].get("scores"):
            continue
        rq2_rec = rq2_records.get(file)
        if rq2_rec is None:
            continue
        c_cond = rq2_rec.get("conditions", {}).get("B_no_verify")
        if not c_cond or not c_cond.get("scores") or not c_cond.get("feedback"):
            continue
        if c_cond["feedback"] == rec["condition_a"]["feedback"]:
            continue  # refine이 있었다고 기록됐지만 실제 텍스트가 같으면 제외 (안전장치)
        eligible.append(rec)

    print(f"[표본추출] verify_rounds>=2 후보: {len(eligible)}건")
    if len(eligible) < n_essays:
        print(f"[경고] 후보({len(eligible)})가 요청한 essay 수({n_essays})보다 적음 — 전체 사용")
        n_essays = len(eligible)

    picked = _stratified_pick(eligible, n_essays, seed)
    picked_grades = collections.Counter(r["grade"] for r in picked)
    print(f"[표본추출] 선택된 essay: {len(picked)}건, 학년 분포: {dict(picked_grades)}")

    blind_items = []
    key_items = []
    rng = random.Random(seed + 1)

    for rec in picked:
        file = rec["file"]
        rq2_rec = rq2_records[file]
        c_cond = rq2_rec["conditions"]["B_no_verify"]

        triplet = {
            "A": {"feedback": rec["condition_a"]["feedback"], "scores": rec["condition_a"]["scores"]},
            "B": {"feedback": rec["condition_b"]["feedback"], "scores": rec["condition_b"]["scores"]},
            "C": {"feedback": c_cond["feedback"], "scores": c_cond["scores"]},
        }
        for cond_label, payload in triplet.items():
            item_id = f"{Path(file).stem}_{cond_label}"
            blind_items.append({
                "item_id": item_id,
                "essay": rec["essay"],
                "prompt": rec["prompt"],
                "grade": rec["grade"],
            })
            key_items.append({
                "item_id": item_id,
                "file": file,
                "condition": cond_label,
                "grade": rec["grade"],
                "subject": rec["subject"],
                "gemini_scores": payload["scores"],
            })

    # feedback은 blind_items에 별도로 채워야 GPT-4o 입력 스크립트에서 조건 순서를 섞을 수 있음
    # -> item_id로 key_items와 매칭되는 feedback을 함께 저장 (라벨은 없음)
    feedback_by_id = {}
    for rec in picked:
        file = rec["file"]
        rq2_rec = rq2_records[file]
        c_cond = rq2_rec["conditions"]["B_no_verify"]
        triplet = {"A": rec["condition_a"]["feedback"], "B": rec["condition_b"]["feedback"], "C": c_cond["feedback"]}
        for cond_label, fb in triplet.items():
            feedback_by_id[f"{Path(file).stem}_{cond_label}"] = fb

    for item in blind_items:
        item["feedback"] = feedback_by_id[item["item_id"]]

    rng.shuffle(blind_items)  # 조건 순서가 드러나지 않도록 섞음

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    blind_path = out_dir_path / "cross_check_blind.jsonl"
    key_path = out_dir_path / "cross_check_key.jsonl"

    with open(blind_path, "w", encoding="utf-8") as f:
        for item in blind_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    with open(key_path, "w", encoding="utf-8") as f:
        for item in key_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[표본추출] 총 {len(blind_items)}건 (essay {len(picked)} x 조건 3)")
    print(f"[표본추출] 블라인드 입력 -> {blind_path}")
    print(f"[표본추출] 정답지(gemini 점수) -> {key_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gemini vs 2차 모델 교차검증용 블라인드 표본 추출")
    parser.add_argument("--rq1", default="mafs/evaluate/results/rq1_200.jsonl")
    parser.add_argument("--rq2", default="mafs/evaluate/results/rq2_200.jsonl")
    parser.add_argument("--n_essays", type=int, default=15, help="essay 개수 (x3조건 = 전체 건수)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out_dir", default="mafs/evaluate/results")
    args = parser.parse_args()
    main(args.rq1, args.rq2, args.n_essays, args.seed, args.out_dir)

"""RQ1·RQ2·RQ3 SPSS 분석용 CSV 내보내기.

실행 예시:
    python mafs/evaluate/export_csv.py \
        --rq1 mafs/evaluate/results/rq1_v4.jsonl \
        --rq2 mafs/evaluate/results/rq2_v4.jsonl \
        --out_dir mafs/evaluate/results/csv
"""

import sys
import csv
import json
import argparse
from pathlib import Path

CRITERIA = ["C1", "C2", "C3", "C4", "C5", "M1", "M2", "M3", "M4", "M5"]

SCHOOL_LEVEL = {
    "초5": "초등", "초6": "초등",
    "중1": "중학", "중2": "중학", "중3": "중학",
}


def _scores(record: dict, cond: str) -> dict:
    return record[cond].get("scores") or {}


def export_rq1(path: str, out_dir: Path) -> None:
    """RQ1: MAFS vs Baseline 쌍대 비교용 CSV.

    주 지표  : score_total (Wilcoxon)
    보조 지표 : score_trigger, 기준별 충족률
    """
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        a = _scores(r, "condition_a")
        b = _scores(r, "condition_b")
        if not a or not b:
            continue

        row = {
            "file":    r.get("file", ""),
            "grade":   r.get("grade", ""),
            "subject": r.get("subject", ""),
            "school_level": SCHOOL_LEVEL.get(r.get("grade", ""), ""),
            "purpose": r.get("purpose", ""),
            # 주 지표
            "mafs_total":    a.get("score_total"),
            "base_total":    b.get("score_total"),
            # 보조 지표
            "mafs_trigger":  a.get("score_trigger"),
            "base_trigger":  b.get("score_trigger"),
            "mafs_ref":      a.get("score_ref"),
            "base_ref":      b.get("score_ref"),
        }
        for c in CRITERIA:
            row[f"mafs_{c}"] = a.get(c)
            row[f"base_{c}"] = b.get(c)
        rows.append(row)

    _write(out_dir / "rq1_spss.csv", rows)
    print(f"[RQ1] {len(rows)}건 → {out_dir / 'rq1_spss.csv'}")


def export_rq2(path: str, out_dir: Path, rq1_path: str | None = None) -> None:
    """RQ2: MAFS 완전판 vs 검증 제거 쌍대 비교용 CSV.

    주 지표  : score_trigger (Wilcoxon)
    보조 지표 : score_ref (간접 효과 확인)
    rq2_34.jsonl 구조: conditions.A_mafs_full / conditions.B_no_verify
    rq1_path 지정 시 verify_rounds 컬럼 추가 (subgroup analysis용)
    """
    # rq1에서 verify_rounds 로드 (파일명 기준 매핑)
    vr_map: dict[str, int] = {}
    if rq1_path:
        for line in Path(rq1_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            vr_map[rec.get("file", "")] = rec.get("verify_rounds", 0)

    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        conds = r.get("conditions", {})
        a = (conds.get("A_mafs_full") or {}).get("scores") or {}
        b = (conds.get("B_no_verify")  or {}).get("scores") or {}
        if not a or not b:
            continue

        fname = r.get("file", "")
        purpose = (conds.get("A_mafs_full") or {}).get("purpose", "") or r.get("purpose", "")
        row = {
            "file":    fname,
            "grade":   r.get("grade", ""),
            "subject": r.get("subject", ""),
            "school_level": SCHOOL_LEVEL.get(r.get("grade", ""), ""),
            "purpose": purpose,
            "verify_rounds": vr_map.get(fname, ""),
            # 주 지표
            "mafs_trigger":     a.get("score_trigger"),
            "noverify_trigger": b.get("score_trigger"),
            # 보조 지표
            "mafs_ref":         a.get("score_ref"),
            "noverify_ref":     b.get("score_ref"),
            "mafs_total":       a.get("score_total"),
            "noverify_total":   b.get("score_total"),
        }
        for c in CRITERIA:
            row[f"mafs_{c}"]     = a.get(c)
            row[f"noverify_{c}"] = b.get(c)
        rows.append(row)

    _write(out_dir / "rq2_spss.csv", rows)
    print(f"[RQ2] {len(rows)}건 → {out_dir / 'rq2_spss.csv'}")


EXPERT_ITEMS = [
    "task_1",
    "content_1", "content_2", "content_3",
    "organization_1", "organization_2",
    "expression_1", "expression_2",
]
# 8항목 × 1~5점 → 합계 범위 8~40
EXPERT_MIN, EXPERT_MAX = 8, 40


def _expert_scores(label_root: Path, fname: str) -> dict | None:
    """라벨링 JSON에서 전문가 점수를 추출한다.

    반환: {
        "expert_total": float,   # 8항목 × 2평균 합계 (8~40)
        "expert_norm":  float,   # (total-8)/32 → 0~1
    }
    파일 없으면 None.
    """
    stem = Path(fname).stem  # 확장자 제거
    # TL_ 폴더 전체 탐색 (폴더가 어느 것인지 모르므로)
    for tl_folder in label_root.iterdir():
        if not tl_folder.is_dir():
            continue
        json_path = tl_folder / f"{stem}.json"
        if not json_path.exists():
            continue
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        analytic = data.get("score", {}).get("personal", {}).get("analytic", {})
        total = 0.0
        found = 0
        for item in EXPERT_ITEMS:
            scores = analytic.get(item, {}).get("score")
            if scores:
                total += sum(scores) / len(scores)
                found += 1
        if found == 0:
            return None
        # 찾은 항목 수가 8개 미만이면 비례 보정
        if found < len(EXPERT_ITEMS):
            total = total * len(EXPERT_ITEMS) / found
        norm = (total - EXPERT_MIN) / (EXPERT_MAX - EXPERT_MIN)
        return {"expert_total": round(total, 4), "expert_norm": round(norm, 4)}
    return None


def export_rq3(path: str, out_dir: Path, label_root: str | None = None) -> None:
    """RQ3: 교과×학년 집단 비교용 CSV (MAFS 완전판만).

    주 지표  : score_total (Two-way ANOVA)
    Y 지표   : expert_norm - llm_norm (학년·교과별 일관성 검증)
    label_root 지정 시 AI Hub 전문가 점수(expert_total, expert_norm, gap_y) 추가.
    """
    label_path = Path(label_root) if label_root else None
    missing_expert = 0

    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        a = _scores(r, "condition_a")
        if not a:
            continue

        grade = r.get("grade", "")
        subject = r.get("subject", "")
        school_level = SCHOOL_LEVEL.get(grade, "")
        score_total = a.get("score_total")

        row = {
            "file":         r.get("file", ""),
            "grade":        grade,
            "subject":      subject,
            "school_level": school_level,
            "combination":  f"{subject}×{grade}",
            "purpose":      r.get("purpose", ""),
            "score_total":    score_total,
            "score_trigger":  a.get("score_trigger"),
            "score_ref":      a.get("score_ref"),
        }
        for c in CRITERIA:
            row[c] = a.get(c)

        # 전문가 점수 추가 (--label_root 지정 시)
        if label_path:
            exp = _expert_scores(label_path, r.get("file", ""))
            if exp:
                llm_norm = round(score_total / 20, 4) if score_total is not None else None
                gap_y = round(exp["expert_norm"] - llm_norm, 4) if llm_norm is not None else None
                row["expert_total"] = exp["expert_total"]
                row["expert_norm"]  = exp["expert_norm"]
                row["llm_norm"]     = llm_norm
                row["gap_y"]        = gap_y  # Y = 전문가_정규화 - LLM판사_정규화
            else:
                row["expert_total"] = None
                row["expert_norm"]  = None
                row["llm_norm"]     = None
                row["gap_y"]        = None
                missing_expert += 1

        rows.append(row)

    _write(out_dir / "rq3_spss.csv", rows)
    print(f"[RQ3] {len(rows)}건 → {out_dir / 'rq3_spss.csv'}")
    if label_path:
        matched = len(rows) - missing_expert
        print(f"  전문가 점수 매칭: {matched}/{len(rows)}건")


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        print(f"  (데이터 없음: {path})")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RQ별 Jamovi용 CSV 내보내기")
    parser.add_argument("--rq1", default=None)
    parser.add_argument("--rq2", default=None)
    parser.add_argument("--rq3", default=None)
    parser.add_argument("--label_root", default=None, help="AI Hub 라벨링데이터 폴더 경로 (TL_ 폴더 상위)")
    parser.add_argument("--out_dir", default="mafs/evaluate/results/csv")
    args = parser.parse_args()

    out = Path(args.out_dir)
    if args.rq1: export_rq1(args.rq1, out)
    if args.rq2: export_rq2(args.rq2, out, rq1_path=args.rq1)
    if args.rq3: export_rq3(args.rq3, out, label_root=args.label_root)
    if not any([args.rq1, args.rq2, args.rq3]):
        print("--rq1 / --rq2 / --rq3 중 하나 이상을 지정하세요.")

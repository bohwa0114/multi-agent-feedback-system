"""AI Hub 전문가 피드백 데이터 추출 파이프라인.

초5~중3 국어·사회·과학 전체 데이터(12개 폴더)를 대상으로 한다.

Training 폴더의 JSON 파일에서 에세이·지시문·학년·도메인별 피드백 텍스트·점수를
추출하여 feedback_db.jsonl에 저장한다.

출력 스키마 (1줄 = 에세이 1개):
{
    "file": "파일명",
    "grade": "중2",
    "purpose": "설명",
    "prompt": "과제 지시문 텍스트",
    "essay": "학생 에세이 텍스트",
    "domains": {
        "task": {
            "feedbacks": ["피드백1", ...],          # 항목별 피드백 텍스트 목록
            "feedback_combined": "합친 피드백",      # 항목 전체를 하나로 이어붙인 텍스트
            "total_syllables": 101,                  # 피드백 총 글자 수
            "weight": 0.139,                         # 전체 피드백 대비 비율
            "avg_score": 4.0                         # 두 평가자 점수 평균
        },
        "content":      { ... },
        "organization": { ... },
        "expression":   { ... }
    }
}

실행 (MISCA/ 루트에서, 전체 12개 폴더):
    python mafs/data/feedback_extractor.py \\
        --data_dir "26.논술형_글쓰기_평가_데이터/3.개방데이터/1.데이터/Training/02.라벨링데이터" \\
        --output   mafs/data/feedback_db.jsonl

특정 폴더만 처리:
    python mafs/data/feedback_extractor.py \\
        --data_dir "26.논술형_글쓰기_평가_데이터/3.개방데이터/1.데이터/Training/02.라벨링데이터" \\
        --grade_folders TL_3._중1_1._국어 TL_4._중2_1._국어 TL_5._중3_1._국어 \\
        --output   mafs/data/feedback_db.jsonl
"""

import json
import statistics
from pathlib import Path


DOMAIN_PREFIXES = {
    "task":         "task_",
    "content":      "content_",
    "organization": "organization_",
    "expression":   "expression_",
}


# ──────────────────────────────────────────
# 단일 파일 처리
# ──────────────────────────────────────────

def extract_record(data: dict, filename: str) -> dict | None:
    """
    JSON 1개에서 학습에 필요한 모든 정보를 추출.
    analytic 피드백이 없으면 None 반환.
    """
    try:
        essay = data["essay_answer"]["text"].strip()
        prompt = data["essay_question"]["prompt"].strip()
        grade = data["essay_question"].get("grade", "")
        purpose = data["essay_question"].get("purpose", "")
        analytic = data["score"]["personal"]["analytic"]
    except (KeyError, TypeError):
        return None

    if not essay or not prompt:
        return None

    domains: dict[str, dict] = {}
    total_syllables = 0

    for domain, prefix in DOMAIN_PREFIXES.items():
        feedbacks: list[str] = []
        syllables = 0
        all_scores: list[float] = []

        for key, item in analytic.items():
            if not key.startswith(prefix) or not isinstance(item, dict):
                continue
            fb_text = item.get("feedback", "").strip()
            if fb_text:
                feedbacks.append(fb_text)
            syllables += item.get("len_syllable", 0)
            scores = item.get("score", [])
            if isinstance(scores, list):
                all_scores.extend(scores)

        domains[domain] = {
            "feedbacks":        feedbacks,
            "feedback_combined": " ".join(feedbacks),
            "total_syllables":  syllables,
            "weight":           0.0,   # 정규화 후 채움
            "avg_score":        round(statistics.mean(all_scores), 2) if all_scores else None,
        }
        total_syllables += syllables

    # 도메인별 분량 비율 정규화
    if total_syllables > 0:
        for domain in domains:
            domains[domain]["weight"] = round(
                domains[domain]["total_syllables"] / total_syllables, 4
            )

    # 유효한 피드백이 하나도 없으면 스킵
    if all(not d["feedback_combined"] for d in domains.values()):
        return None

    return {
        "file":    filename,
        "grade":   grade,
        "purpose": purpose,
        "prompt":  prompt,
        "essay":   essay,
        "domains": domains,
    }


# ──────────────────────────────────────────
# 전체 데이터 추출
# ──────────────────────────────────────────

def extract_all(
    data_dir: str | Path,
    output_path: str | Path,
    grade_folders: list[str] | None = None,
) -> int:
    """
    data_dir 하위 JSON을 처리하여 output_path(JSONL)에 저장.

    grade_folders: 처리할 하위 폴더명 목록. None이면 전체 탐색.
                   예: ["TL_3._중1_1._국어", "TL_4._중2_1._국어", "TL_5._중3_1._국어"]
    반환: 저장된 레코드 수
    """
    data_dir = Path(data_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if grade_folders:
        json_files = []
        for folder in grade_folders:
            target = data_dir / folder
            if not target.exists():
                print(f"[경고] 폴더 없음: {target}", flush=True)
                continue
            json_files.extend(target.glob("**/*.json"))
        json_files = sorted(json_files)
    else:
        json_files = sorted(data_dir.glob("**/*.json"))
    n_ok = 0
    n_skip = 0

    with open(output_path, "w", encoding="utf-8") as out:
        for path in json_files:
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                n_skip += 1
                continue

            record = extract_record(data, path.name)
            if record is None:
                n_skip += 1
                continue

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_ok += 1

            if n_ok % 1000 == 0:
                print(f"  {n_ok}건 처리 중 ...", flush=True)

    return n_ok


# ──────────────────────────────────────────
# 간단한 통계 출력
# ──────────────────────────────────────────

def print_summary(output_path: str | Path) -> None:
    """저장된 JSONL을 읽어 간단한 통계를 출력."""
    output_path = Path(output_path)
    records = []
    with open(output_path, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    n = len(records)
    print(f"\n총 레코드: {n}건")

    # 학년 분포
    from collections import Counter
    grade_dist = Counter(r["grade"] for r in records)
    print("\n학년 분포:")
    for grade, cnt in sorted(grade_dist.items()):
        print(f"  {grade}: {cnt}건")

    # 목적 분포
    purpose_dist = Counter(r["purpose"] for r in records)
    print("\n글쓰기 목적 분포:")
    for purpose, cnt in sorted(purpose_dist.items()):
        print(f"  {purpose}: {cnt}건")

    # 영역별 평균 가중치
    print("\n영역별 평균 가중치 (전문가 피드백 분량 비율):")
    for domain in DOMAIN_PREFIXES:
        weights = [r["domains"][domain]["weight"] for r in records]
        avg = statistics.mean(weights)
        std = statistics.stdev(weights) if len(weights) > 1 else 0.0
        print(f"  {domain:12s}: {avg*100:.1f}%  (±{std*100:.1f}%)")

    # 영역별 평균 점수
    print("\n영역별 평균 점수 (1~5):")
    for domain in DOMAIN_PREFIXES:
        scores = [
            r["domains"][domain]["avg_score"]
            for r in records
            if r["domains"][domain]["avg_score"] is not None
        ]
        if scores:
            print(f"  {domain:12s}: {statistics.mean(scores):.2f}")


# ──────────────────────────────────────────
# CLI 실행
# ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="AI Hub 전문가 피드백 JSON → feedback_db.jsonl 추출"
    )
    parser.add_argument(
        "--data_dir",
        required=True,
        help="라벨링 JSON 루트 폴더 경로",
    )
    parser.add_argument(
        "--grade_folders",
        nargs="+",
        default=None,
        help="처리할 하위 폴더명 목록 (기본: None → 전체 탐색)",
    )
    parser.add_argument(
        "--output",
        default="mafs/data/feedback_db.jsonl",
        help="출력 JSONL 파일 경로",
    )
    args = parser.parse_args()

    print(f"[추출] 대상 폴더: {args.grade_folders}", flush=True)
    n = extract_all(args.data_dir, args.output, grade_folders=args.grade_folders)
    print(f"[완료] {n}건 저장 → {args.output}")

    print_summary(args.output)

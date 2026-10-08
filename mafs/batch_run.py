"""MAFS 배치 처리 스크립트.

AI Hub 논술형 글쓰기 평가 데이터를 일괄 처리하여 결과를 JSONL로 저장한다.

입력 데이터 선택 원칙:
  - 연구 평가(RQ1~RQ3): CSV 원천 데이터(01.원천데이터/TS_...) 사용.
    전문가 피드백이 없어 오염 없이 순수 입력으로 사용 가능.
  - 학습 데이터 구축 전용: JSON 라벨링 데이터(02.라벨링데이터/TL_...) 사용.
    few_shot_builder.py / feedback_extractor.py 에서만 참조.

실행 예시 (MISCA/ 루트에서):
    # CSV 원천 데이터 폴더 (기본, 권장)
    python mafs/batch_run.py \\
        --input_dir "26.논술형_글쓰기_평가_데이터/3.개방데이터/1.데이터/Training/01.원천데이터/TS_3._중1_1._국어" \\
        --output mafs/results/results_중1국어.jsonl \\
        --sample 10 --seed 42

    # JSON 라벨링 데이터 폴더 (학습 데이터 검증 목적에만 사용)
    python mafs/batch_run.py \\
        --input_dir "26.논술형_글쓰기_평가_데이터/.../TL_3._중1_1._국어" \\
        --ext json \\
        --output mafs/results/results.jsonl

출력 JSONL 스키마 (1줄 = 1건):
{
    "file":           "14-2-M1-N-0A-E-0041.csv",
    "grade":          "중1",
    "subject":        "국어",
    "purpose":        "설명",
    "prompt":         "과제 지시문 텍스트",
    "essay":          "학생 에세이 텍스트",
    "diagnosis":      "취약 신호 진단 결과",
    "feedback":       "최종 피드백 텍스트",
    "verify_rounds":  1,
    "final_criteria": {"C1": "✓", "C2": "✓", ...},
    "status":         "ok" | "error",
    "error":          null | "에러 메시지"
}
"""

import sys
import asyncio
import json
import traceback
from pathlib import Path

MAFS_DIR = Path(__file__).parent
if str(MAFS_DIR) not in sys.path:
    sys.path.insert(0, str(MAFS_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from pipeline import run_mafs
from data.loader import load_essay_from_json, parse_essay_csv, extract_subject_from_folder


# ──────────────────────────────────────────
# 파일 파싱
# ──────────────────────────────────────────

def _load_csv(path: Path) -> dict:
    """CSV 원천 데이터 파일을 읽어 {prompt, grade, subject, purpose, essay} 반환.

    subject는 CSV 내부에 없으므로 부모 폴더명(TS_1._초5_1._국어 등)에서 추출한다.
    purpose는 CSV에 없으므로 빈 문자열로 반환 — DIAGNOSIS 단계에서 자동 판단.
    """
    try:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp949", errors="replace")
    except Exception as e:
        raise ValueError(f"파일 읽기 실패: {e}") from e

    parsed = parse_essay_csv(text)
    if not parsed["essay"]:
        raise ValueError("학생 답변을 찾을 수 없습니다")
    if not parsed["prompt"]:
        raise ValueError("글쓰기 지시문을 찾을 수 없습니다")

    parsed["subject"] = extract_subject_from_folder(path.parent.name)
    parsed["purpose"] = ""
    return parsed


def _load_json(path: Path) -> dict:
    """AI Hub 라벨링 JSON을 읽어 {prompt, grade, subject, purpose, essay} 반환."""
    data = load_essay_from_json(str(path))
    result = {
        "prompt":   data["prompt"],
        "grade":    data["grade"],
        "subject":  data["subject"],
        "purpose":  data.get("purpose", ""),
        "essay":    data["essay_text"],
    }
    if not result["essay"]:
        raise ValueError("에세이 텍스트가 비어 있습니다")
    if not result["prompt"]:
        raise ValueError("과제 지시문이 비어 있습니다")
    return result


# ──────────────────────────────────────────
# 단건 처리
# ──────────────────────────────────────────

async def _process_one(path: Path, ext: str) -> dict:
    """파일 1건을 처리해 결과 딕셔너리 반환."""
    if ext == "csv":
        parsed = _load_csv(path)
    else:
        parsed = _load_json(path)

    result = await run_mafs(
        essay=parsed["essay"],
        prompt=parsed["prompt"],
        grade=parsed["grade"],
        purpose=parsed.get("purpose", ""),
    )

    return {
        "file":           path.name,
        "grade":          parsed["grade"],
        "subject":        parsed.get("subject", ""),
        "purpose":        result.purpose,
        "prompt":         parsed["prompt"],
        "essay":          parsed["essay"],
        "diagnosis":      result.diagnosis,
        "feedback":       result.feedback,
        "verify_rounds":  result.verify_rounds,
        "final_criteria": result.final_criteria,
        "status":         "ok",
        "error":          None,
    }


# ──────────────────────────────────────────
# 배치 실행
# ──────────────────────────────────────────

async def batch_run(
    input_dir: str | Path,
    output_path: str | Path,
    ext: str = "csv",
    limit: int | None = None,
    sample: int | None = None,
    seed: int = 42,
) -> None:
    """input_dir의 파일을 처리해 output_path(JSONL)에 저장.

    Args:
        input_dir:   입력 파일이 있는 디렉터리
        output_path: 결과를 저장할 JSONL 파일 경로
        ext:         처리할 파일 확장자 ("csv" 또는 "json")
        limit:       최대 처리 건수 — 정렬 후 앞에서부터 (None이면 전부)
        sample:      무작위 샘플 건수 — 전체에서 무작위 추출 (limit과 함께 쓰면 sample 우선)
        seed:        sample 재현성을 위한 랜덤 시드 (기본 42)
    """
    import random as _random

    input_dir = Path(input_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob(f"**/*.{ext}"))
    if sample:
        rng = _random.Random(seed)
        files = rng.sample(files, min(sample, len(files)))
        files = sorted(files)          # 샘플 후 정렬해 재현 가능한 순서 유지
    elif limit:
        files = files[:limit]

    total = len(files)
    if total == 0:
        print(f"[BATCH] {input_dir} 에서 .{ext} 파일을 찾을 수 없습니다.", flush=True)
        return

    print(f"[BATCH] 총 {total}건 처리 시작 → {output_path}", flush=True)
    n_ok = n_err = 0

    with open(output_path, "w", encoding="utf-8") as out:
        for i, path in enumerate(files, 1):
            print(f"\n[BATCH] ({i}/{total}) {path.name}", flush=True)
            try:
                record = await _process_one(path, ext)
                n_ok += 1
            except Exception as e:
                tb = traceback.format_exc()
                print(f"[BATCH] ✗ 오류 — {path.name}\n{tb}", flush=True)
                record = {
                    "file":           path.name,
                    "grade":          "",
                    "subject":        "",
                    "purpose":        "",
                    "prompt":         "",
                    "essay":          "",
                    "diagnosis":      "",
                    "feedback":       "",
                    "verify_rounds":  0,
                    "final_criteria": {},
                    "status":         "error",
                    "error":          str(e),
                }
                n_err += 1

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()

    print(f"\n[BATCH] 완료 — 성공 {n_ok}건 / 오류 {n_err}건 → {output_path}", flush=True)


# ──────────────────────────────────────────
# CLI
# ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MAFS 배치 처리")
    parser.add_argument(
        "--input_dir", required=True,
        help="처리할 CSV 또는 JSON 파일이 있는 폴더",
    )
    parser.add_argument(
        "--output", default="mafs/results/results.jsonl",
        help="결과 JSONL 파일 경로 (기본: mafs/results/results.jsonl)",
    )
    parser.add_argument(
        "--ext", default="csv", choices=["csv", "json"],
        help="처리할 파일 확장자 (기본: csv)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="최대 처리 건수 — 정렬 후 앞에서부터 (기본: 전부)",
    )
    parser.add_argument(
        "--sample", type=int, default=None,
        help="무작위 샘플 건수 — 전체에서 무작위 추출 (limit보다 우선)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="--sample 재현성을 위한 랜덤 시드 (기본: 42)",
    )
    args = parser.parse_args()

    asyncio.run(batch_run(
        input_dir=args.input_dir,
        output_path=args.output,
        ext=args.ext,
        sample=args.sample,
        seed=args.seed,
        limit=args.limit,
    ))

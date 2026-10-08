"""RQ1 평가 스크립트 — 교육적 요소 유무에 따른 피드백 품질 비교.

비교 조건:
  A. MAFS      : MISCA 루브릭·검증 기준·가중치 진단·도메인 도구를 포함한 전체 시스템
  B. Baseline  : "교사 입장에서 피드백을 작성해 주세요" 수준의 단순 지침

실행 예시 (MISCA/ 루트에서):
    # RQ1 전체 실행 (MAFS + Baseline, 34건)
    python mafs/evaluate/rq1_instruction.py \\
        --file_list mafs/evaluate/results/sampled_rq12.txt \\
        --output mafs/evaluate/results/rq1_34.jsonl

    # RQ3용 MAFS만 실행 (Baseline 생략, 200건)
    python mafs/evaluate/rq1_instruction.py \\
        --file_list mafs/evaluate/results/sampled_rq3.txt \\
        --mafs_only \\
        --output mafs/evaluate/results/rq3_200.jsonl

출력 JSONL 스키마 (1줄 = 1건):
  기본 모드:
    {"file": "...", "grade": "중1", "subject": "국어", "purpose": "설명문",
     "synthesis_0": "...", "verify_rounds": 1,
     "condition_a": {"feedback": "...", "scores": {...}},
     "condition_b": {"feedback": "...", "scores": {...}}}
  --mafs_only 모드 (RQ3용):
    {"file": "...", "grade": "중1", "subject": "국어", "purpose": "설명문",
     "synthesis_0": "...", "verify_rounds": 1,
     "condition_a": {"feedback": "...", "scores": {...}}}
"""

import sys
import asyncio
import json
import argparse
import random
import traceback
from pathlib import Path

MAFS_DIR = Path(__file__).parent.parent
if str(MAFS_DIR) not in sys.path:
    sys.path.insert(0, str(MAFS_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(MAFS_DIR / ".env")

from pipeline import run_mafs_synthesis, run_mafs_verify
from data.loader import parse_essay_csv, extract_subject_from_folder
from evaluate.llm_judge import score_feedback, print_score_summary
from evaluate.stats import paired_comparison, print_paired_result
from config import MODEL

import os
from google import genai
from google.genai import types

# ─────────────────────────────────────────────────
# Baseline 지침 — 교육 이론 없는 단순 요청
# ─────────────────────────────────────────────────

BASELINE_PROMPT = """\
다음 학생이 제출한 글에 대해 피드백을 작성해 주세요.
"""


async def _generate_baseline(essay: str, prompt: str, grade: str) -> str:
    """단순 지침으로 피드백을 생성한다."""
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    user_msg = f"[과제 지시문]\n{prompt}\n\n[학생 학년]\n{grade}\n\n[학생 글쓰기]\n{essay}"
    resp = await client.aio.models.generate_content(
        model=MODEL,
        contents=user_msg,
        config=types.GenerateContentConfig(system_instruction=BASELINE_PROMPT),
    )
    return resp.text or ""


def _load_csv(path: Path) -> dict:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949", errors="replace")
    parsed = parse_essay_csv(text)
    parsed["subject"] = extract_subject_from_folder(path.parent.name)
    parsed["purpose"] = ""
    return parsed


async def _process_one(
    path: Path,
    mafs_only: bool = False,
    reuse_mafs: dict | None = None,
    reuse_baseline: dict | None = None,
) -> dict | None:
    parsed = _load_csv(path)
    essay, prompt, grade = parsed["essay"], parsed["prompt"], parsed["grade"]

    if reuse_mafs is not None:
        # Step 2(rq3_200.jsonl)에서 MAFS 결과 재사용 — API 호출 없음
        feedback_a    = reuse_mafs["condition_a"]["feedback"]
        scores_a      = reuse_mafs["condition_a"]["scores"]
        synthesis_0   = reuse_mafs.get("synthesis_0", "")
        verify_rounds = reuse_mafs.get("verify_rounds", 0)
        purpose       = reuse_mafs.get("purpose", "")
        print(f"  [A] MAFS 재사용 (Step 2 결과)", flush=True)
    else:
        print(f"  [A] MAFS 실행 중...", flush=True)
        try:
            sr = await run_mafs_synthesis(essay=essay, prompt=prompt, grade=grade)
            result_a = await run_mafs_verify(sr)
            feedback_a    = result_a.feedback
            synthesis_0   = sr.synthesis
            purpose       = result_a.purpose
            verify_rounds = result_a.verify_rounds
        except Exception as e:
            print(f"  [A] 오류: {e}", flush=True)
            return None
        print(f"  [JUDGE-A] 채점 중...", flush=True)
        scores_a = await score_feedback(essay, prompt, feedback_a, grade)

    record: dict = {
        "file":          path.name,
        "grade":         grade,
        "subject":       parsed["subject"],
        "purpose":       purpose or parsed.get("purpose", ""),
        "prompt":        prompt,
        "essay":         essay,
        "synthesis_0":   synthesis_0,
        "verify_rounds": verify_rounds,
        "condition_a":   {"feedback": feedback_a, "scores": scores_a},
    }

    if mafs_only:
        return record

    # Baseline 실행 (RQ1용)
    if reuse_baseline is not None:
        feedback_b = reuse_baseline.get("feedback", "")
        print(f"  [B] Baseline 재사용", flush=True)
    else:
        print(f"  [B] Baseline 실행 중...", flush=True)
        try:
            feedback_b = await _generate_baseline(essay, prompt, grade)
        except Exception as e:
            print(f"  [B] 오류: {e}", flush=True)
            return None

    print(f"  [JUDGE-B] 채점 중...", flush=True)
    scores_b = await score_feedback(essay, prompt, feedback_b, grade)
    record["condition_b"] = {"feedback": feedback_b, "scores": scores_b}
    return record


async def main(
    input_dir: str | None,
    output: str,
    sample: int | None,
    seed: int,
    file_list: str | None = None,
    reuse_rq1: str | None = None,
    mafs_only: bool = False,
    reuse_mafs: str | None = None,
) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if file_list:
        files = [Path(p.strip()) for p in Path(file_list).read_text(encoding="utf-8").splitlines() if p.strip()]
    elif input_dir:
        input_path = Path(input_dir)
        files = sorted(input_path.glob("**/*.csv"))
        if sample:
            rng = random.Random(seed)
            files = sorted(rng.sample(files, min(sample, len(files))))
    else:
        print("[RQ1] --input_dir 또는 --file_list 중 하나가 필요합니다.", flush=True)
        return

    if not files:
        print(f"[RQ1] CSV 파일 없음", flush=True)
        return

    mode_label = "MAFS only (RQ3)" if mafs_only else "MAFS + Baseline (RQ1)"
    print(f"[RQ1] 모드: {mode_label}", flush=True)

    # Step 2(rq3_200.jsonl)에서 MAFS 결과 캐시 로드
    mafs_cache: dict[str, dict] = {}
    if reuse_mafs:
        for line in Path(reuse_mafs).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            mafs_cache[rec["file"]] = rec
        print(f"[RQ1] MAFS 결과 {len(mafs_cache)}건 로드 완료 (Step 2 재사용)", flush=True)

    # 기존 RQ1 결과에서 Baseline 피드백 재사용
    baseline_cache: dict[str, dict] = {}
    if reuse_rq1 and not mafs_only:
        for line in Path(reuse_rq1).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if "condition_b" in rec:
                baseline_cache[rec["file"]] = rec["condition_b"]
        print(f"[RQ1] Baseline 피드백 {len(baseline_cache)}건 로드 완료", flush=True)

    # 이미 처리된 파일 이름 수집 (resume 지원)
    done_files: set[str] = set()
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    done_files.add(rec.get("file", ""))
                except json.JSONDecodeError:
                    pass

    pending = [p for p in files if p.name not in done_files]
    if done_files:
        print(f"[RQ1] 이미 처리된 {len(done_files)}건 건너뜀. 남은 {len(pending)}건 처리.", flush=True)

    print(f"[RQ1] {len(files)}건 처리 시작 → {output_path}", flush=True)
    scores_a_all, scores_b_all = [], []

    # 기존 결과 로드하여 통계에 포함
    if output_path.exists() and done_files:
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    scores_a_all.append(rec["condition_a"]["scores"])
                    if "condition_b" in rec:
                        scores_b_all.append(rec["condition_b"]["scores"])
                except (json.JSONDecodeError, KeyError):
                    pass

    with open(output_path, "a", encoding="utf-8") as out:
        for i, path in enumerate(pending, len(done_files) + 1):
            print(f"\n[RQ1] ({i}/{len(files)}) {path.name}", flush=True)
            try:
                reuse_b = baseline_cache.get(path.name) if not mafs_only else None
                reuse_m = mafs_cache.get(path.name) if mafs_cache else None
                record = await _process_one(
                    path, mafs_only=mafs_only,
                    reuse_mafs=reuse_m, reuse_baseline=reuse_b,
                )
                if record:
                    scores_a_all.append(record["condition_a"]["scores"])
                    if "condition_b" in record:
                        scores_b_all.append(record["condition_b"]["scores"])
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()
            except Exception:
                print(traceback.format_exc(), flush=True)

    print_score_summary("A. MAFS", scores_a_all)
    if not mafs_only and scores_b_all:
        print_score_summary("B. Baseline (단순 지침)", scores_b_all)
        print("\n\n[RQ1] 통계 분석: 대응표본 t-검정")
        for metric in ("score_total", "score_trigger", "score_ref"):
            result = paired_comparison(
                scores_a_all, scores_b_all,
                label_a="A.MAFS", label_b="B.Baseline",
                metric=metric,
            )
            print_paired_result(result)

    print(f"\n[RQ1] 완료 → {output_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RQ1 평가: 교육적 지침 유무 비교 / RQ3용 MAFS 전용 실행")
    parser.add_argument("--input_dir", default=None, help="CSV 원천 데이터 폴더")
    parser.add_argument("--file_list", default=None, help="sample_dataset.py가 생성한 파일 목록 텍스트")
    parser.add_argument("--output", default="mafs/evaluate/results/rq1_results.jsonl")
    parser.add_argument("--sample", type=int, default=None, help="무작위 샘플 건수 (--input_dir 사용 시)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reuse_rq1", default=None, help="기존 RQ1 결과에서 Baseline 피드백 재사용")
    parser.add_argument("--mafs_only", action="store_true",
                        help="MAFS만 실행하고 Baseline 생략 (RQ3용 200건 실행 시 사용)")
    parser.add_argument("--reuse_mafs", default=None,
                        help="Step 2(rq3_200.jsonl)에서 MAFS 결과 재사용 — RQ1 Step 3에서 중복 실행 방지")
    args = parser.parse_args()
    asyncio.run(main(
        args.input_dir, args.output, args.sample, args.seed,
        args.file_list, args.reuse_rq1, args.mafs_only, args.reuse_mafs,
    ))

"""RQ2 평가 스크립트 — 검증 에이전트(critic) 유무에 따른 피드백 품질 비교.

비교 조건:
  A. mafs_full   : 다중 에이전트 + MISCA 검증 루프 + 도메인 도구 전체 (완전판)
  B. no_verify   : 동일한 다중 에이전트 + 도구, 검증 루프 없이 1회 합성 결과를 최종 출력

실행 예시 (MISCA/ 루트에서):
    python mafs/evaluate/rq2_design_elements.py \\
        --input_dir "26.논술형_글쓰기_평가_데이터/.../01.원천데이터/TS_3._중1_1._국어" \\
        --sample 10 --seed 42 \\
        --output mafs/evaluate/results/rq2_중1국어.jsonl
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

from pipeline import run_mafs, run_mafs_synthesis, run_mafs_verify
from data.loader import parse_essay_csv, extract_subject_from_folder
from evaluate.llm_judge import score_feedback, print_score_summary
from evaluate.stats import paired_comparison, print_paired_result


# ─────────────────────────────────────────────────
# 공용 도우미
# ─────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────
# 조건별 피드백 생성
# ─────────────────────────────────────────────────

CONDITION_LABELS = {
    "A_mafs_full": "A. MAFS 완전판 (검증 루프 포함)",
    "B_no_verify": "B. 검증 제거 (공유 합성 초안 그대로)",
}


# ─────────────────────────────────────────────────
# 단건 처리
# ─────────────────────────────────────────────────

async def _process_one(
    path: Path,
    reuse_a: dict | None = None,
) -> dict | None:
    parsed = _load_csv(path)
    essay, prompt, grade = parsed["essay"], parsed["prompt"], parsed["grade"]

    feedbacks = {}
    purposes  = {}

    if reuse_a is not None:
        # condition A: RQ1의 MAFS 피드백 + 점수 재사용
        feedbacks["A_mafs_full"] = reuse_a["a"].get("feedback")
        purposes["A_mafs_full"]  = reuse_a["a"].get("purpose", "")
        scores_a                 = reuse_a["a"].get("scores")
        print(f"  [A] RQ1 결과 재사용", flush=True)

        # condition B: RQ1의 synthesis_0 (검증 전 초안) → B만 새로 채점
        feedbacks["B_no_verify"] = reuse_a.get("synthesis_0", "")
        purposes["B_no_verify"]  = purposes["A_mafs_full"]
        print(f"  [B] RQ1 synthesis_0 재사용 — 채점 중...", flush=True)
        scores_b = await score_feedback(essay, prompt, feedbacks["B_no_verify"], grade) \
            if feedbacks.get("B_no_verify") else None
    else:
        # 공유 synthesis 설계: synthesis 한 번 실행 → B로 사용, A는 검증 루프 추가
        print(f"  [공유 synthesis] 실행 중...", flush=True)
        try:
            sr = await run_mafs_synthesis(essay=essay, prompt=prompt, grade=grade)
            feedbacks["B_no_verify"] = sr.synthesis
            purposes["B_no_verify"]  = sr.purpose
            print(f"  [A] 검증 루프 실행 중...", flush=True)
            result_a = await run_mafs_verify(sr)
            feedbacks["A_mafs_full"] = result_a.feedback
            purposes["A_mafs_full"]  = result_a.purpose
        except Exception as e:
            print(f"  [공유 synthesis] 오류: {e}", flush=True)
            return None

        async def _null():
            return None

        print(f"  [JUDGE] 채점 중...", flush=True)
        scores_a, scores_b = await asyncio.gather(
            score_feedback(essay, prompt, feedbacks["A_mafs_full"], grade) if feedbacks.get("A_mafs_full") else _null(),
            score_feedback(essay, prompt, feedbacks["B_no_verify"],  grade) if feedbacks.get("B_no_verify")  else _null(),
        )

    conditions_out = {
        "A_mafs_full": {"feedback": feedbacks["A_mafs_full"], "purpose": purposes["A_mafs_full"], "scores": scores_a},
        "B_no_verify":  {"feedback": feedbacks["B_no_verify"],  "purpose": purposes["B_no_verify"],  "scores": scores_b},
    }

    return {
        "file":       path.name,
        "grade":      grade,
        "subject":    parsed["subject"],
        "prompt":     prompt,
        "essay":      essay,
        "conditions": conditions_out,
    }


# ─────────────────────────────────────────────────
# 배치 실행
# ─────────────────────────────────────────────────

async def main(
    input_dir: str | None,
    output: str,
    sample: int | None,
    seed: int,
    file_list: str | None = None,
    reuse_rq1: str | None = None,
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
        print("[RQ2] --input_dir 또는 --file_list 중 하나가 필요합니다.", flush=True)
        return

    if not files:
        print(f"[RQ2] CSV 파일 없음", flush=True)
        return

    # RQ1 결과에서 condition A + synthesis_0 재활용
    rq1_cache: dict[str, dict] = {}
    if reuse_rq1:
        for line in Path(reuse_rq1).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            rq1_cache[rec["file"]] = {
                "a": rec["condition_a"],
                "synthesis_0": rec.get("synthesis_0", ""),
            }
        print(f"[RQ2] RQ1 결과 {len(rq1_cache)}건 로드 완료 (condition A + synthesis_0)", flush=True)


    # resume: 이미 처리된 파일 건너뜀
    done_files: set[str] = set()
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    done_files.add(json.loads(line)["file"])
                except (json.JSONDecodeError, KeyError):
                    pass
    if done_files:
        print(f"[RQ2] 이미 처리된 {len(done_files)}건 건너뜀", flush=True)

    pending = [p for p in files if p.name not in done_files]
    print(f"[RQ2] {len(files)}건 × 2조건 처리 시작 → {output_path}", flush=True)
    scores_a_all: list[dict] = []
    scores_b_all: list[dict] = []

    # 기존 결과 통계에 포함
    if output_path.exists() and done_files:
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    sc_a = rec["conditions"]["A_mafs_full"]["scores"]
                    sc_b = rec["conditions"]["B_no_verify"]["scores"]
                    if sc_a: scores_a_all.append(sc_a)
                    if sc_b: scores_b_all.append(sc_b)
                except (json.JSONDecodeError, KeyError):
                    pass

    with open(output_path, "a", encoding="utf-8") as out:
        for i, path in enumerate(pending, len(done_files) + 1):
            print(f"\n[RQ2] ({i}/{len(files)}) {path.name}", flush=True)
            try:
                reuse_a = rq1_cache.get(path.name)
                record = await _process_one(path, reuse_a=reuse_a)
                if record:
                    sc_a = record["conditions"]["A_mafs_full"]["scores"]
                    sc_b = record["conditions"]["B_no_verify"]["scores"]
                    if sc_a:
                        scores_a_all.append(sc_a)
                    if sc_b:
                        scores_b_all.append(sc_b)
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()
            except Exception:
                print(traceback.format_exc(), flush=True)

    print_score_summary(CONDITION_LABELS["A_mafs_full"], scores_a_all)
    print_score_summary(CONDITION_LABELS["B_no_verify"], scores_b_all)

    # ── 통계 검정 ──
    print("\n\n[RQ2] 통계 분석: 쌍대 Wilcoxon 부호 순위 검정")
    for metric in ("score_total", "score_trigger", "score_ref"):
        result = paired_comparison(
            scores_a_all, scores_b_all,
            label_a=CONDITION_LABELS["A_mafs_full"],
            label_b=CONDITION_LABELS["B_no_verify"],
            metric=metric,
        )
        print_paired_result(result)

    print(f"\n[RQ2] 완료 → {output_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RQ2 평가: 검증 에이전트 유무 비교")
    parser.add_argument("--input_dir", default=None, help="CSV 원천 데이터 폴더")
    parser.add_argument("--file_list", default=None, help="sample_dataset.py가 생성한 파일 목록 텍스트")
    parser.add_argument("--output", default="mafs/evaluate/results/rq2_results.jsonl")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reuse_rq1", default=None, help="RQ1 결과 JSONL에서 condition A 피드백 재활용")
    args = parser.parse_args()
    asyncio.run(main(args.input_dir, args.output, args.sample, args.seed, args.file_list, args.reuse_rq1))

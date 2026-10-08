"""배포 전 1회 실행: 전문가 피드백 데이터 → few-shot 컨텍스트 파일 생성.

생성 파일:
    mafs/data/manager_weight_context.json   — DIAGNOSIS_PROMPT 주입용 (목적별 가중치)
    mafs/data/few_shot_task.json            — 과제수행 에이전트 few-shot 예시
    mafs/data/few_shot_content.json         — 내용 에이전트 few-shot 예시
    mafs/data/few_shot_organization.json    — 조직 에이전트 few-shot 예시
    mafs/data/few_shot_expression.json      — 표현 에이전트 few-shot 예시

실행 (MISCA/ 루트에서):
    python mafs/data/few_shot_builder.py \\
        --db mafs/data/feedback_db.jsonl \\
        --output_dir mafs/data
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path


DOMAINS = ["task", "content", "organization", "expression"]
DOMAIN_KO = {
    "task":         "과제수행",
    "content":      "내용",
    "organization": "조직",
    "expression":   "표현",
}
PURPOSES = ["설명", "설득", "친교 및 정서"]

# few-shot 예시 선택 기준
MIN_FEEDBACK_CHARS = 80    # 너무 짧은 피드백 제외
MAX_FEEDBACK_CHARS = 450   # 너무 긴 피드백 제외
ESSAY_EXCERPT_LEN  = 220   # 에세이 앞부분 발췌 길이
N_EXAMPLES_PER_DOMAIN = 3  # 도메인당 최대 예시 수 (목적 1개당 1개 목표)
WEAK_SCORE_THRESHOLD = 3.0 # 취약 영역 판단 기준 (이하면 weak)


# ──────────────────────────────────────────
# 1. feedback_db.jsonl 로드
# ──────────────────────────────────────────

def load_db(db_path: str | Path) -> list[dict]:
    records = []
    with open(db_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ──────────────────────────────────────────
# 2. 매니저용: 목적 × 도메인별 가중치 통계
# ──────────────────────────────────────────

def build_weight_context(records: list[dict]) -> dict:
    """
    전체 / 목적별 / (목적 × 영역취약도)별 평균 가중치 계산.
    반환값 → manager_weight_context.json 으로 저장됨.
    """
    def avg_weights(recs: list[dict]) -> dict[str, float] | None:
        if not recs:
            return None
        return {
            d: round(statistics.mean(r["domains"][d]["weight"] for r in recs), 4)
            for d in DOMAINS
        }

    # 전체 평균
    overall = avg_weights(records)

    # 목적별 평균
    by_purpose: dict[str, dict] = {}
    purpose_groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        purpose_groups[r.get("purpose", "")].append(r)
    for purpose, recs in purpose_groups.items():
        w = avg_weights(recs)
        if w:
            by_purpose[purpose] = w

    # (목적 × 영역취약도)별 평균
    # "content가 weak(≤3)인 설명문에서 전문가는 각 영역에 얼마씩 썼나?"
    by_purpose_weak: dict[str, dict[str, dict]] = {}
    for purpose, p_recs in purpose_groups.items():
        by_purpose_weak[purpose] = {}
        for domain in DOMAINS:
            weak_recs = [
                r for r in p_recs
                if (r["domains"][domain]["avg_score"] or 99) <= WEAK_SCORE_THRESHOLD
            ]
            strong_recs = [
                r for r in p_recs
                if (r["domains"][domain]["avg_score"] or 0) > WEAK_SCORE_THRESHOLD
            ]
            by_purpose_weak[purpose][domain] = {
                "weak":   avg_weights(weak_recs),
                "strong": avg_weights(strong_recs),
                "n_weak": len(weak_recs),
                "n_strong": len(strong_recs),
            }

    return {
        "n_records": len(records),
        "overall": overall,
        "by_purpose": by_purpose,
        "by_purpose_weak_domain": by_purpose_weak,
    }


def build_diagnosis_context(context_path: str | Path) -> str:
    """
    manager_weight_context.json → DIAGNOSIS_PROMPT 앞에 붙일 문자열.
    파일 없으면 빈 문자열 반환 (기본 휴리스틱 fallback).
    """
    try:
        with open(context_path, encoding="utf-8") as f:
            ctx = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""

    if "overall" not in ctx:
        return ""

    n = ctx["n_records"]
    ow = ctx["overall"]

    # 전체 평균
    mean_line = " | ".join(
        f"{DOMAIN_KO[d]} {ow[d]*100:.0f}%" for d in DOMAINS
    )

    # 목적별 평균
    purpose_lines = []
    for purpose, w in ctx.get("by_purpose", {}).items():
        w_str = " | ".join(f"{DOMAIN_KO[d]} {w[d]*100:.0f}%" for d in DOMAINS)
        purpose_lines.append(f"  {purpose}: {w_str}")

    # 취약 시 참고 수치 (어느 영역이 weak일 때 전문가가 그 영역에 얼마나 썼는가)
    weak_lines = []
    for purpose, domain_data in ctx.get("by_purpose_weak_domain", {}).items():
        for domain, data in domain_data.items():
            w_weak = data.get("weak")
            n_weak = data.get("n_weak", 0)
            if w_weak and n_weak >= 10:
                w_str = " | ".join(f"{DOMAIN_KO[d]} {w_weak[d]*100:.0f}%" for d in DOMAINS)
                weak_lines.append(
                    f"  {purpose} / {DOMAIN_KO[domain]} 취약 (N={n_weak}): {w_str}"
                )

    lines = [
        f"[전문가 피드백 학습 데이터 — 교차 검증 참고용 (N={n})]",
        "※ 아래 수치는 계산 기본값이 아닙니다. 가중치는 반드시 25% 기본값 × 취약도 계수로 산출하세요.",
        f"전체 평균 경향: {mean_line}",
    ]
    if purpose_lines:
        lines.append("\n목적별 평균 경향 (계산 후 교차 검증용):")
        lines.extend(purpose_lines)

    lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────
# 3. 서브에이전트용: 도메인별 few-shot 예시 선택
# ──────────────────────────────────────────

def _score_example(record: dict, domain: str) -> float:
    """
    예시 품질 점수 (높을수록 좋은 예시).
    기준: 피드백 적정 길이 + 취약도(낮은 점수) + 에세이 적정 길이
    """
    d = record["domains"][domain]
    fb_len = len(d["feedback_combined"])
    avg_score = d["avg_score"] or 5.0
    essay_len = len(record["essay"])

    # 피드백 길이 점수: MIN~MAX 범위에 가까울수록 높음
    if fb_len < MIN_FEEDBACK_CHARS or fb_len > MAX_FEEDBACK_CHARS:
        fb_score = 0.0
    else:
        fb_score = 1.0 - abs(fb_len - 200) / 300

    # 취약도 점수: 점수가 낮을수록 더 instructive
    weakness_score = max(0.0, (WEAK_SCORE_THRESHOLD - avg_score + 1) / WEAK_SCORE_THRESHOLD)

    # 에세이 길이 점수: 100~600자 범위 선호
    if essay_len < 80 or essay_len > 800:
        essay_score = 0.5
    else:
        essay_score = 1.0

    return fb_score * 0.5 + weakness_score * 0.35 + essay_score * 0.15


def select_examples(
    records: list[dict],
    domain: str,
    n: int = N_EXAMPLES_PER_DOMAIN,
) -> list[dict]:
    """
    domain별 대표 few-shot 예시 선택.
    목적(설명/설득/친교)을 최대한 골고루 포함하고, 취약한 글 위주로 선택.
    """
    # 피드백이 비어 있는 레코드 제외
    valid = [
        r for r in records
        if len(r["domains"][domain]["feedback_combined"]) >= MIN_FEEDBACK_CHARS
    ]

    # 목적별로 분류
    by_purpose: dict[str, list[dict]] = defaultdict(list)
    for r in valid:
        by_purpose[r.get("purpose", "기타")].append(r)

    # 각 목적 그룹 내에서 품질 점수 내림차순 정렬
    for purpose in by_purpose:
        by_purpose[purpose].sort(
            key=lambda r: _score_example(r, domain), reverse=True
        )

    # 목적별로 1개씩 뽑되, 부족하면 가장 많은 그룹에서 보충
    selected: list[dict] = []
    for purpose in PURPOSES:
        if len(selected) >= n:
            break
        candidates = by_purpose.get(purpose, [])
        for r in candidates:
            if r not in selected:
                selected.append(r)
                break

    # 아직 n개 못 채웠으면 남은 것 중 점수 높은 것으로 보충
    if len(selected) < n:
        remaining = sorted(
            [r for r in valid if r not in selected],
            key=lambda r: _score_example(r, domain),
            reverse=True,
        )
        selected.extend(remaining[: n - len(selected)])

    # 저장할 필드만 추출 (에세이 전체 저장하지 않고 앞부분만)
    result = []
    for r in selected[:n]:
        d = r["domains"][domain]
        result.append({
            "purpose": r.get("purpose", ""),
            "grade":   r.get("grade", ""),
            "prompt":  r["prompt"],
            "essay_excerpt": r["essay"][:ESSAY_EXCERPT_LEN].strip() + (
                "..." if len(r["essay"]) > ESSAY_EXCERPT_LEN else ""
            ),
            "feedback": d["feedback_combined"],
            "avg_score": d["avg_score"],
        })
    return result


# ──────────────────────────────────────────
# 4. 서브에이전트 시스템 프롬프트용 문자열 생성
# ──────────────────────────────────────────

def build_agent_fewshot(domain: str, fewshot_path: str | Path) -> str:
    """
    few_shot_{domain}.json → 서브에이전트 시스템 프롬프트 끝에 붙일 문자열.
    파일 없으면 빈 문자열 반환.

    LLM이 스스로 글을 판단한 뒤 전문가 피드백 패턴을 참고할 수 있도록 구성.
    """
    try:
        with open(fewshot_path, encoding="utf-8") as f:
            examples = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""

    if not examples:
        return ""

    domain_ko = DOMAIN_KO[domain]
    lines = [
        "",
        "## 전문가 피드백 참고 사례",
        f"아래는 실제 전문가가 {domain_ko} 영역을 피드백한 예시입니다.",
        "이 글을 먼저 스스로 분석한 뒤, 아래 사례의 관점·언어·깊이를 참고하여 피드백을 작성하세요.",
        "사례를 그대로 복사하지 말고, 이 글에 맞게 새롭게 작성합니다.",
    ]
    for i, ex in enumerate(examples, 1):
        purpose = ex.get("purpose", "")
        grade   = ex.get("grade", "")
        lines.append(f"\n### 사례 {i} ({purpose} / {grade})")
        lines.append(f"[과제 지시문] {ex['prompt']}")
        lines.append(f"[학생 글 일부] {ex['essay_excerpt']}")
        lines.append(f"[전문가 {domain_ko} 피드백] {ex['feedback']}")

    return "\n".join(lines)


# ──────────────────────────────────────────
# 5. 전체 실행 (모든 파일 생성)
# ──────────────────────────────────────────

def build_all(db_path: str | Path, output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[1/2] feedback_db.jsonl 로딩 ...", flush=True)
    records = load_db(db_path)
    print(f"  {len(records)}건 로드 완료", flush=True)

    # 매니저용 가중치 컨텍스트
    print("[2/2] 가중치 컨텍스트 + few-shot 예시 생성 ...", flush=True)

    weight_ctx = build_weight_context(records)
    ctx_path = output_dir / "manager_weight_context.json"
    with open(ctx_path, "w", encoding="utf-8") as f:
        json.dump(weight_ctx, f, ensure_ascii=False, indent=2)
    print(f"  저장: {ctx_path}", flush=True)

    # 서브에이전트용 few-shot 예시
    for domain in DOMAINS:
        examples = select_examples(records, domain)
        fs_path = output_dir / f"few_shot_{domain}.json"
        with open(fs_path, "w", encoding="utf-8") as f:
            json.dump(examples, f, ensure_ascii=False, indent=2)
        print(f"  저장: {fs_path} ({len(examples)}개 예시)", flush=True)

    print("\n[완료] 모든 파일 생성됨", flush=True)


# ──────────────────────────────────────────
# CLI 실행
# ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="feedback_db.jsonl → manager/sub-agent few-shot 컨텍스트 파일 생성"
    )
    parser.add_argument(
        "--db",
        default="mafs/data/feedback_db.jsonl",
        help="feedback_db.jsonl 경로",
    )
    parser.add_argument(
        "--output_dir",
        default="mafs/data",
        help="생성 파일 저장 디렉터리",
    )
    args = parser.parse_args()

    build_all(args.db, args.output_dir)

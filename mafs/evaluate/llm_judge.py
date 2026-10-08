"""LLM 판사 평가 모듈 — RQ1~RQ3 공통 사용.

독립 평가자로서 피드백 초안을 C1~C5·M1~M5 기준으로 0/1/2 루브릭 채점한다.
  0 = 미충족
  1 = 부분 충족 (기준 방향은 맞으나 깊이·구체성 부족)
  2 = 완전 충족 (기준을 충분한 근거와 함께 완전히 만족)
이 모듈은 MAFS 파이프라인 내 검증 에이전트와 독립적으로 동작한다.
"""

import os
import json
import re
import asyncio
from pathlib import Path

MAFS_DIR = Path(__file__).parent.parent
CRITERIA = ["C1", "C2", "C3", "C4", "C5", "M1", "M2", "M3", "M4", "M5"]
TRIGGER_CRITERIA = ["C1", "C2", "M1", "M4"]

# ─────────────────────────────────────────────────
# 평가 프롬프트
# ─────────────────────────────────────────────────

JUDGE_SYSTEM_PROMPT = """\
당신은 초5~중3 논술형 글쓰기 피드백 연구 평가자입니다.
MISCA 피드백 모형(Panadero & Lipnevich, 2022)과 MAGIC 논문(Jordan et al., 2025) 기준으로
피드백 초안의 품질을 평가하고 JSON으로만 응답합니다.

## 평가 기준 (각 기준: 2=완전충족 / 1=부분충족 / 0=미충족)

C1 (글쓰기 관련성)
  2: 에세이의 내용·논리·구조·표현 분석을 위해 특정 표현·문장·사례를 5개 이상 참조하고, 그 중 3개 이상을 따옴표로 직접 인용함. 인용은 서로 다른 피드백 지점(강점·약점·feed forward 등)에 각각 연결되어야 함
  1: 에세이 내용을 언급하고 있으나 직접 인용이 2개 이하이거나, 인용이 한 지점에만 집중되어 있음
  0: 에세이 내용과 무관하게 일반론만 서술하거나 오타 목록만 나열함
  다음은 참조로 인정하지 않는다:
  - 맞춤법·오타 목록만 열거하는 것 (예: "이산하탄소→이산화탄소" 나열)
  - 에세이 내용을 그대로 요약하는 것
  - "잘 썼다", "부족하다" 식의 막연한 언급

C2 (약점 구체성)
  2: '어떤 부분(위치)이 왜(이유) 약점인지' 두 가지를 모두 갖추고, 에세이의 해당 표현·문장을 직접 인용한 구체적 지적이 3건 이상 있음
  1: 위치 또는 이유 중 하나만 있거나, 직접 인용이 없는 지적이 1~2건만 있음
  0: "전반적으로 부족하다" "더 구체적으로 썼으면 좋겠다" 식의 막연한 지적만 있음

C3 (강점 근거)
  2: 에세이의 실제 표현·구조·내용을 2개 이상 직접 인용하고, 각 인용에 대해 "왜 강점인지"(예: 독자에게 어떤 효과를 주는지, 어떤 기준을 충족하는지)까지 설명함
  1: 강점을 에세이 내용과 연결하여 언급하나 직접 인용이 1개 이하이거나, 인용은 있으나 왜 강점인지 설명이 없음
  0: 근거 없는 칭찬만 있거나 강점 언급이 전혀 없음 (진정한 강점이 없는 글에서 억지 칭찬도 0점)

C4 (분석 근거 수치화)
  2: 맞춤법 오류 건수, 접속어 유형 수·종류, 특성/근거/정서표현 개수 등 도구 분석 수치를 1개 이상 명시하거나, 학년 기준(예: "중1 수준에서는", "초등 고학년 기준으로")을 구체적으로 제시하여 피드백 판단 근거를 수치 또는 기준으로 뒷받침함
  1: 수치나 학년 기준 언급이 있으나 모호하거나(예: "여러 오류", "다양한 접속어"), 피드백 내용과 연결되지 않고 단순 나열에 그침
  0: 수치·기준 언급이 전혀 없고 "많다", "적다", "부족하다" 식의 주관적 표현만 있음
  다음은 인정하지 않는다:
  - 맞춤법 교정 목록 단순 나열 (건수 명시 없이 오류만 열거)
  - "더 구체적으로", "충분하지 않다" 식의 막연한 정도 표현

C5 (학습 성장 전제)
  2: 강점 인정·개선점·feed forward가 균형 있게 구성되어 학습 의욕을 충분히 지지함
  1: 세 요소 중 하나가 빠지거나 매우 약하게 다루어짐
  0: 일방적 비판만 있거나 학습 의욕을 저해하는 구성임

M1 (피드포워드)
  2: "다음에는 ~해 보세요" 또는 "다음 글을 쓸 때는 ~" 형식으로, 이 에세이의 특정 약점과 연결된 다음 글쓰기 지침이 명시적으로 있음
  1: 피드포워드 형식이 있으나 에세이 특정 약점과 연결되지 않고 일반론적임
  0: 피드포워드가 전혀 없거나 "~이 필요합니다", "~했다면 좋았을 것입니다" 형식만 있음

M2 (분석 타당성)
  2: 피드백이 지적한 약점·강점이 에세이 실제 내용에 비추어 모두 타당함
  1: 대부분 타당하나 오분석 1건이 있음
  0: 에세이에 없는 내용 언급, 실제 강점을 약점으로 지적, 또는 오분석 2건 이상

M3 (학습자 수준 적합)
  2: 어휘·문장·어조가 해당 학년 학생이 충분히 이해하고 받아들일 수 있는 수준임
  1: 대체로 적합하나 일부 어휘·문장이 너무 어렵거나 설명 없이 전문 용어를 사용함
  0: 학년 수준을 크게 벗어나 학생이 이해하기 어려운 표현·어조가 다수임

M4 (과제 맥락 반영)
  2: 과제 지시문 조건(글쓰기 유형·독자·형식·분량·소재 범위 등)이 에세이에서 어떻게 충족·미충족되었는지를 에세이의 구체적 표현·구조·내용과 연결하여 2가지 이상 분석함
  1: 과제 유형·주제를 언급하거나 에세이와 1가지만 연결함
  0: 과제 지시문을 단순 나열하거나 "잘 따랐습니다" 식의 확인만 함, 또는 언급 없음
  지시문에 조건이 없는 경우, 해당 글쓰기 유형(설명문·설득문·친교문)의 핵심 구조·요건을 에세이 실제 내용과 연결하여 2가지 이상 분석했을 때 2점.

M5 (영역별 분석의 충실성)
  2: 과제수행·내용·조직·표현 4개 영역 각각에서 에세이의 특정 표현·구조·내용을 근거로 한 구체적 분석이 2문장 이상 있음
  1: 4개 영역을 모두 언급했으나 일부 영역이 1문장 이하로만 다루어짐
  0: 1개 이상의 영역이 누락되거나 "과제수행(잘함)" 식의 괄호 한 단어 언급만 있음

## 출력 형식
JSON만 출력하고 다른 텍스트는 절대 포함하지 마세요.
마크다운 코드블록(```json ... ```)도 사용하지 마세요.

{
  "C1": 0,
  "C2": 1,
  "C3": 2,
  "C4": 1,
  "C5": 2,
  "M1": 0,
  "M2": 2,
  "M3": 2,
  "M4": 1,
  "M5": 1,
  "rationale": {
    "C1": "판단 근거 한 문장",
    "C2": "판단 근거 한 문장",
    "C3": "판단 근거 한 문장",
    "C4": "판단 근거 한 문장",
    "C5": "판단 근거 한 문장",
    "M1": "판단 근거 한 문장",
    "M2": "판단 근거 한 문장",
    "M3": "판단 근거 한 문장",
    "M4": "판단 근거 한 문장",
    "M5": "판단 근거 한 문장"
  }
}
"""


def _build_judge_input(essay: str, prompt: str, feedback: str, grade: str) -> str:
    return (
        f"[과제 지시문]\n{prompt}\n\n"
        f"[학생 학년]\n{grade}\n\n"
        f"[학생 에세이]\n{essay}\n\n"
        f"[평가할 피드백]\n{feedback}"
    )


def _parse_judge_output(text: str) -> dict | None:
    """LLM 출력에서 JSON을 추출·파싱한다. 마크다운 코드블록 포함 처리."""
    # 마크다운 코드블록 제거
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = text.rstrip("`").strip()

    # 첫 번째 { ... } 블록 추출
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    scores = {}
    for c in CRITERIA:
        val = data.get(c)
        if val in (0, 1, 2):
            scores[c] = val
        else:
            return None  # 불완전한 응답

    scores["rationale"] = data.get("rationale", {})
    return scores


def _compute_summary(scores: dict) -> dict:
    """점수 합계와 트리거/참고 기준별 소계를 계산한다."""
    trigger_score = sum(scores.get(c, 0) for c in TRIGGER_CRITERIA)
    ref_criteria = [c for c in CRITERIA if c not in TRIGGER_CRITERIA]
    ref_score = sum(scores.get(c, 0) for c in ref_criteria)
    total = trigger_score + ref_score
    return {
        "score_total":    total,
        "score_trigger":  trigger_score,
        "score_ref":      ref_score,
        "max_total":      len(CRITERIA) * 2,
        "max_trigger":    len(TRIGGER_CRITERIA) * 2,
        "max_ref":        len(ref_criteria) * 2,
    }


# ─────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────

async def score_feedback(
    essay: str,
    prompt: str,
    feedback: str,
    grade: str,
    model: str | None = None,
    max_retries: int = 3,
) -> dict | None:
    """피드백 1건을 LLM 판사로 채점한다.

    Returns:
        {"C1": 0|1|2, ..., "M5": 0|1|2,
         "rationale": {...},
         "score_total": int (0~20), "score_trigger": int (0~8), "score_ref": int (0~12), ...}
        파싱 실패 시 None.
    """
    from google import genai
    from google.genai import types
    from dotenv import load_dotenv

    load_dotenv(MAFS_DIR / ".env")

    if model is None:
        model = os.getenv("JUDGE_MODEL", "gemini-2.5-flash")

    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    user_msg = _build_judge_input(essay, prompt, feedback, grade)

    for attempt in range(max_retries):
        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=user_msg,
                config=types.GenerateContentConfig(
                    system_instruction=JUDGE_SYSTEM_PROMPT,
                    temperature=0.0,
                ),
            )
            scores = _parse_judge_output(resp.text or "")
            if scores is not None:
                scores.update(_compute_summary(scores))
                return scores
            print(f"[JUDGE] 파싱 실패 (시도 {attempt + 1}/{max_retries}) — 재시도")
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep([5, 15, 30][attempt])
            else:
                print(f"[JUDGE] 오류: {e}")
                return None

    return None


def print_score_summary(label: str, scores_list: list[dict]) -> None:
    """조건별 채점 결과 요약을 출력한다."""
    valid = [s for s in scores_list if s is not None]
    if not valid:
        print(f"{label}: 유효한 결과 없음")
        return

    n = len(valid)
    max_total   = valid[0]["max_total"]
    max_trigger = valid[0]["max_trigger"]
    max_ref     = valid[0]["max_ref"]
    print(f"\n{'='*60}")
    print(f"[{label}]  N={n}  (기준당 0~2점)")
    print(f"{'기준':<6} {'평균':>6}  {'분포 0/1/2':>14}")
    print("-" * 35)
    for c in CRITERIA:
        vals = [s[c] for s in valid]
        avg  = sum(vals) / n
        d0   = vals.count(0)
        d1   = vals.count(1)
        d2   = vals.count(2)
        tag  = " ← trigger" if c in TRIGGER_CRITERIA else ""
        print(f"  {c:<4} {avg:>5.2f}  ({d0:>2}/{d1:>2}/{d2:>2}){tag}")
    print("-" * 35)
    avg_total   = sum(s["score_total"]   for s in valid) / n
    avg_trigger = sum(s["score_trigger"] for s in valid) / n
    avg_ref     = sum(s["score_ref"]     for s in valid) / n
    print(f"  전체 평균:   {avg_total:.2f} / {max_total}")
    print(f"  트리거 평균: {avg_trigger:.2f} / {max_trigger}")
    print(f"  참고 평균:   {avg_ref:.2f} / {max_ref}")
    print("=" * 60)

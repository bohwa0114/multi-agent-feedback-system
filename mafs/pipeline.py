"""MAFS 핵심 파이프라인 — 순수 실행 모듈.

batch_run.py 및 evaluate/ 스크립트에서 임포트한다.

공개 인터페이스:
    run_mafs(essay, prompt, grade, on_stage=None) -> PipelineResult
    PipelineResult.feedback      : 최종 피드백 텍스트
    PipelineResult.diagnosis     : 취약 신호 진단 결과
    PipelineResult.purpose       : DIAGNOSIS가 판단한 글쓰기 목적 (설명문/설득문/친교및정서)
    PipelineResult.verify_rounds : 실제 검증 실행 횟수
    PipelineResult.final_criteria: 마지막 검증 라운드의 기준별 충족 여부
"""

import sys
import os
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

MAFS_DIR = Path(__file__).parent
if str(MAFS_DIR) not in sys.path:
    sys.path.insert(0, str(MAFS_DIR))

from dotenv import load_dotenv
load_dotenv(MAFS_DIR / ".env")

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────

MAX_RETRIES = 4
RETRY_DELAYS = [5, 15, 30, 60]

ALL_CRITERIA = ["C1", "C2", "C3", "C4", "C5", "M1", "M3", "M4", "M5"]
TRIGGER_CRITERIA = ["C1", "C2", "M1", "M4"]


# ──────────────────────────────────────────
# 파이프라인 결과 타입
# ──────────────────────────────────────────

@dataclass
class SynthesisResult:
    """Steps 1-3 결과. run_mafs_verify()에 그대로 전달 가능."""
    synthesis: str
    diagnosis: str
    purpose: str
    essay: str
    prompt: str
    grade: str


@dataclass
class PipelineResult:
    feedback: str
    diagnosis: str
    verify_rounds: int
    purpose: str = ""
    final_criteria: dict[str, str] = field(default_factory=dict)


def parse_purpose_from_diagnosis(diagnosis: str) -> str:
    """DIAGNOSIS 출력에서 '글쓰기 목적: ...' 줄을 파싱해 목적 문자열을 반환한다.

    Returns:
        "설명문", "설득문", "친교및정서" 중 하나. 파싱 실패 시 빈 문자열.
    """
    for line in diagnosis.splitlines():
        if "글쓰기 목적" in line and ":" in line:
            value = line.split(":", 1)[1].strip()
            for keyword in ("설명문", "설득문", "친교및정서", "친교 및 정서"):
                if keyword in value:
                    return "친교및정서" if "친교" in keyword else keyword
    return ""


# ──────────────────────────────────────────
# LLM / ADK 호출 헬퍼
# ──────────────────────────────────────────

def _is_503(e: Exception) -> bool:
    msg = str(e)
    if "503" in msg or "UNAVAILABLE" in msg or "429" in msg:
        return True
    if isinstance(e, BaseExceptionGroup):
        return any(_is_503(sub) for sub in e.exceptions)
    return False


async def _llm(system_prompt: str, user_message: str, model: str) -> str:
    """재시도 포함 직접 LLM 호출."""
    from google import genai
    from google.genai import types

    api_key = os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)

    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=user_message,
                config=types.GenerateContentConfig(system_instruction=system_prompt),
            )
            text = resp.text or ""
            print(f"[LLM] {model} → {len(text)}자", flush=True)
            return text
        except Exception as e:
            if _is_503(e) and attempt < MAX_RETRIES - 1:
                print(f"[RETRY-LLM] {RETRY_DELAYS[attempt]}초 후 재시도...", flush=True)
                await asyncio.sleep(RETRY_DELAYS[attempt])
            else:
                raise


async def _run_adk_agent(agent, user_message: str) -> str:
    """ADK 에이전트(도구 포함) 실행 후 텍스트 수집. 재시도 포함."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part

    for attempt in range(MAX_RETRIES):
        try:
            ss = InMemorySessionService()
            runner = Runner(agent=agent, app_name="mafs", session_service=ss)
            session = await ss.create_session(app_name="mafs", user_id="user")
            msg = Content(role="user", parts=[Part(text=user_message)])

            texts = []
            async for event in runner.run_async(
                user_id="user", session_id=session.id, new_message=msg
            ):
                if event.content and event.content.parts:
                    parts = [p.text for p in event.content.parts if getattr(p, "text", None)]
                    if parts:
                        texts.append("\n".join(parts))

            result = "\n\n".join(texts).strip()
            print(f"[ADK] {agent.name} → {len(result)}자", flush=True)
            return result

        except Exception as e:
            if _is_503(e) and attempt < MAX_RETRIES - 1:
                print(f"[RETRY-ADK] {agent.name} {RETRY_DELAYS[attempt]}초 후 재시도...", flush=True)
                await asyncio.sleep(RETRY_DELAYS[attempt])
            else:
                raise


# ──────────────────────────────────────────
# 검증 결과 파싱 유틸리티
# ──────────────────────────────────────────

def parse_criteria(text: str) -> dict[str, str]:
    """검증 결과 텍스트에서 기준별 충족 여부(✓/✗/?) 추출.

    모델이 ✓/✗ 기호를 출력하지 않는 경우를 대비해 여러 패턴을 순서대로 시도한다.
    """
    # 충족/미충족을 나타내는 키워드 집합
    PASS_WORDS = ("✓", "충족", "통과", "pass", "PASS", "O", "◯")
    FAIL_WORDS = ("✗", "미충족", "실패", "fail", "FAIL", "X", "×")

    result = {}
    for c in ALL_CRITERIA:
        found = "?"
        # 기준 코드가 등장하는 위치를 모두 탐색
        search_start = 0
        while True:
            idx = text.find(c, search_start)
            if idx == -1:
                break
            # 기준 코드 앞뒤가 단어 경계인지 확인 (C1A 같은 오탐 방지)
            before = text[idx - 1] if idx > 0 else " "
            after  = text[idx + len(c)] if idx + len(c) < len(text) else " "
            if before.isalnum() or after.isalnum():
                search_start = idx + 1
                continue
            # 해당 기준 코드 기준으로 앞뒤 60자 스니펫 검사
            snippet = text[max(0, idx - 5): idx + 60]
            for w in FAIL_WORDS:
                if w in snippet:
                    found = "✗"
                    break
            if found == "?":
                for w in PASS_WORDS:
                    if w in snippet:
                        found = "✓"
                        break
            if found != "?":
                break
            search_start = idx + 1
        result[c] = found
    return result


def print_verification(round_num: int, text: str, prev: dict[str, str] | None) -> dict[str, str]:
    """라운드별 기준 충족 현황을 터미널에 출력하고 파싱 결과를 반환."""
    cur = parse_criteria(text)
    # 비트리거 기준이 ?로 파싱된 경우 이전 라운드 값 유지 (재합성 시 일부 기준 누락 방지)
    if prev:
        for c in ALL_CRITERIA:
            if c not in TRIGGER_CRITERIA and cur.get(c) == "?" and prev.get(c) in ("✓", "✗"):
                cur[c] = prev[c]
    lines = [f"\n{'='*50}", f"[검증 {round_num}회차] MISCA 기준 충족 현황", f"{'='*50}"]

    header = f"  {'기준':<6}{'결과':<6}{'유형':<12}"
    lines.append(header)
    lines.append("  " + "-" * 22)

    for c in ALL_CRITERIA:
        symbol = cur.get(c, "?")
        kind = "(트리거)" if c in TRIGGER_CRITERIA else "(참고)"
        change = ""
        if prev and prev.get(c) and prev[c] != symbol and prev[c] != "?":
            change = f"  ← {prev[c]} 에서 변경"
        lines.append(f"  {c:<6}{symbol:<6}{kind:<12}{change}")

    failed_triggers = [c for c in TRIGGER_CRITERIA if cur.get(c) == "✗"]
    if failed_triggers:
        lines.append(f"\n  미충족 트리거: {', '.join(failed_triggers)} → 재합성 예정")
    else:
        lines.append("\n  모든 트리거 기준 충족 ✓")

    lines.append("=" * 50)
    print("\n".join(lines), flush=True)
    return cur


# ──────────────────────────────────────────
# LLM 기반 재실행 결정 파싱
# ──────────────────────────────────────────

_AGENT_KEYS = {"task_agent", "content_agent", "organization_agent", "expression_agent"}


def _parse_refine_decision(manager_output: str) -> dict[str, str]:
    """매니저 LLM 출력 파싱 → {에이전트명: 지시문}.

    출력 형식:
        재실행: task_agent, content_agent
        task_agent: <지시>
        content_agent: <지시>
        organization_agent: 해당없음
        expression_agent: 해당없음
    """
    result: dict[str, str] = {}

    rerun_agents: set[str] = set()
    for line in manager_output.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("재실행:"):
            val = stripped.split(":", 1)[1].strip()
            if val and val != "없음":
                for part in val.split(","):
                    a = part.strip()
                    if a in _AGENT_KEYS:
                        rerun_agents.add(a)
            break

    if not rerun_agents:
        return result

    for line in manager_output.splitlines():
        stripped = line.strip()
        for agent in rerun_agents:
            if stripped.startswith(f"{agent}:"):
                instruction = stripped.split(":", 1)[1].strip()
                if instruction and instruction != "해당없음":
                    result[agent] = instruction
                break

    return result


# ──────────────────────────────────────────
# 핵심 파이프라인
# ──────────────────────────────────────────

async def run_mafs_synthesis(
    essay: str,
    prompt: str,
    grade: str,
    purpose: str = "",
    on_stage=None,
) -> SynthesisResult:
    """MAFS Step 1-3 (진단 + 병렬 에이전트 + 합성)만 실행하고 중간 결과를 반환.

    RQ2 공유 synthesis 설계에서 사용:
        sr = await run_mafs_synthesis(essay, prompt, grade)
        feedback_b = sr.synthesis          # no_verify 조건
        result_a  = await run_mafs_verify(sr)  # 검증 루프 조건
    """
    from agent import parallel_feedback
    from config import MODEL
    from prompts.manager import DIAGNOSIS_PROMPT, SYNTHESIS_PROMPT
    from data.few_shot_builder import build_diagnosis_context

    _ctx_path = MAFS_DIR / "data" / "manager_weight_context.json"
    _learned_ctx = build_diagnosis_context(_ctx_path)
    _diagnosis_prompt = _learned_ctx + DIAGNOSIS_PROMPT

    async def notify(stage: str):
        print(f"[STAGE] {stage}", flush=True)
        if on_stage:
            try:
                await on_stage(stage)
            except Exception:
                pass

    _purpose_hint = f"\n\n[글쓰기 목적 힌트]\n{purpose}" if purpose else ""
    base_input = (
        f"[글쓰기]\n{essay}\n\n"
        f"[과제 지시문]\n{prompt}\n\n"
        f"[학생 학년]\n{grade}"
        f"{_purpose_hint}"
    )

    await notify("reading")
    diagnosis = await _llm(_diagnosis_prompt, base_input, MODEL)
    print(f"[DIAG] {diagnosis[:120]}", flush=True)

    await notify("parallel")
    sub_feedback = await _run_adk_agent(parallel_feedback, base_input)

    await notify("synthesizing")
    synthesis_input = (
        f"{base_input}\n\n"
        f"[가중치 진단]\n{diagnosis}\n\n"
        f"[영역별 분석 결과]\n{sub_feedback}"
    )
    synthesis = await _llm(SYNTHESIS_PROMPT, synthesis_input, MODEL)

    inferred_purpose = purpose or parse_purpose_from_diagnosis(diagnosis)
    return SynthesisResult(
        synthesis=synthesis,
        diagnosis=diagnosis,
        purpose=inferred_purpose,
        essay=essay,
        prompt=prompt,
        grade=grade,
    )


async def run_mafs_verify(sr: SynthesisResult, on_stage=None) -> PipelineResult:
    """MAFS Step 4 (검증 루프)만 실행. run_mafs_synthesis() 결과를 받아 처리.

    RQ2 공유 synthesis 설계에서 사용.
    """
    from agent import (verification_agent,
                       task_agent, content_agent, organization_agent, expression_agent)
    from config import MODEL
    from prompts.manager import REFINE_MANAGER_PROMPT, SYNTHESIS_PATCH_PROMPT

    _agent_map = {
        "task_agent": task_agent,
        "content_agent": content_agent,
        "organization_agent": organization_agent,
        "expression_agent": expression_agent,
    }

    async def notify(stage: str):
        print(f"[STAGE] {stage}", flush=True)
        if on_stage:
            try:
                await on_stage(stage)
            except Exception:
                pass

    synthesis = sr.synthesis
    essay, prompt = sr.essay, sr.prompt

    prev_failed_criteria: set[str] = set()
    prev_criteria: dict[str, str] = {}
    final_criteria: dict[str, str] = {}
    verify_rounds = 0

    for round_num in range(1, 4):
        stage_map = {1: "verifying_1", 2: "verifying_2", 3: "verifying_3"}
        await notify(stage_map[round_num])
        verify_rounds = round_num

        verify_input = (
            f"[피드백 초안]\n{synthesis}\n\n"
            f"[에세이]\n{essay}\n\n"
            f"[과제 지시문]\n{prompt}"
        )
        verification = await _run_adk_agent(verification_agent, verify_input)
        prev_criteria = print_verification(
            round_num, verification,
            prev_criteria if round_num > 1 else None,
        )
        final_criteria = prev_criteria

        trigger_parsed = [prev_criteria.get(c) for c in TRIGGER_CRITERIA]
        if all(v == "?" for v in trigger_parsed):
            print(f"[VER] 파싱 실패 round {round_num}", flush=True)
            if round_num < 3:
                continue
            else:
                break

        current_failed = {c for c in TRIGGER_CRITERIA if prev_criteria.get(c) == "✗"}
        failed = bool(current_failed)
        if not failed or round_num == 3:
            break

        if round_num == 2 and current_failed and current_failed == prev_failed_criteria:
            print("[VER] 동일 기준 2차 연속 미충족 — 종료", flush=True)
            break

        prev_failed_criteria = current_failed

        refine_stage = "refining_1" if round_num == 1 else "refining_2"
        await notify(refine_stage)

        # ── 매니저 LLM: 하위 에이전트 재실행 결정 ──
        base_input = (
            f"[글쓰기]\n{essay}\n\n"
            f"[과제 지시문]\n{prompt}\n\n"
            f"[학생 학년]\n{sr.grade}"
        )
        refine_manager_input = (
            f"[검증 결과 및 미충족 이유]\n{verification}\n\n"
            f"[현재 피드백 초안]\n{synthesis}\n\n"
            f"[에세이]\n{essay}\n\n"
            f"[과제 지시문]\n{prompt}"
        )
        refine_decision_text = await _llm(REFINE_MANAGER_PROMPT, refine_manager_input, MODEL)
        refine_decision = _parse_refine_decision(refine_decision_text)
        print(f"[REFINE] 매니저 결정 — 재실행: {list(refine_decision.keys())}", flush=True)

        # ── 선택된 하위 에이전트 재실행 ──
        new_sub_outputs: dict[str, str] = {}
        for agent_name, instruction in refine_decision.items():
            agent = _agent_map[agent_name]
            agent_input = (
                f"{base_input}\n\n"
                f"[재실행 지시 — 반드시 반영]\n{instruction}"
            )
            new_output = await _run_adk_agent(agent, agent_input)
            new_sub_outputs[agent_name] = new_output
            print(f"[REFINE] {agent_name} 재실행 완료 ({len(new_output)}자)", flush=True)

        # ── 매니저 LLM: 새 에이전트 출력으로 합성 교체 ──
        if new_sub_outputs:
            new_sub_block = "\n\n".join(
                f"[{name} 새 분석]\n{output}"
                for name, output in new_sub_outputs.items()
            )
            synthesis_patch_input = (
                f"[기존 피드백 초안]\n{synthesis}\n\n"
                f"[재실행 에이전트 새 분석]\n{new_sub_block}\n\n"
                f"[에세이]\n{essay}\n\n"
                f"[과제 지시문]\n{prompt}"
            )
            synthesis = await _llm(SYNTHESIS_PATCH_PROMPT, synthesis_patch_input, MODEL)
        else:
            # 파싱 실패 fallback: task_agent 기본 실행 (M2/M3 가장 흔한 실패, 모두 task_agent 담당)
            print("[REFINE] 재실행 에이전트 파싱 실패 — task_agent 기본 실행", flush=True)
            agent_input = (
                f"{base_input}\n\n"
                f"[재실행 지시]\n{refine_decision_text}"
            )
            new_output = await _run_adk_agent(task_agent, agent_input)
            new_sub_outputs["task_agent"] = new_output
            new_sub_block = f"[task_agent 새 분석]\n{new_output}"
            synthesis_patch_input = (
                f"[기존 피드백 초안]\n{synthesis}\n\n"
                f"[재실행 에이전트 새 분석]\n{new_sub_block}\n\n"
                f"[에세이]\n{essay}\n\n"
                f"[과제 지시문]\n{prompt}"
            )
            synthesis = await _llm(SYNTHESIS_PATCH_PROMPT, synthesis_patch_input, MODEL)

    await notify("done")
    return PipelineResult(
        feedback=synthesis,
        diagnosis=sr.diagnosis,
        purpose=sr.purpose,
        verify_rounds=verify_rounds,
        final_criteria=final_criteria,
    )


async def run_mafs(
    essay: str,
    prompt: str,
    grade: str,
    purpose: str = "",
    on_stage=None,
    skip_verify: bool = False,
) -> PipelineResult:
    """MAFS 하드코딩 오케스트레이션 — Python이 각 단계를 직접 호출.

    Args:
        essay:        학생 에세이 텍스트
        prompt:       과제 지시문 텍스트
        grade:        학생 학년 (예: "중1")
        purpose:      글쓰기 목적 힌트. 선택적.
        on_stage:     단계 변경 시 호출할 async 콜백. 선택적.
        skip_verify:  True이면 검증 루프 없이 합성 초안을 그대로 반환.

    Returns:
        PipelineResult
    """
    sr = await run_mafs_synthesis(essay, prompt, grade, purpose, on_stage)
    if skip_verify:
        return PipelineResult(
            feedback=sr.synthesis,
            diagnosis=sr.diagnosis,
            purpose=sr.purpose,
            verify_rounds=0,
            final_criteria={},
        )
    return await run_mafs_verify(sr, on_stage)

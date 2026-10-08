"""검증 에이전트 (Verification Agent) + LLM Judge 서브에이전트."""

from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool

import os
from config import MODEL

# 검증 에이전트는 형식 준수가 중요하므로 별도 모델 변수로 관리
# VERIFY_MODEL 미설정 시 gemini-2.5-pro 고정 (flash는 출력 형식 불안정)
VERIFY_MODEL = os.getenv("VERIFY_MODEL", "gemini-2.5-pro")
from prompts.verification import VERIFICATION_PROMPT, LLM_JUDGE_PROMPT

# LLM Judge: MISCA 전문가 페르소나로 서술형 질적 판단 수행
# Agent-as-a-Tool 패턴으로 검증 에이전트의 도구로 등록
llm_judge = LlmAgent(
    name="llm_judge",
    model=VERIFY_MODEL,
    instruction=LLM_JUDGE_PROMPT,
    description=(
        "MISCA 전문가 페르소나로 피드백 초안의 각 기준(C1~C5·M1~M5)에 대해 "
        "서술형 질적 판단을 수행한다."
    ),
)

verification_agent = LlmAgent(
    name="verification_agent",
    model=VERIFY_MODEL,
    instruction=VERIFICATION_PROMPT,
    description=(
        "MISCA 기반 C1~C5·M1~M5 기준으로 피드백 초안을 질적으로 검토하고, "
        "트리거 기준 미충족 시 구체적 지적 사항을 생성하여 매니저에게 반환한다."
    ),
    tools=[AgentTool(agent=llm_judge)],
)

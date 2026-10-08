"""MAFS 에이전트 정의.

pipeline.py의 run_mafs()에서 parallel_feedback, verification_agent를 임포트한다.
Python 하드코딩 오케스트레이션으로 전환 후 root_agent(ADK LlmAgent 매니저)는 사용하지 않는다.
"""

from google.adk.agents import LlmAgent, ParallelAgent

from config import SUB_MODEL
from tools.evidence_extractor import extract_evidence_sentences
from tools.feature_counter import count_features
from tools.conjunction_analyzer import analyze_conjunctions
from tools.spell_checker import check_spelling
from agents.verification_agent import verification_agent
from prompts.task import TASK_PROMPT
from prompts.content import CONTENT_PROMPT
from prompts.organization import ORGANIZATION_PROMPT
from prompts.expression import EXPRESSION_PROMPT

# 서브에이전트: 시스템 프롬프트만 사용 (zero-shot)
# few-shot 예시는 자동 선별 품질 문제로 비활성화
task_agent = LlmAgent(
    name="task_completion_agent",
    model=SUB_MODEL,
    instruction=TASK_PROMPT,
    description="과제 지시문의 독자·목적·조건 충족 여부를 판단하고 피드백 초안을 생성한다.",
    tools=[extract_evidence_sentences],
)

content_agent = LlmAgent(
    name="content_agent",
    model=SUB_MODEL,
    instruction=CONTENT_PROMPT,
    description="글쓰기 내용의 명료성·구체성·적절성을 판단하고 피드백 초안을 생성한다.",
    tools=[extract_evidence_sentences, count_features],
)

organization_agent = LlmAgent(
    name="organization_agent",
    model=SUB_MODEL,
    instruction=ORGANIZATION_PROMPT,
    description="글쓰기 조직의 연결성·통일성을 판단하고 피드백 초안을 생성한다.",
    tools=[analyze_conjunctions, extract_evidence_sentences],
)

expression_agent = LlmAgent(
    name="expression_agent",
    model=SUB_MODEL,
    instruction=EXPRESSION_PROMPT,
    description="글쓰기 표현의 어휘 적절성·어법 정확성을 판단하고 피드백 초안을 생성한다.",
    tools=[check_spelling, extract_evidence_sentences],
)

# 병렬 실행 그룹
parallel_feedback = ParallelAgent(
    name="parallel_feedback",
    description=(
        "과제수행·내용·조직·표현 4개 에이전트를 병렬로 실행하여 "
        "각 영역 피드백 초안을 동시에 생성한다."
    ),
    sub_agents=[task_agent, content_agent, organization_agent, expression_agent],
)


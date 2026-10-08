# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

MAFS(Multi-Agent Writing Feedback System) — 초5~중3 논술형 글쓰기 피드백 자동 생성 다중 에이전트 시스템 (국어·사회, 본 실험 평가 대상 기준).
Google ADK + Gemini 기반. 설계 근거: `MAFS_design_spec.pdf` (로컬 참고 문서, 저장소에는 포함되지 않음)

## 실행 명령어

```bash
# 의존성 설치
pip install -r mafs/requirements.txt

# 환경변수 설정
copy mafs\.env.example mafs\.env   # Windows
# .env 파일에 GOOGLE_API_KEY 입력
# 모델 변경: GEMINI_MODEL / GEMINI_SUB_MODEL 변수 사용

# 데이터 로더 동작 확인
python mafs/data/loader.py
```

## 아키텍처

### 인터페이스: 배치 평가 스크립트 (`mafs/batch_run.py`, `mafs/evaluate/`)

- CSV/JSON 논술문 파일을 일괄 처리해 `run_mafs()` 파이프라인을 실행
- RQ1~RQ3 평가 스크립트(`rq1_instruction.py`, `rq2_design_elements.py`)가 LLM 판사 채점까지 연결
- CSV 형식: AI Hub 논술형 글쓰기 평가 데이터 (글쓰기 지시문 / 학년 / 학생 답변)

### 오케스트레이션: Python 하드코딩 (`mafs/pipeline.py`)

ADK LlmAgent 매니저를 제거하고 Python이 각 단계를 직접 순서대로 호출한다.
(배경: LlmAgent가 도구 호출 후 텍스트를 생성하지 않는 빈 응답 문제 구조적 해결)

**공개 API:**
- `run_mafs(essay, prompt, grade, purpose="", on_stage=None, skip_verify=False) → PipelineResult` — 전체 파이프라인
- `run_mafs_synthesis(essay, prompt, grade, purpose="", on_stage=None) → SynthesisResult` — Steps 1-3만
- `run_mafs_verify(sr: SynthesisResult, on_stage=None) → PipelineResult` — Step 4(검증 루프)만
- `SynthesisResult` dataclass: synthesis, diagnosis, purpose, essay, prompt, grade 필드 보유

RQ2 공유 synthesis 설계에서 `run_mafs_synthesis()` 결과를 B조건(검증 없음)으로 직접 쓰고, 같은 결과에 `run_mafs_verify()`를 적용한 것을 A조건(검증 포함)으로 사용한다.

```
STEP 1: _llm(DIAGNOSIS_PROMPT)            ← 취약 신호 진단 + 가중치 조정 + 글쓰기 목적 판단
STEP 2: _run_adk_agent(parallel_feedback) ← 4개 ADK 에이전트 병렬 실행
STEP 3: _llm(SYNTHESIS_PROMPT)            ← 종합 피드백 초안 생성  [→ SynthesisResult.synthesis]
STEP 4: 검증 루프 (검증 최대 3회 / refine 최대 2회)
        _run_adk_agent(verification_agent) → 미충족 트리거(C1·C2·M1·M4) 있으면:
          _llm(REFINE_MANAGER_PROMPT)      ← LLM 매니저: 검증 결과 분석 → 재실행 에이전트 결정
          _run_adk_agent(selected_agents)  ← 선택된 하위 에이전트만 재실행
          _llm(SYNTHESIS_PATCH_PROMPT)     ← 재실행 결과로 해당 영역만 교체·통합
```

### 에이전트 구조

```
parallel_feedback (ParallelAgent)  ← agent.py, ADK 내부 병렬 실행
├── task_completion_agent          ← 과제수행: 의사소통 맥락·조건 충족 여부 + 목적별 뉘앙스 [SUB_MODEL]
├── content_agent                  ← 내용: 목적별 루브릭 적용             [SUB_MODEL]
│     설명문: 명료성·구체성·적절성(특성 개수)
│     설득문: 주장의 명료성·주장의 적절성·근거의 타당성(근거 개수)
│     친교및정서: 명료성·구체성·적절성(정서표현 언어 개수)
├── organization_agent             ← 조직: 연결성·통일성                [SUB_MODEL]
└── expression_agent               ← 표현: 어휘 적절성·어법 정확성       [SUB_MODEL]

verification_agent (LlmAgent)      ← MISCA 기반 품질 검증               [MODEL]
└── llm_judge (AgentTool)          ← MISCA 전문가 페르소나 서브에이전트  [MODEL]
```

### 모델 설정 (`mafs/config.py`)

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `MODEL` | `gemini-2.5-flash` | 진단·합성·검증 |
| `SUB_MODEL` | `gemini-2.5-flash` | 4개 병렬 분석 에이전트 |

LLM 판사(`evaluate/llm_judge.py`)도 기본값 `gemini-2.5-flash`. 전 모델 flash로 통일.

SUB_MODEL은 RPM이 높은 경량 모델(gemini-2.5-flash-lite 등)을 사용하여 병렬 호출 시 503 방지.

### Function Tools (`mafs/tools/`)

모든 도구는 `async def`로 정의하며 ADK가 자동으로 LlmAgent에 등록한다.

| 파일 | 도구명 | 용도 |
|------|--------|------|
| `evidence_extractor.py` | `extract_evidence_sentences` | 에세이를 인덱싱된 문장 목록으로 변환 (hallucination 방지) |
| `feature_counter.py` | `count_features` | LLM이 추출한 후보 목록 중복 제거 후 카운팅 (설명문: 특성, 설득문: 근거, 친교및정서: 정서표현 언어) |
| `conjunction_analyzer.py` | `analyze_conjunctions` | 한국어 접속어 유형별(순접·역접·인과·예시·전환·양보) 빈도·다양성 산출 |
| `spell_checker.py` | `check_spelling` | speller.town 맞춤법 검사 API (직접 HTTP 호출). graceful fallback 포함 |

### 시스템 프롬프트 (`mafs/prompts/`)

| 파일 | 상수명 | 용도 |
|------|--------|------|
| `manager.py` | `DIAGNOSIS_PROMPT` | 취약 신호 진단 + 동적 가중치 조정 + 글쓰기 목적 판단. 출력에 `글쓰기 목적:` 명시 |
| `manager.py` | `SYNTHESIS_PROMPT` | 최종 통합 피드백 생성 (가중치 비율 분량 배분, 영역당 문단 1개, 학년별 문체) |
| `manager.py` | `REFINE_MANAGER_PROMPT` | 검증 결과를 받아 어떤 하위 에이전트를 재실행할지 LLM이 판단. 출력 형식: `재실행: task_agent, content_agent` + 에이전트별 구체적 지시 |
| `manager.py` | `SYNTHESIS_PATCH_PROMPT` | 재실행 에이전트 새 출력으로 기존 합성의 해당 영역만 교체. 나머지 영역은 그대로 유지 |
| `verification.py` | `VERIFICATION_PROMPT` | MISCA C1~C5·M1·M3~M5 기준(9개, M2 분석 타당성은 사후 독립 판사 전용) + few-shot 예시 내장 |

재호출 트리거 기준: C1(글쓰기 관련성), C2(약점 구체성), M1(피드포워드), M4(과제 맥락 반영)

### 핵심 설계 제약 (수정 시 반드시 유지)

- **검증 에이전트는 매니저의 추론 과정을 받지 않는다** — 확증 편향 방지.
- **4개 병렬 에이전트는 점수를 산출하지 않는다** — 피드백 텍스트만 생성.
- **검증 최대 3회 / refine 최대 2회** — 동일 기준 2차 연속 미충족이면 재실행 없이 종료.
- **LLM 기반 매니저 라우팅** — REFINE_MANAGER_PROMPT가 검증 결과를 분석해 재실행 에이전트를 자율 결정. Python 하드코딩으로 분기하지 않는다.
- **SYNTHESIS_PATCH_PROMPT는 해당 영역만 수정** — 재실행하지 않은 에이전트 영역은 기존 합성 그대로 유지. 전체 재합성 금지.
- **SYNTHESIS_PROMPT 분량 배분** — 최종 조정 가중치 X%인 영역은 피드백의 약 X% 분량, 영역당 문단 하나.
- **RQ1·RQ2 공유 synthesis** — `run_mafs_synthesis()` 결과(`synthesis_0`)를 RQ1 출력에 저장. RQ2는 `--reuse_rq1`로 이 값을 조건 B로 재사용하고, 같은 A조건 피드백도 재사용. 두 연구 질문에서 MAFS 피드백이 동일하도록 보장.

### 연구 완료 상태

- **본 실험 200건 완료**: 국어·사회 10폴더×20건 층화 샘플링, RQ1·RQ2·RQ3 전부 실행 및 통계 분석 완료 (과학 폴더 제외 — 5(학년)×2(교과) 균형 설계). 평가 방법론은 `design.md` §8, 실제 결과 수치는 논문 IV장 참조.
- **RAG**: 연구 설계 공정성 문제로 파이프라인에서 제거 (파일 `tools/rag_retriever.py` 삭제됨).
- **RQ2 subgroup analysis 완료**: verify_rounds >= 2 케이스(refine 발생 70건)만 추출하여 synthesis_0 vs 최종 대응표본 t-검정.
- **Jamovi용 CSV 완료**: `export_csv.py`로 생성. RQ1·RQ2: 대응표본 t-검정 + Cohen's d. RQ3: Two-way ANOVA 5×2 + partial η².

## 데이터 경로

AI Hub 논술형 글쓰기 평가 데이터: `MISCA/26.논술형_글쓰기_평가_데이터/`
`data/loader.py`의 `LABEL_DIR` 변수가 라벨링 JSON 경로 참조.
JSON 키: `essay_answer.text` (에세이), `essay_question.prompt` (과제 지시문).

학습 데이터: `mafs/data/feedback_db.jsonl` — N=16,010 (초5~중3 국어·사회·과학 12개 폴더 전체)
학습 데이터 재구축: `python mafs/data/feedback_extractor.py --data_dir "26.논술형_글쓰기_평가_데이터/3.개방데이터/1.데이터/Training/02.라벨링데이터" --output mafs/data/feedback_db.jsonl`
weight context 재구축: `python mafs/data/few_shot_builder.py`

## 추가 참고 파일

- `mafs/EXTERNAL_APIS.md`: 외부 API 및 의존성 상세
- `mafs/design.md`: 설계 지침서 전문
- `mafs/process.md`: 설계·구현 의사결정 과정 기록

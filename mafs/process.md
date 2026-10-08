# MAFS 개발 과정 기록

Multi-Agent Writing Feedback System — 설계·구현 과정 로그  
중학교 논술형 글쓰기 피드백 자동 생성 다중 에이전트 시스템

> 이 문서는 기술 명세(design.md)가 아닌 **의사결정 과정**을 기록한다.
> 왜 이렇게 설계했는지, 어떤 문제를 만났고 어떻게 해결했는지를 담는다.

---

## 현재 상태 — 본 실험 완료 (N=200)

**평가 진행 단계** — 파일럿(120건) RQ1·RQ2·RQ3 완료 후, 본 실험 200건(국어·사회 10폴더 × 20건, 과학 제외 — 5×2 균형 설계)으로 RQ1·RQ2·RQ3 전부 완료. 평가 방법론은 `design.md` §8, 실제 결과 수치는 논문 IV장 참조.

완성된 항목:
- 본 실험 200건 샘플링 및 RQ1·RQ2·RQ3 실행 (과학 폴더 제외)
- RQ2 subgroup analysis (refine 발생 70건 한정 대응표본 t-검정)
- Jamovi용 CSV 변환(export_csv.py) 및 통계 최종 보고 (RQ1·RQ2: 대응표본 t-검정 + Cohen's d / RQ3: Two-way ANOVA 5×2 + partial η²)
- 검증 기준 강화: C1(직접 인용 필수+3개), C2(약점 2건), M1(에세이 특정), M4(조건 명시 인용)
- LLM Judge 재정의: 체크리스트 → 서술형 질적 판단 먼저, ✓/✗는 결론으로만
- few-shot 전면 제거 — 자동 선별 예시 품질 문제 확인 후 zero-shot으로 전환
- 배치 처리(`batch_run.py`) — JSON/CSV 일괄 처리, `--sample`/`--seed` 무작위 샘플링
- `view_results.py` — 배치 결과 요약 뷰어
- cross-prompt 확장: 중학교 국어 → 초5~중3 국어·사회·과학 12개 폴더 (학습 데이터 범위. 본 실험 평가 대상은 국어·사회로 한정)
- `feedback_db.jsonl` 재구축 (N=4,146 → N=16,010)
- content.py AI Hub 실제 루브릭 기반 목적별 전면 재설계 (설명문·설득문·친교및정서 각각 3기준)
- DIAGNOSIS_PROMPT 출력에 `글쓰기 목적:` 명시, `pipeline.py`에 `purpose` 파라미터 추가
- 맞춤법 API 교체: 네이버 직접 HTTP → speller.town REST API
- LLM 기반 매니저 라우팅 구현 (REFINE_MANAGER_PROMPT + SYNTHESIS_PATCH_PROMPT)
- 파이프라인 분리: run_mafs_synthesis() / run_mafs_verify() / SynthesisResult
- 공유 synthesis 설계: RQ2 B조건에 synthesis_0 재사용 → A<B 역전 원천 차단
- RAG 제거 완료: tools/rag_retriever.py 삭제, evaluate/rejudge.py 삭제
- TRIGGER_KEYWORDS 버그 수정: parse_criteria 결과로 refine 트리거 통일
- rq2_design_elements.py reused_scores NameError 수정
- rq1_instruction.py 출력에 verify_rounds 필드 추가 (subgroup analysis용)
- export_csv.py: RQ2 형식 수정(_conditions_ 구조), 파일명 _spss.csv로 변경
- 파일럿(120건) RQ1·RQ2·RQ3 완료 및 결과 정리

---

## 이론적 근거와 구현 결정의 연결

MAFS의 핵심 설계 결정은 각각 교육학 이론에 근거한다.

| 이론 | 출처 | 구현 결정 |
|------|------|-----------|
| MISCA 피드백 모형 | Panadero & Lipnevich (2022) | 검증 기준 M1·M3~M5 설계. 피드백의 언어 품질이 아닌 교육적 효과성을 검증하는 기준 틀로 채택 |
| MAGIC 기준 | Jordan et al. (2025) | 검증 기준 C1~C5 설계. 피드백의 관련성·구체성·즉시 실행 가능성 등 품질 축 채택 |
| 근접발달영역(ZPD) | Vygotsky (1978) | 동적 가중치 설계 근거. 학생의 현재 수준에서 "조금 더" 도달 가능한 영역에 피드백 비중 집중 |
| Feed forward | Hattie & Timperley (2007) | M1 기준 설계. "Where to next?"를 제공하는 피드백만 feed forward로 인정. 현재 글 수정 조언(feed back)과 명확히 구분 |
| 형성 평가 | Black & Wiliam (1998) | 시스템 전체 목적. 총괄 평가(점수)가 아닌 학습 개선을 위한 피드백 생성 |

### MISCA → M1·M3~M5 조작적 정의

MISCA 모형의 5요소(Message, Implementation, Student, Context, Agents)를 검증 가능한 기준으로 조작화:

- **M3 (학년 적합성)** ← Student 요소: 피드백이 학생의 발달 수준·학년 기대치에 맞는가
- **M1 (feed forward)** ← Implementation 요소: 학생이 피드백을 다음 글쓰기에 실제로 적용할 수 있는가
- **M4 (과제 맥락 반영)** ← Context 요소: 피드백이 과제 지시문의 구체적 조건을 인식하고 있는가
- **M5 (영역별 분석의 충실성)** ← Message 요소: 피드백 메시지가 4개 영역을 가중치에 비례하여 다루는가

---

## 시도했다가 폐기한 방법들

### OpenAI GPT → Gemini 전환

초기 구현은 OpenAI GPT(`gpt-4o`)로 시작했다. ADK가 OpenAI API를 지원하지만 네이티브 통합이 아니어서 도구 호출 스키마 충돌이 발생했다. Google ADK가 Gemini 생태계에 최적화되어 있어 Gemini로 전환했다.

### FastAPI + SSE 웹 UI → Discord 봇

초기 인터페이스는 FastAPI 서버에 SSE(Server-Sent Events)로 파이프라인 진행 상황을 스트리밍하는 커스텀 웹 UI였다. 배포 복잡성과 로컬 서버 실행 의존성이 문제였다. Discord 봇으로 전환하면서 별도 서버 없이 슬래시 명령어로 테스트할 수 있게 됐다.

### ADK LlmAgent 매니저 → Python 하드코딩

설계 지침서의 Manager Pattern을 ADK `LlmAgent`로 구현했다. LlmAgent 매니저가 하위 에이전트를 `AgentTool`로 등록하고 순서대로 호출하는 방식이었으나, 도구 호출 후 텍스트 생성 없이 빈 응답을 반환하는 구조적 문제가 반복됐다. ADK LlmAgent는 도구 호출 결과를 최종 응답으로 간주하고 추가 텍스트를 생성하지 않았다. Python이 직접 각 단계를 순서대로 호출하는 방식으로 전환해 해결했다.

### py-hanspell → 직접 HTTP 호출

`py-hanspell`은 네이버 맞춤법 검사기의 비공식 래퍼 라이브러리다. API 변경에 취약하고 실제 운용 중 불안정한 동작이 확인됐다. 직접 HTTP 요청으로 교체하고 500자 초과 자동 분할과 graceful fallback을 추가했다.

### 교사 수동 가중치 입력 → LLM 자동 진단

초기 설계는 교사가 Discord 슬래시 명령어에서 4개 영역 가중치를 직접 입력하는 방식이었다. 실제 교육 현장에서 교사가 매번 가중치를 설정하는 것은 비현실적이고, 교사가 글을 미리 읽어야 한다는 전제가 시스템 목적과 어긋났다. LLM이 에세이를 읽고 취약 신호를 자동 진단해 가중치를 결정하는 방식으로 전환했다.

---

## 검증 기준 반복 개선 과정

검증 기준은 테스트를 거치며 세 차례 주요 개정됐다.

### 1차: 기호 강제 방식 (초기)

트리거 기준(C1·C2·M1·M4)의 결과를 `✗`/`✓` 기호로 강제 출력하도록 지시해 오탐을 줄이는 방식. 기준 자체는 추상적이었다.

**문제**: 거의 모든 피드백이 1회차에 모든 기준 충족. 기준이 너무 관대해 변별력이 없었다.

### 2차: 기준별 조작적 정의 추가

각 기준에 충족/미충족 예시와 핵심 테스트 질문을 추가했다.

- C1: "이 피드백을 다른 학생 글에 복붙해도 말이 되는가? → 된다면 미충족"
- M1: feed forward의 정의를 "다음 글쓰기를 위한 행동 지침"으로 명확화

**문제**: M1에서 "~이 필요합니다", "~했다면 좋았을 것입니다" 같은 표현을 LLM이 feed forward로 오인했다.

### 3차: MAGIC + MISCA 논문 기반 전면 재설계

Jordan et al. (2025)의 MAGIC 기준과 Panadero & Lipnevich (2022)의 MISCA 모형 논문을 직접 참고해 모든 기준을 재설계했다. 각 기준에 미충족 패턴을 명시적으로 열거하고, LLM Judge에게도 엄격 판단 원칙 4개를 별도로 부여했다.

**문제**: 중2 사회·초5 과학 배치 테스트 결과 트리거 통과율이 100%. 검증 루프가 사실상 무의미한 상태. 원인 분석:
- SYNTHESIS_PROMPT가 트리거 기준을 이미 충족하도록 생성을 지시하고 있어, 검증 에이전트는 합성이 지시를 따랐는지만 확인하는 수준
- 임계값 자체가 낮아서 "합성 지시를 따른 피드백"이 형식적으로 모든 기준을 통과

### 4차: 임계값 강화 및 LLM Judge 재정의 (현재)

| 기준 | 기존 임계값 | 강화된 임계값 |
|------|------------|--------------|
| C1 | 특정 내용 참조 2개 이상 | 참조 3개 이상 + 따옴표 직접 인용 1개 이상 필수 |
| C2 | 약점 1건 (위치+이유) | 약점 2건 이상, 각각 위치+이유 모두 필수 |
| M1 | "다음에는~" 형식이면 충족 | 이 에세이의 특정 약점과 연결된 지침만 충족. 일반 조언 미충족 |
| M4 | 조건 1개 참조면 충족 | 글쓰기 유형·주제 언급 불충분. 실제 조건(개수·독자·형식 등) 명시 인용 필수 |

LLM Judge를 체크리스트 채우는 역할에서 **에세이와 피드백을 함께 읽는 질적 독자**로 재정의:
- 에세이 실제 문장을 따옴표로 인용하며 서술
- 피드백이 이 에세이를 실제로 읽고 쓴 것인지를 복붙 테스트로 판단
- "의심스러우면 미충족" 원칙 추가
- ✓/✗는 서술형 분석의 결론으로만 배정 (기호 먼저 정하고 이유 끼워 맞추기 금지)

---

## 단계별 개발 과정

### 1단계: 초기 설계 및 뼈대 구축

**시작점**: MAFS_design_spec.pdf 설계 지침서 기반.  
Google ADK + Gemini(`gemini-2.0-flash`) 조합 선택.

**최초 아키텍처**
- ADK `LlmAgent` 기반 매니저 에이전트가 모든 하위 에이전트를 도구로 호출
- 교사가 Discord에서 4개 영역 가중치를 직접 슬라이더로 입력
- 맞춤법 검사: `py-hanspell` (네이버 맞춤법 래퍼)

**첫 번째 인터페이스**: FastAPI + SSE(Server-Sent Events) 커스텀 웹 UI

---

### 2단계: 주요 설계 변경 — LLM 백엔드 교체 및 오케스트레이션 전환

**문제 1: OpenAI → Gemini 전환**  
초기에 OpenAI GPT로 구현했다가 ADK와의 호환성 문제로 Gemini로 전환.  
ADK는 Google 생태계에 최적화되어 있어 Gemini가 자연스러운 선택이었음.

**문제 2: ADK LlmAgent 매니저가 빈 응답을 반환**  
LlmAgent 매니저에게 하위 에이전트 호출 후 텍스트를 생성하도록 지시했으나,
도구 호출 후 텍스트 생성 없이 빈 응답을 반환하는 구조적 문제가 반복됨.

**해결**: ADK LlmAgent 매니저 제거 → Python 하드코딩 오케스트레이션으로 전환

```
STEP 1: _llm(DIAGNOSIS_PROMPT)          ← 취약 신호 진단
STEP 2: _run_adk_agent(parallel_feedback) ← 4개 ADK 에이전트 병렬 실행
STEP 3: _llm(SYNTHESIS_PROMPT)          ← 통합 피드백 합성
STEP 4: 검증 루프 (검증 최대 3회 / 재합성 최대 2회)
```

ADK는 `ParallelAgent`의 병렬 실행에만 활용하고,
순서 제어는 Python이 직접 담당하는 혼합 구조.

**문제 3: 맞춤법 API**  
`py-hanspell`이 불안정하여 직접 HTTP 호출 방식으로 교체.  
500자 초과 시 자동 분할, graceful fallback 포함.

**인터페이스 변경**: FastAPI 웹 UI → Discord 봇으로 전환  
테스트 편의성과 배포 단순성을 고려한 결정.

---

### 3단계: 기능 고도화

**교사 가중치 입력 제거**  
초기에는 교사가 Discord에서 4개 영역 가중치를 직접 입력하는 방식이었으나,
실제로 교사가 매번 가중치를 설정하는 것은 비현실적.
→ LLM이 에세이를 읽고 자동으로 취약 신호를 진단해 가중치를 결정하는 방식으로 전환.

**DIAGNOSIS_PROMPT 설계**  
- 영역별 취약도 판단 기준을 체크 항목 4~5개로 구체화
- `HIGH / MEDIUM / LOW`를 절대 기준이 아닌 "다른 영역 대비 상대적 비교"로 정의
- 글쓰기 목적(설명문·설득문·감상문)별 체크 항목 분기

**SYNTHESIS_PROMPT 설계**  
- 학년별 문체 4단계 (초1~3 / 초4~6 / 중1~3 / 고1~3)
- 영역 이름 선언 금지 ("내용 영역에서는..." 같은 항목 나열 방식 금지)
- 가중치 X%인 영역은 피드백의 약 X% 분량 배분
- feed forward 마지막 문단 필수 (Hattie & Timperley 2007)

---

### 4단계: AI Hub 데이터 학습 파이프라인

**초기 데이터 범위 결정 (이후 변경됨)**  
AI Hub 데이터 중 중학교 국어 3개 폴더(`TL_3~5`)만 사용.  
이유: 연구 대상을 중학교 논술형 글쓰기로 한정.  
→ N=4,146

**2단계 파이프라인 구축**
1. `feedback_extractor.py`: AI Hub JSON → `feedback_db.jsonl` (에세이·피드백 추출)
2. `few_shot_builder.py`: `feedback_db.jsonl` → `manager_weight_context.json` + 도메인별 few-shot JSON 생성

**주입 방식**
- `manager_weight_context.json` → `DIAGNOSIS_PROMPT` 앞에 교차 검증 참고 데이터로 주입 (계산 기본값 아님)
- `few_shot_{domain}.json` → 각 서브에이전트 시스템 프롬프트에 자동 주입
- 파일 없으면 빈 문자열 → 원본 프롬프트만 사용 (graceful fallback)

---

### 5단계: 검증 기준 설계 및 재설계

**초기 검증 기준**  
트리거 기준(C1·C2·M1·M4)에 ✗/✓ 기호를 강제해 오탐을 줄이는 방식으로 시작.

**문제: 검증이 너무 관대함**  
테스트 결과 거의 모든 피드백이 1회차에 모든 기준 충족.  
feed forward가 없거나 약해도 M1 통과, 일반론적 피드백도 C1 통과.

**검증 기준 전면 재설계** (Jordan et al. 2025 MAGIC + Panadero & Lipnevich 2022 MISCA 기반)

| 기준 | 재정의 | 핵심 테스트 |
|------|--------|------------|
| C1 | 에세이 특정성 | 이 피드백을 다른 학생 글에 복붙해도 말이 되는가? → 된다면 미충족 |
| C2 | 약점 구체성 | (1) 어떤 부분인지, (2) 왜 문제인지 두 가지 명시 여부 |
| C3 | 강점 근거 | 구체적 내용 인용 없는 "노력이 느껴집니다" = 미충족 |
| C4 | 즉시 실행 가능성 | 구체적 행동 동사 포함 여부 |
| C5 | 학습 성장 전제 | 강점 0개 + feed forward 0개 = 미충족 |
| M3 | 학년 적합성 | 어휘·문장·어조·기대 수준 4가지 축 |
| M1 | feed forward | "~이 필요합니다" = 미충족. "다음 글을 쓸 때는 ~해 보세요" = 충족 |
| M4 | 과제 맥락 반영 | 지시문 읽지 않아도 쓸 수 있는 피드백인가? → 그렇다면 미충족 |
| M5 | 영역별 분석의 충실성 | 완전성(4개 영역 모두 언급) + 비례성(가중치 대비 분량) |

**M1 혼동 원인 및 해결**  
"~이 필요합니다", "~했다면 좋았을 것입니다" 같은 표현을 LLM이 feed forward로 오인.  
→ 미충족 패턴 목록을 M1 판단 원칙에 명시적으로 열거.

---

### 6단계: Refine 루프 아키텍처 개선

**초기 Refine 구조**  
검증 미충족 시 단순히 검증 결과를 SYNTHESIS에 붙여 재합성.  
→ sub_feedback(하위 에이전트 원본 분석)은 그대로인 채 합성만 반복.

**문제: 2회 refine 후에도 같은 기준 미충족**  
C1·C2·M4 같은 기준은 합성 단계가 아닌 하위 에이전트 분석 단계의 문제.  
합성만 반복해도 원본 재료가 바뀌지 않으므로 개선 불가.

**해결: 미충족 기준별 책임 분리**

| 미충족 기준 | 원인 | 해결 |
|------------|------|------|
| C1 (에세이 특정성) | 하위 에이전트가 일반론적 분석 | parallel_feedback 재실행 (구체적 인용 지시 포함) |
| C2 (약점 구체성) | 하위 에이전트가 단정만 제시 | parallel_feedback 재실행 (부분+이유 명시 지시) |
| M4 (과제 맥락) | 하위 에이전트가 지시문 무시 | parallel_feedback 재실행 (지시문 인용 지시) |
| M1 (feed forward) | 합성 단계에서 누락 | 합성 호출 시 feed-forward 강제 지시 추가 |

새 Refine 흐름:
```
미충족 기준 분류
  → C1/C2/M4: parallel_feedback 재실행 → sub_feedback 교체 → 재합성
  → M1: 기존 sub_feedback 유지 + 합성 지시에 feed-forward 추가 → 재합성
```

---

## 주요 의사결정 요약

| 결정 | 선택 | 이유 |
|------|------|------|
| LLM 백엔드 | Gemini (ADK 네이티브) | ADK와 호환성 최적 |
| 오케스트레이션 | Python 하드코딩 | ADK LlmAgent 매니저 빈 응답 문제 |
| 인터페이스 | Discord 봇 (개발용) + batch_run.py (평가용) | 테스트 편의성, 배포 단순성 |
| 교사 가중치 | LLM 자동 진단으로 대체 | 교사가 매번 설정하는 건 비현실적 |
| 가중치 계산 기준 | 25% 기본값 × 취약도 계수, 전문가 데이터는 참고 전용 | 전문가 데이터 앵커링 시 모두 LOW여도 14%/40%/24%/22%로 고정되는 버그 |
| 데이터 범위 | 초5~중3 국어·사회·과학 전체 (N=16,010) | cross-prompt 일반화, RQ3(교과별 차이) 검증을 위해 확장 |
| 맞춤법 API | speller.town (부산대 AI 공개 REST) | 네이버 비공식 파싱은 HTML 구조 변경 시 중단 위험 |
| 검증 기준 | MAGIC + MISCA 논문 기반 | 교육적 효과성 중심, 언어 품질 중심이 아님 |
| Refine 전략 | 기준별 책임 분리 | 원인이 다른 기준을 동일 방법으로 재시도해도 개선 없음 |
| content.py 루브릭 | AI Hub 실제 루브릭 기반 목적별 재설계 | 기존 직관적 분기가 설득문 근거 개수 측정 누락 등 불일치 확인 |
| purpose 파이프라인 | DIAGNOSIS 출력 명시 + pipeline.py 파라미터 추가 | 과제 지시문만으로 목적 오판 방지, 배치 시 AI Hub 메타데이터 활용 |
| 서브에이전트 학습 방식 | zero-shot (few-shot 제거) | 자동 선별 예시가 전부 최저점·금지 패턴 — 오히려 품질 저하 위험 |
| 검증 기준 임계값 | 강화 (C1·C2·M1·M4) | 구 기준으로 100% 통과 → 검증 루프가 의미 없는 상태였음 |
| Refine 라우팅 | LLM 기반 (REFINE_MANAGER_PROMPT) | 논문 기술("매니저가 판단")과 구현이 일치해야 함. Python 하드코딩은 LLM 기반이 아님 |
| SYNTHESIS_PATCH | 해당 영역만 교체 (SYNTHESIS_PATCH_PROMPT) | 전체 재합성 시 기존 충족 기준이 stochastic하게 깨질 위험 |
| 공유 synthesis | synthesis_0 B조건 재사용 | 독립 실행 간 stochastic 노이즈가 A<B 역전 유발. 동일 출발점 비교 필수 |
| 파이프라인 분리 | run_mafs_synthesis() / run_mafs_verify() | RQ2에서 B=synthesis_0, A=verify(sr) 패턴을 위해 단계 분리 필요 |

---

---

### 8단계: 검증 기준 강화 및 few-shot 제거 (zero-shot 전환)

**검증 기준 강화** (§검증 기준 반복 개선 과정 4차 참조)

**few-shot 예시 검토 및 제거**

`few_shot_builder.py`가 자동 선별한 예시들을 수동 검토한 결과:
- 4개 도메인 모두 avg_score=1(최저점) 에세이만 선별됨 — 중간·우수 글 피드백 패턴 학습 불가
- 전문가 피드백 자체에 "~해야 합니다", "~필요합니다" 같은 표현이 가득 — M1 기준에서 미충족 처리해야 하는 패턴을 오히려 강화

→ 서브에이전트 few-shot 주입 전면 제거, **zero-shot으로 전환**  
→ 이미 상세하게 작성된 시스템 프롬프트(루브릭·판단 기준·출력 형식)만으로 운영  
→ `few_shot_{task,content,organization,expression}.json` 파일 삭제 (더 이상 사용하지 않음)  
※ `few_shot_builder.py`는 `manager_weight_context.json` 생성에 계속 사용되므로 유지

---

### 7단계: Cross-prompt 확장 및 프롬프트 재설계

**데이터 범위 확장 결정**  
연구 목적을 중학교 국어 한정 → 초5~중3 국어·사회·과학 전체로 변경.  
RQ3(교과별 피드백 품질 차이)를 추가하면서 사회·과학 데이터가 필수가 됨.  
→ `feedback_extractor.py` 기본값 변경: 중학교 국어 3폴더 → `None`(전체 탐색)  
→ `feedback_db.jsonl` 재구축: N=4,146 → N=16,010

**content.py 목적별 프레임 분기 (1차)**  
기존 설명문 전용 프레임(명료성·구체성·특성개수)을 설득문·감상문에 그대로 적용하는 문제 발견.  
→ 목적별 루브릭 분기를 추가했으나 기준이 직관적으로 도출된 것이었음.

**verification.py M3 기준 일반화**  
"중학생 수준에 맞는가" → "해당 학년 학생 수준에 맞는가"  
초5~초6 기대 수준 미스매치 예시 추가.

**연구 문제 확정 (RQ1~RQ3)**  
- RQ1: MAFS vs 단일 LLM (C1~C5·M1~M5 점수 비교)
- RQ2: 동적 가중치 적용 효과 (적용·미적용 비교)
- RQ3: 교과별 피드백 품질 차이 (국어·사회·과학·학교급)

---

---

### 9단계: content.py AI Hub 루브릭 기반 전면 재설계 + purpose 파이프라인 연결

**문제: content.py 목적별 루브릭이 AI Hub 실제 기준과 불일치**  
1차 분기는 직관적으로 설계됐는데, AI Hub 실제 루브릭 데이터를 확인한 결과 기준이 달랐다.

- **설득문**: AI Hub 기준은 주장의 명료성(합리성·참신성) + 주장의 적절성(논리성·독창성) + 근거의 타당성(근거 개수 기반)
- **친교및정서**: 명료성·구체성·적절성(정서표현 언어 개수 기반)

→ content.py를 AI Hub 실제 루브릭으로 전면 재설계.  
→ 세 목적 모두 3항목 구조로 통일. 설명문·설득문·친교및정서 모두 `count_features` 재활용(카운팅 대상만 다름).

**문제: 서브 에이전트가 목적을 추론해야 함**  
DIAGNOSIS_PROMPT가 목적을 판단하지만 출력에 명시하지 않아 서브 에이전트가 task_prompt에서 스스로 추론해야 했다.

→ DIAGNOSIS 출력 형식에 `글쓰기 목적: <설명문/설득문/친교및정서>` 추가.  
→ `pipeline.py`에 `purpose: str = ""` 파라미터 추가.  
→ `batch_run.py`에서 AI Hub 메타데이터의 `purpose` 필드를 `run_mafs()`에 전달.  
→ base_input에 `[글쓰기 목적 힌트]` 섹션으로 포함 — DIAGNOSIS가 확인 후 출력에 반영.

**의사결정 근거**  
| 결정 | 이유 |
|------|------|
| content.py 루브릭을 AI Hub 기준으로 교체 | 기존 기준은 직관적 도출이었고 설득문의 "근거 개수" 측정이 빠져 있었음 |
| purpose를 pipeline에 명시적으로 전달 | 과제 지시문만으로 목적이 불분명한 경우 오판 방지 |
| count_features를 세 목적 모두 재활용 | 카운팅 대상(특성/근거/정서표현 언어)만 다를 뿐 중복 제거 로직은 동일 |
| RAG 파이프라인에서 제거 | MAFS만 Training 전문가 피드백을 참조하면 Baseline과 비교 조건 불균형. 취약 영역 집중은 DIAGNOSIS 동적 가중치로 달성 |
| 전 모델 gemini-2.5-flash로 통일 | gemini-2.5-pro 접근 403 오류 + 비용 절감. MODEL·SUB_MODEL·JUDGE_MODEL 모두 flash |
| LLM 판사 기준 재정비 | 파일럿 120건 분포 분석 결과: C3·M3 변별력 0 → C3 기준 강화, C4 "즉시 실행 가능성" → "분석 근거 수치화"로 재정의, C1 직접 인용 2→3개 |
| 검증 피드백 → 재합성 전달 추가 | 기존엔 미충족 기준명만 전달, 재합성이 이유를 몰라 개선 효과 미미 → verification 전문을 refine_input에 포함 |

---

---

### 10단계: LLM 기반 매니저 라우팅 + 공유 synthesis 설계 (2026-04-27)

#### RQ2 v2·v3 분석 결과

RQ2 v2(전체 재합성)와 v3(PATCH 방식) 모두 A<B(검증 후 악화) 케이스가 21~23% 존재했다.

**근본 원인 분석:**
- A조건(검증 포함)과 B조건(검증 없음)이 완전히 독립적인 LLM 실행에서 나온 피드백을 비교
- 검증 없이도 우연히 품질 좋은 B피드백이 생성되면 검증이 오히려 역효과처럼 보임
- 개선 방법이 아닌 stochastic 노이즈가 A<B를 유발하는 것이 문제

**해결: 공유 synthesis 설계**
- `run_mafs_synthesis()`로 synthesis_0를 1회 생성
- B조건 = synthesis_0 그대로 사용
- A조건 = 동일한 synthesis_0에 `run_mafs_verify()` 적용
- 동일 출발점에서 검증 효과만을 측정 → A<B 역전 구조적 차단

**RQ1과 RQ2 일관성 문제:**
- RQ1에서 쓴 MAFS 피드백과 RQ2에서 쓴 MAFS 피드백이 서로 다른 실행에서 나온 것
- 해결: RQ1 출력에 `synthesis_0` 필드 추가 → RQ2가 `--reuse_rq1`로 A조건·synthesis_0 모두 재사용

#### Refine 루프를 Python 하드코딩에서 LLM 기반으로 전환

**배경:** 논문에 "매니저가 검증 결과를 판단해 하위 에이전트를 선택적으로 재호출"이라고 기술할 것이라면 실제로 LLM이 판단해야 함. 기존 구현은 Python if-else로 "C1/C2/M4 → parallel_feedback, M1 → 합성 지시 추가" 형태로 하드코딩되어 있었고 이는 LLM 기반 매니저가 아니었음.

**구현:**
- `REFINE_MANAGER_PROMPT`: 검증 결과 전문 + 현재 합성 + 에세이 + 과제 지시문 입력. LLM이 어떤 에이전트를 재실행할지, 각 에이전트에게 무슨 지시를 줄지 스스로 결정. 출력 형식: `재실행: task_agent, content_agent` 헤더 + 에이전트별 상세 지시.
- `_parse_refine_decision()`: 출력 파싱 → `{에이전트명: 지시문}` dict
- `SYNTHESIS_PATCH_PROMPT`: 기존 합성 + 재실행 에이전트 새 분석 → 해당 영역만 교체. 전체 재합성 금지 명시.
- REFINE_MANAGER_PROMPT 제약: "반드시 최소 1개 이상 선택. '없음' 허용 안 됨" 추가 (파싱 실패 방지).

**의사결정 근거:**

| 결정 | 이유 |
|------|------|
| LLM 기반 라우팅 | 논문에서 "매니저 에이전트가 판단"으로 기술 예정. 하드코딩은 설계 의도와 불일치 |
| SYNTHESIS_PATCH_PROMPT 분리 | 전체 재합성은 괜찮은 영역도 stochastic하게 변경 → 기존에 충족하던 기준이 깨질 위험 |
| 공유 synthesis | 독립 실행 간 stochastic 노이즈가 연구 결과를 오염. 동일 출발점에서 비교해야 검증 효과 측정 가능 |
| synthesis_0 RQ1 저장 | RQ1·RQ2를 다른 날 실행해도 동일한 MAFS 피드백을 공유하려면 RQ1 결과에 저장 필요 |

---

## 완료된 본 실험 (200건 — 국어·사회 10폴더, 과학 제외)

- [x] 층화 샘플링: `sample_dataset.py --n_per_folder 20 --seed 42 --output sampled_rq3.txt` (과학 폴더 제외)
- [x] RQ1 실행: `rq1_instruction.py --file_list sampled_rq3.txt --output rq1_200.jsonl`
- [x] RQ2 실행: `rq2_design_elements.py --file_list sampled_rq3.txt --reuse_rq1 rq1_200.jsonl --output rq2_200.jsonl`
- [x] RQ3: rq1_200.jsonl condition_a 점수 그룹 비교
- [x] RQ2 subgroup analysis: rq1_200.jsonl에서 verify_rounds >= 2 케이스(70건)만 추출하여 synthesis_0 vs condition_a 대응표본 t-검정
- [x] Jamovi용 CSV 변환: `export_csv.py --rq1 rq1_200.jsonl --rq2 rq2_200.jsonl --rq3 rq3_200.jsonl --out_dir results/csv`
- [x] Jamovi 통계 분석: RQ1·RQ2 대응표본 t-검정 + Cohen's d / RQ3 Two-way ANOVA 5×2 + partial η² — 실제 결과 수치는 논문 IV장 참조

# 외부 API 및 의존성 정리

## 1. Google Gemini API (필수)

| 항목 | 내용 |
|------|------|
| 용도 | 모든 LlmAgent의 언어 모델 (기본값: `gemini-2.5-flash`) |
| 키 발급 | https://aistudio.google.com/apikey |
| 설정 방법 | `.env` 파일에 `GOOGLE_API_KEY=발급받은_키` 입력 |
| 모델 변경 | `.env`에서 `GEMINI_MODEL=gemini-2.5-flash` 등으로 변경 가능 |
| 사용 에이전트 | 매니저·과제수행·내용·조직·표현·검증·LLM Judge 전체 |
| 요금 | Gemini 2.0 Flash: 무료 티어 있음 (분당 요청 수 제한) |

---

## 2. speller.town (jhaemin/speller-api) — 맞춤법 검사 (표현 에이전트)

| 항목 | 내용 |
|------|------|
| 용도 | 학생 에세이 맞춤법·띄어쓰기 오류 탐지 (`tools/spell_checker.py`) |
| 방식 | `requests`로 직접 HTTP POST 호출 (`SPELLER_URL = "https://speller.town"`), 재시도 없음 |
| 엔진 | 부산대학교 인공지능연구실과 (주)나라인포테크의 한국어 맞춤법/문법 검사기를 활용한 오픈소스 API 서버 |
| 소스 | https://github.com/jhaemin/speller-api |
| 제약 사항 | - 개인 오픈소스 프로젝트이므로 호스팅 중단·도메인 만료 위험 있음 <br>- 500자 분할 로직 없음(단일 POST 요청) <br>- API 키 불필요 |
| 실패 처리 | `status: "error"` 반환 후 graceful fallback (어법 피드백 생략, 표현 에이전트 프롬프트에 명시) |

---

## 3. Google ADK — google-adk (프레임워크)

| 항목 | 내용 |
|------|------|
| 용도 | 다중 에이전트 시스템 프레임워크 |
| 설치 | `pip install google-adk` |
| 공식 문서 | https://adk.dev |
| 주요 사용 클래스 | `LlmAgent`, `ParallelAgent`, `AgentTool` |
| 로컬 UI | `adk web` 명령어로 브라우저 UI 실행 |

---

## 향후 연동 예정 (현재 미구현)

| 항목 | 용도 | 비고 |
|------|------|------|
| ADK ArtifactService | 피드백 초안 저장·로드 | 현재 session.state로 대체 |

※ RAG(ChromaDB/FAISS + AI Hub 전문가 피드백)는 연구 설계 공정성 문제로 파이프라인에서 제거. MAFS만 Training 정답 예시를 참조하면 Baseline과 비교 조건이 불균형해진다.

---

## 설치 순서 요약

```bash
# 1. 가상환경 생성 (권장)
python -m venv .venv
.venv\Scripts\activate  # Windows

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 설정
copy .env.example .env
# .env 파일에서 GOOGLE_API_KEY 값 입력

# 4. 실행
cd <저장소 루트>
adk web
```

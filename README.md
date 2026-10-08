# MAFS: Multi-Agent Writing Feedback System

초등학교 5학년~중학교 3학년 학생의 논술형 글에 피드백을 자동으로 생성하는 다중 에이전트 시스템입니다. Google ADK와 Gemini(`gemini-2.5-flash`)로 구현했습니다.

## 피드백 예시

[`examples/`](examples/) 폴더에서 MAFS가 생성한 피드백 전문을 볼 수 있습니다.

| 파일 | 내용 |
|---|---|
| [`sample_feedback_AB.md`](examples/sample_feedback_AB.md) | RQ1: MAFS(조건 A)와 최소 지침 단일 LLM(조건 B)의 피드백 비교 |
| [`sample_feedback_AC.md`](examples/sample_feedback_AC.md) | RQ2: 검증·재생성 후 최종본(조건 A)과 검증 전 초안(조건 C)의 피드백 비교 |

학생 글은 AI Hub 데이터의 재배포 제한 때문에 전문을 싣지 않았습니다. 피드백에서 인용한 구절만 발췌해 두었습니다.

## 시스템 구조

1. **진단**: 글의 취약 영역을 진단하고, 영역별 가중치와 글쓰기 목적(설명·설득·친교및정서)을 정합니다.
2. **병렬 분석**: 과제수행·내용·조직·표현 4개 에이전트가 각 영역을 분석합니다.
3. **종합**: 4개 영역의 분석을 가중치에 맞춰 하나의 피드백으로 합칩니다.
4. **검증**: MISCA 기준으로 피드백 품질을 검증합니다. 기준을 충족하지 못하면 해당 영역 에이전트만 다시 실행해 고칩니다(검증 최대 3회, 재생성 최대 2회).

자세한 설계는 [`mafs/design.md`](mafs/design.md)에 있습니다.

## 실행

```bash
pip install -r mafs/requirements.txt
cp mafs/.env.example mafs/.env   # GOOGLE_API_KEY 입력
```

평가에 사용한 데이터는 [AI Hub 논술형 글쓰기 평가 데이터](https://www.aihub.or.kr/)입니다. 저장소에는 포함하지 않았으니 AI Hub에서 직접 내려받아야 합니다.

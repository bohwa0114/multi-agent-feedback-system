"""
맞춤법 검사 도구 (Korean Spell Checker)

speller.town (부산대 AI 기반 공개 REST API)을 사용한다.
LLM 단독으로 맞춤법·띄어쓰기 오류를 일관되게 탐지하면 hallucination 위험이 있어
API로 객관적 오류 목록을 확보하고, LLM은 어휘·문맥 판단에만 집중하도록 역할을 분리한다.

API: POST https://speller.town
Request:  {"text": "검사할 텍스트"}
Response: {"suggestions": [{"text": "원문", "candidates": ["교정안"], ...}, ...]}
"""

import asyncio


SPELLER_URL = "https://speller.town"


async def check_spelling(text: str) -> dict:
    """speller.town API로 맞춤법 오류를 탐지하고 결과를 반환한다.

    Args:
        text: 검사할 에세이 텍스트

    Returns:
        {
            "original": str,
            "corrected": str,
            "error_count": int,
            "corrections": dict,   # {원문: 교정안} (첫 번째 후보)
            "status": "ok" | "error",
            "message": str
        }
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _check_sync, text)
        return result
    except Exception as e:
        return {
            "original": text,
            "corrected": text,
            "error_count": 0,
            "corrections": {},
            "status": "error",
            "message": f"맞춤법 검사 중 오류 발생: {str(e)}",
        }


def _check_sync(text: str) -> dict:
    """speller.town API 동기 호출 (run_in_executor에서 사용)."""
    try:
        import requests
    except ImportError:
        return {
            "original": text,
            "corrected": text,
            "error_count": 0,
            "corrections": {},
            "status": "error",
            "message": "requests 패키지가 없습니다. pip install requests 를 실행하세요.",
        }

    try:
        resp = requests.post(
            SPELLER_URL,
            json={"text": text},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {
            "original": text,
            "corrected": text,
            "error_count": 0,
            "corrections": {},
            "status": "error",
            "message": f"API 호출 실패: {str(e)}",
        }

    suggestions = data.get("suggestions", [])
    corrections = {}
    for s in suggestions:
        original_token = s.get("text", "")
        candidates = s.get("candidates", [])
        if original_token and candidates:
            corrections[original_token] = candidates[0]

    # corrected: 원문에서 오류 토큰을 첫 번째 교정안으로 순서대로 치환
    corrected = text
    for orig, fixed in corrections.items():
        corrected = corrected.replace(orig, fixed, 1)

    error_count = len(suggestions)
    return {
        "original": text,
        "corrected": corrected,
        "error_count": error_count,
        "corrections": corrections,
        "status": "ok",
        "message": f"검사 완료: {error_count}개 오류 발견",
    }

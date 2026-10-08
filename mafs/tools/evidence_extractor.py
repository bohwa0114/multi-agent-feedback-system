"""
근거 문장 추출 도구 (Evidence Sentence Extractor)

LLM이 단독으로 "어느 문장이 근거인지" 출력하면 불안정하고 hallucination 위험이 있어,
에세이를 문장 단위로 분리·인덱싱하여 LLM이 번호로 참조할 수 있도록 구조화한다.
"""

import re


async def extract_evidence_sentences(essay: str, criteria: str) -> dict:
    """에세이를 문장 단위로 분리하여 인덱스와 함께 반환한다.

    Args:
        essay: 학생 에세이 전문
        criteria: 근거를 찾는 기준 (예: "조건 충족 여부", "명료성 부족 구간")

    Returns:
        {
            "sentences": [{"index": int, "text": str}, ...],
            "total": int,
            "criteria": str
        }
    """
    # 한국어 문장 분리: 마침표·느낌표·물음표 기준, 줄바꿈도 분리 경계로 처리
    raw = re.split(r"(?<=[.!?])\s+|(?<=。)\s*|\n+", essay.strip())
    sentences = [s.strip() for s in raw if s.strip()]

    return {
        "sentences": [{"index": i, "text": s} for i, s in enumerate(sentences)],
        "total": len(sentences),
        "criteria": criteria,
    }

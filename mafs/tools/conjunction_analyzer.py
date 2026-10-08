"""
접속어·연결어 분석 도구 (Korean Conjunction Analyzer)

LLM이 에세이 전체를 읽어도 접속어 빈도·다양성을 수치로 일관되게 산출하기 어렵다.
Python 딕셔너리 매칭으로 객관적 수치를 확보하고 LLM이 이를 참고하여 연결성 판단에 활용한다.
"""

# 한국어 접속어 목록 (별도 라이브러리 없이 딕셔너리로 직접 정의)
CONJUNCTIONS: dict[str, list[str]] = {
    "순접": ["그리고", "또한", "게다가", "더불어", "아울러", "뿐만 아니라"],
    "역접": ["그러나", "하지만", "반면에", "반면", "그렇지만", "그럼에도", "그럼에도 불구하고"],
    "인과": ["따라서", "그러므로", "왜냐하면", "그래서", "그 결과", "그 때문에", "이로 인해"],
    "예시": ["예를 들어", "예컨대", "가령", "이를테면"],
    "전환": ["그런데", "한편", "그렇다면", "그렇다고", "어쨌든", "그건 그렇고"],
    "양보": ["물론", "비록", "설령", "설사", "비록 ~지만"],
}


async def analyze_conjunctions(text: str) -> dict:
    """한국어 접속어 유형별 빈도·다양성 수치를 산출한다.

    Args:
        text: 분석할 에세이 텍스트

    Returns:
        {
            "by_type": {
                유형명: {"found": [발견된 접속어 목록], "count": int}
            },
            "total_count": int,       # 전체 접속어 등장 횟수
            "diversity": int,         # 사용된 유형 수 (0~6)
            "dominant_type": str,     # 가장 많이 사용된 유형 (없으면 None)
            "interpretation": str     # 간단한 해석 텍스트
        }
    """
    by_type: dict[str, dict] = {}
    total_count = 0

    for conj_type, words in CONJUNCTIONS.items():
        found = []
        for word in words:
            # 단어 경계 없이 단순 포함 여부로 매칭 (한국어 특성상 공백 기준 불안정)
            count = text.count(word)
            found.extend([word] * count)
        by_type[conj_type] = {"found": list(set(found)), "count": len(found)}
        total_count += len(found)

    used_types = [t for t, v in by_type.items() if v["count"] > 0]
    diversity = len(used_types)

    dominant_type = None
    if used_types:
        dominant_type = max(used_types, key=lambda t: by_type[t]["count"])

    # 해석 생성
    if total_count == 0:
        interpretation = "접속어가 전혀 사용되지 않았습니다."
    elif diversity == 1:
        interpretation = f"'{dominant_type}' 유형 접속어만 반복 사용되고 있습니다. 다양한 유형의 접속어 활용이 필요합니다."
    elif diversity <= 2:
        interpretation = f"접속어 유형이 {diversity}가지로 다소 단조롭습니다."
    else:
        interpretation = f"접속어 유형이 {diversity}가지로 비교적 다양하게 사용되었습니다."

    return {
        "by_type": by_type,
        "total_count": total_count,
        "diversity": diversity,
        "dominant_type": dominant_type,
        "interpretation": interpretation,
    }

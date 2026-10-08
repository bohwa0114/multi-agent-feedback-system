"""
특성 카운팅 도구 (Feature Counter)

내용 루브릭이 '설명 대상 특성 개수' 기반(4개↑=5점, 3개↑=4점, 2개↑=3점 등)이라
LLM 단독 카운팅은 주관적·불일관하다.
LLM이 특성 후보 목록을 추출하면, 이 도구가 중복 제거 후 객관적 개수를 산출한다.
"""


async def count_features(feature_candidates: list[str]) -> dict:
    """LLM이 추출한 설명 대상 특성 후보 목록을 받아 중복 제거 후 개수를 반환한다.

    Args:
        feature_candidates: LLM이 에세이에서 추출한 설명 대상 특성 문자열 목록
                            예: ["빠른 속도", "경제성", "빠른 이동 속도", "친환경"]

    Returns:
        {
            "count": int,           # 중복 제거 후 특성 개수
            "features": list[str],  # 중복 제거된 특성 목록
            "threshold_met": bool,  # 기준치(3개) 이상 여부
            "score_hint": str       # 루브릭 점수 힌트
        }
    """
    unique_features = list(dict.fromkeys(
        f.strip() for f in feature_candidates if f.strip()
    ))
    count = len(unique_features)

    if count >= 4:
        score_hint = "5점 수준 (특성 4개 이상)"
    elif count >= 3:
        score_hint = "4점 수준 (특성 3개 이상)"
    elif count >= 2:
        score_hint = "3점 수준 (특성 2개 이상)"
    elif count >= 1:
        score_hint = "2점 수준 (특성 1개)"
    else:
        score_hint = "1점 수준 (특성 없음)"

    return {
        "count": count,
        "features": unique_features,
        "threshold_met": count >= 3,
        "score_hint": score_hint,
    }

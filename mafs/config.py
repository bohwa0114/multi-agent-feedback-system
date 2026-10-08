"""MAFS 전역 설정.

MODEL      : 진단·합성·검증 에이전트용
SUB_MODEL  : 4개 분석 에이전트용 (병렬 실행 시 RPM 여유 확보)
"""

import os

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SUB_MODEL = os.getenv("GEMINI_SUB_MODEL", "gemini-2.5-flash")

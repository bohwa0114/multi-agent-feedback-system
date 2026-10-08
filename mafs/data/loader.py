"""AI Hub 논술형 글쓰기 평가 데이터 로더.

데이터 출처: AI Hub 논술형 글쓰기 평가 데이터 (dataSetSn=71819)

원천 데이터 (CSV, 01.원천데이터/TS_...):
  - 학생 에세이·과제 지시문·학년만 포함. 전문가 피드백 없음.
  - 연구 평가용 입력으로 사용 (RQ1~RQ3).

라벨링 데이터 (JSON, 02.라벨링데이터/TL_...):
  - 전문가 피드백·루브릭 점수 포함. 학습 데이터 구축 전용.
  - few_shot_builder.py / feedback_extractor.py 에서만 사용.
"""

import json
import os
from pathlib import Path


# 프로젝트 루트 기준 데이터 디렉터리
DATA_ROOT = Path(__file__).parent.parent.parent / "26.논술형_글쓰기_평가_데이터"
SOURCE_DIR = DATA_ROOT / "3.개방데이터" / "1.데이터" / "Training" / "01.원천데이터"
LABEL_DIR  = DATA_ROOT / "3.개방데이터" / "1.데이터" / "Training" / "02.라벨링데이터"


def extract_subject_from_folder(folder_name: str) -> str:
    """폴더명에서 교과를 추출한다.

    Args:
        folder_name: 예) "TS_1._초5_1._국어" 또는 "TL_3._중1_3._사회"

    Returns:
        교과명 (예: "국어", "사회", "과학"). 추출 실패 시 빈 문자열.
    """
    parts = folder_name.split("_")
    if parts:
        last = parts[-1].strip(".")
        if last in ("국어", "사회", "과학"):
            return last
    return ""


def load_essay_from_json(json_path: str) -> dict:
    """AI Hub 라벨링 JSON 파일에서 에세이 데이터를 추출한다.

    Args:
        json_path: JSON 파일 절대 경로

    Returns:
        {
            "essay_text": str,   # 학생 에세이 전문
            "prompt": str,       # 과제 지시문
            "grade": str,        # 학년 (예: "중1")
            "subject": str,      # 과목 (예: "국어")
            "purpose": str,      # 글쓰기 목적 (예: "설명", "설득", "친교 및 정서")
        }
    """
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    eq = data.get("essay_question", {})
    essay_text = data.get("essay_answer", {}).get("text", "")
    prompt = eq.get("prompt", "")
    grade = eq.get("grade", "")
    subject = eq.get("subject", "")
    purpose = eq.get("purpose", "")

    return {
        "essay_text": essay_text,
        "prompt": prompt,
        "grade": grade,
        "subject": subject,
        "purpose": purpose,
    }


def list_available_samples(grade_folder: str | None = None) -> list[str]:
    """사용 가능한 JSON 샘플(라벨링 데이터) 파일 경로 목록을 반환한다.

    Args:
        grade_folder: 특정 학년 폴더명 (예: "TL_3._중1_1._국어"). None이면 전체.

    Returns:
        JSON 파일 경로 목록
    """
    if not LABEL_DIR.exists():
        return []

    if grade_folder:
        search_dir = LABEL_DIR / grade_folder
        folders = [search_dir] if search_dir.exists() else []
    else:
        folders = [d for d in LABEL_DIR.iterdir() if d.is_dir()]

    json_files = []
    for folder in folders:
        json_files.extend(str(p) for p in folder.glob("**/*.json"))

    return sorted(json_files)


def list_available_csv_samples(grade_folder: str | None = None) -> list[str]:
    """사용 가능한 CSV 샘플(원천 데이터) 파일 경로 목록을 반환한다.

    원천 데이터(01.원천데이터)는 전문가 피드백이 없는 순수 학생 글쓰기 데이터.
    연구 평가(RQ1~RQ3) 입력으로 사용한다.

    Args:
        grade_folder: 특정 학년 폴더명 (예: "TS_3._중1_1._국어"). None이면 전체.

    Returns:
        CSV 파일 경로 목록
    """
    if not SOURCE_DIR.exists():
        return []

    if grade_folder:
        search_dir = SOURCE_DIR / grade_folder
        folders = [search_dir] if search_dir.exists() else []
    else:
        folders = [d for d in SOURCE_DIR.iterdir() if d.is_dir()]

    csv_files = []
    for folder in folders:
        csv_files.extend(str(p) for p in folder.glob("**/*.csv"))

    return sorted(csv_files)


def load_sample(index: int = 0, grade_folder: str | None = None) -> dict:
    """사용 가능한 샘플 중 하나를 로드한다.

    Args:
        index: 샘플 인덱스 (기본값: 0 = 첫 번째 샘플)
        grade_folder: 특정 학년 폴더명 (None이면 전체에서 선택)

    Returns:
        load_essay_from_json()와 동일한 형식
    """
    samples = list_available_samples(grade_folder)
    if not samples:
        raise FileNotFoundError(
            f"데이터 파일을 찾을 수 없습니다. 경로를 확인하세요: {LABEL_DIR}"
        )
    if index >= len(samples):
        raise IndexError(f"인덱스 {index}가 범위를 초과합니다. 최대: {len(samples) - 1}")

    return load_essay_from_json(samples[index])


def parse_essay_csv(text: str) -> dict:
    """AI Hub 논술형 CSV 텍스트에서 지시문·학년·에세이를 추출.

    Args:
        text: CSV 파일 전체 텍스트

    Returns:
        {"prompt": str, "grade": str, "essay": str}
    """
    lines = text.splitlines()
    result = {"prompt": "", "grade": "중1", "essay": ""}

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line == "글쓰기 지시문":
            for j in range(i + 1, len(lines)):
                candidate = lines[j].strip()
                if candidate and candidate not in ("", "학생 정보", "지시문 정보", "학생 답변"):
                    result["prompt"] = candidate
                    break

        elif line.startswith("학년,"):
            result["grade"] = line.split(",", 1)[1].strip()

        elif line == "학생 답변":
            essay_lines = []
            for j in range(i + 1, len(lines)):
                essay_lines.append(lines[j])
            raw = "\n".join(essay_lines).strip()
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1].replace('""', '"')
            result["essay"] = raw
            break

        i += 1

    return result


if __name__ == "__main__":
    # 빠른 테스트: 첫 번째 샘플 로드 및 출력
    try:
        sample = load_sample(0)
        print("=== 샘플 로드 성공 ===")
        print(f"학년: {sample['grade']}, 과목: {sample['subject']}")
        print(f"에세이 길이: {len(sample['essay_text'])}자")
        print(f"\n[과제 지시문]\n{sample['prompt'][:200]}...")
        print(f"\n[에세이 앞부분]\n{sample['essay_text'][:300]}...")
    except FileNotFoundError as e:
        print(f"오류: {e}")

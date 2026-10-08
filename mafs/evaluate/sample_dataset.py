"""층화 샘플링 유틸리티 — RQ1·RQ2·RQ3 공통 데이터셋 생성.

국어·사회 10개 폴더(학년×교과)에서 폴더당 N건씩 층화 샘플링하고,
선택적으로 RQ1·RQ2용 서브샘플을 추가 생성한다.

사용 방법:
    # RQ3용 200건 + RQ1·RQ2용 34건 서브샘플 동시 생성
    python mafs/evaluate/sample_dataset.py \\
        --data_root "26.논술형_글쓰기_평가_데이터/.../01.원천데이터" \\
        --n_per_folder 20 --seed 42 \\
        --output mafs/evaluate/results/sampled_rq3.txt \\
        --n_rq12 34 \\
        --output_rq12 mafs/evaluate/results/sampled_rq12.txt

출력 형식: 파일 경로 1줄에 1개 (UTF-8)
"""

import sys
import argparse
import random
from pathlib import Path

MAFS_DIR = Path(__file__).parent.parent
if str(MAFS_DIR) not in sys.path:
    sys.path.insert(0, str(MAFS_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 국어·사회 10개 폴더 (과학 제외 — 5×2 균형 설계)
# Training/01.원천데이터 기준 (TS_ 접두사)
EXPECTED_FOLDERS = [
    "TS_1._초5_1._국어",
    "TS_1._초5_3._사회",
    "TS_2._초6_1._국어",
    "TS_2._초6_3._사회",
    "TS_3._중1_1._국어",
    "TS_3._중1_3._사회",
    "TS_4._중2_1._국어",
    "TS_4._중2_3._사회",
    "TS_5._중3_1._국어",
    "TS_5._중3_3._사회",
]


def stratified_sample(
    data_root: str,
    n_per_folder: int = 20,
    seed: int = 42,
) -> list[Path]:
    """폴더당 n_per_folder건씩 층화 샘플링하여 경로 목록을 반환."""
    root = Path(data_root)
    rng  = random.Random(seed)
    sampled: list[Path] = []

    found_folders = []
    for folder_name in EXPECTED_FOLDERS:
        folder = root / folder_name
        if not folder.exists():
            matches = [d for d in root.iterdir()
                       if d.is_dir() and folder_name.replace("TS_", "") in d.name]
            if matches:
                folder = matches[0]
            else:
                print(f"  [경고] 폴더 없음: {folder_name}", flush=True)
                continue

        csv_files = sorted(folder.glob("**/*.csv"))
        if not csv_files:
            print(f"  [경고] CSV 없음: {folder.name}", flush=True)
            continue

        n = min(n_per_folder, len(csv_files))
        chosen = sorted(rng.sample(csv_files, n))
        sampled.extend(chosen)
        found_folders.append(folder.name)
        print(f"  {folder.name}: {len(csv_files)}건 중 {n}건 선택", flush=True)

    print(f"\n총 {len(found_folders)}개 폴더 / {len(sampled)}건 샘플링 완료", flush=True)
    return sampled


def main(
    data_root: str,
    n_per_folder: int,
    seed: int,
    output: str,
    n_rq12: int | None,
    output_rq12: str | None,
) -> None:
    print(f"[SAMPLE] 층화 샘플링 시작 — 폴더당 {n_per_folder}건, seed={seed}", flush=True)
    files = stratified_sample(data_root, n_per_folder, seed)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for p in files:
            f.write(str(p) + "\n")
    print(f"[SAMPLE] RQ3 목록 저장 → {output_path} ({len(files)}건)", flush=True)

    # RQ1·RQ2 서브샘플 (전체 목록에서 무작위 추출)
    if n_rq12 and output_rq12:
        rng = random.Random(seed + 1)  # 다른 seed로 독립 추출
        n = min(n_rq12, len(files))
        rq12_files = sorted(rng.sample(files, n))

        rq12_path = Path(output_rq12)
        rq12_path.parent.mkdir(parents=True, exist_ok=True)
        with open(rq12_path, "w", encoding="utf-8") as f:
            for p in rq12_files:
                f.write(str(p) + "\n")
        print(f"[SAMPLE] RQ1·RQ2 서브샘플 저장 → {rq12_path} ({n}건)", flush=True)

    print(
        f"\n활용 방법:\n"
        f"  RQ3 (MAFS만): python mafs/evaluate/rq1_instruction.py"
        f" --file_list {output} --mafs_only --output rq3_200.jsonl\n"
        f"  RQ1      : python mafs/evaluate/rq1_instruction.py"
        f" --file_list {output_rq12 or output} --output rq1_34.jsonl\n"
        f"  RQ2      : python mafs/evaluate/rq2_design_elements.py"
        f" --file_list {output_rq12 or output} --reuse_rq1 rq1_34.jsonl --output rq2_34.jsonl",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="층화 샘플링: RQ1~RQ3 공통 데이터셋 생성")
    parser.add_argument("--data_root", required=True, help="01.원천데이터 폴더 경로")
    parser.add_argument("--n_per_folder", type=int, default=20, help="폴더당 샘플 건수 (기본 20, RQ3용)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output",
        default="mafs/evaluate/results/sampled_rq3.txt",
        help="RQ3용 전체 파일 경로 목록",
    )
    parser.add_argument(
        "--n_rq12",
        type=int,
        default=None,
        help="RQ1·RQ2용 서브샘플 건수 (전체 목록에서 추출, 기본 None)",
    )
    parser.add_argument(
        "--output_rq12",
        default=None,
        help="RQ1·RQ2용 서브샘플 파일 경로 목록 저장 경로",
    )
    args = parser.parse_args()
    main(args.data_root, args.n_per_folder, args.seed, args.output, args.n_rq12, args.output_rq12)

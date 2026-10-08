"""교차검증 2차 채점 — GPT-4o로 블라인드 표본을 재채점한다.

gemini 채점 프롬프트(evaluate/llm_judge.py의 JUDGE_SYSTEM_PROMPT)를 그대로
재사용하여, sample_cross_check.py가 만든 cross_check_blind.jsonl(조건 라벨
제거된 피드백)을 GPT-4o로 채점한다. 채점 기준·입력 형식이 gemini 채점과
완전히 동일해야 비교가 의미 있으므로 프롬프트를 수정하지 않고 import한다.

실행 전 준비:
  1) mafs/.env 에 OPENAI_API_KEY=... 추가
  2) pip install openai

실행 예시 (MISCA/ 루트에서):
    python mafs/evaluate/cross_check_score.py \\
        --input mafs/evaluate/results/cross_check_blind.jsonl \\
        --output mafs/evaluate/results/cross_check_gpt4o.jsonl \\
        --model gpt-4o
"""

import sys
import os
import json
import asyncio
import argparse
from pathlib import Path

MAFS_DIR = Path(__file__).parent.parent
if str(MAFS_DIR) not in sys.path:
    sys.path.insert(0, str(MAFS_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(MAFS_DIR / ".env")

from evaluate.llm_judge import (
    JUDGE_SYSTEM_PROMPT,
    _build_judge_input,
    _parse_judge_output,
    _compute_summary,
)

MAX_CONCURRENCY = 2

# gemini 채점과 완전히 동일한 프롬프트를 그대로 사용 (C1~M5 10개 기준, 한 글자도 바꾸지 않음)
GPT_JUDGE_PROMPT = JUDGE_SYSTEM_PROMPT


async def score_feedback_openai(
    client,
    essay: str,
    prompt: str,
    feedback: str,
    grade: str,
    model: str,
    max_retries: int = 3,
) -> dict | None:
    """gemini와 동일한 루브릭·입력 형식으로 GPT-4o 채점을 수행한다."""
    user_msg = _build_judge_input(essay, prompt, feedback, grade)

    for attempt in range(max_retries):
        try:
            resp = await client.chat.completions.create(
                model=model,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": GPT_JUDGE_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            text = resp.choices[0].message.content or ""
            scores = _parse_judge_output(text)
            if scores is not None:
                scores.update(_compute_summary(scores))
                return scores
            print(f"[GPT4O-JUDGE] 파싱 실패 (시도 {attempt + 1}/{max_retries}) — 재시도")
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep([5, 15, 30][attempt])
            else:
                print(f"[GPT4O-JUDGE] 오류: {e}")
                return None
    return None


async def main(input_path: str, output_path: str, model: str) -> None:
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[오류] OPENAI_API_KEY가 mafs/.env에 설정되어 있지 않습니다.")
        return
    client = AsyncOpenAI(api_key=api_key)

    items = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done_ids: set[str] = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        done_ids.add(json.loads(line)["item_id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
    if done_ids:
        print(f"[GPT4O-JUDGE] 이미 처리된 {len(done_ids)}건 건너뜀")

    pending = [it for it in items if it["item_id"] not in done_ids]
    print(f"[GPT4O-JUDGE] {len(pending)}/{len(items)}건 채점 시작 (model={model})")

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    lock = asyncio.Lock()

    async def _process(item: dict, out_f) -> None:
        async with semaphore:
            scores = await score_feedback_openai(
                client, item["essay"], item["prompt"], item["feedback"], item["grade"], model
            )
        result = {"item_id": item["item_id"], "gpt4o_scores": scores}
        async with lock:
            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()
            status = "OK" if scores else "FAIL"
            print(f"  [{status}] {item['item_id']}")

    with open(out_path, "a", encoding="utf-8") as out_f:
        await asyncio.gather(*(_process(it, out_f) for it in pending))

    print(f"[GPT4O-JUDGE] 완료 -> {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPT-4o로 블라인드 표본 재채점")
    parser.add_argument("--input", default="mafs/evaluate/results/cross_check_blind.jsonl")
    parser.add_argument("--output", default="mafs/evaluate/results/cross_check_gpt4o.jsonl")
    parser.add_argument("--model", default="gpt-4o")
    args = parser.parse_args()
    asyncio.run(main(args.input, args.output, args.model))

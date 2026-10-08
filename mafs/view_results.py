"""배치 결과 JSONL 요약 뷰어."""
import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

path = sys.argv[1] if len(sys.argv) > 1 else "mafs/results/results_중2사회.jsonl"

records = []
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        idx = line.find("{")
        if idx > 0:
            line = line[idx:]
        records.append(json.loads(line))

print(f"총 {len(records)}건\n")
all_pass = 0
rounds_dist = {}

for i, r in enumerate(records, 1):
    fc = r.get("final_criteria", {})
    triggers = {k: fc.get(k, "?") for k in ["C1", "C2", "M1", "M4"]}
    refs = {k: fc.get(k, "?") for k in ["C3", "C4", "C5", "M3", "M5"]}
    t_pass = all(v == "✓" for v in triggers.values())
    if t_pass:
        all_pass += 1
    rv = r["verify_rounds"]
    rounds_dist[rv] = rounds_dist.get(rv, 0) + 1

    prompt_short = r.get("prompt", "")[:40].replace("\n", " ")
    diag = r.get("diagnosis", "")
    weight_line = ""
    for l in diag.split("\n"):
        if "최종 가중치 요약" in l:
            weight_line = l.replace("최종 가중치 요약: ", "")
            break

    purpose = r.get("purpose", "")
    status_mark = "✓" if t_pass else "✗"
    print(f"[{i:02d}] {status_mark} {r['file']}  rounds={rv}")
    print(f"      지시문: {prompt_short}...  [{r.get('grade','')} {r.get('subject','')} / {purpose}]")
    print(f"      가중치: {weight_line}")
    t = triggers
    rf = refs
    print(
        f"      트리거: C1={t['C1']} C2={t['C2']} M1={t['M1']} M4={t['M4']}"
        f"  |  참고: C3={rf['C3']} C4={rf['C4']} C5={rf['C5']} M3={rf['M3']} M5={rf['M5']}"
    )
    print()

print("=" * 50)
print(f"트리거 전부 통과: {all_pass}/{len(records)}건 ({all_pass/len(records)*100:.0f}%)")
print(f"검증 rounds 분포: { {k: rounds_dist[k] for k in sorted(rounds_dist)} }")

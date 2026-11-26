"""Network smoke test: discover and fetch guides from a trip profile."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crawler import collect_guides
from src.profile import trip_profile, describe


def main() -> int:
    parser = argparse.ArgumentParser(description="自动搜索并抓取旅行攻略")
    parser.add_argument("--city", default="杭州")
    parser.add_argument("--date", default="2026-12-01")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--budget", type=float, default=1000)
    parser.add_argument("--audience", default="情侣")
    args = parser.parse_args()
    profile = trip_profile(args.city, args.date, args.days, args.budget, args.audience)
    print(describe(profile))
    for query in profile["queries"]:
        print("SEARCH:", query)
    notes = collect_guides(profile["queries"], args.city, progress=lambda n, stage: print(f"{n:.0%}: {stage}", flush=True))
    notes = [n for n in notes if n.get("kind") != "title_only" and n.get("text", "").strip()]
    for note in notes:
        print(f"PASS: {note['title']} ({len(note['text'])} chars)\n{note['url']}\n{note['text'][:160]}")
    if len(notes) < 3:
        print(f"FAIL: 仅取得 {len(notes)} 篇可读正文，未达到三篇目标")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

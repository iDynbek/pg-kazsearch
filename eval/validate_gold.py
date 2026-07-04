"""
Validation gates for the gold_v2 query dataset.

Gates:
  1. Every relevant URL exists in the corpus (articles table).
  2. Every query has >= 1 relevant document.
  3. No duplicate query strings.
  4. Circularity guard: no query is a verbatim substring of exactly one title
     while all its relevant docs are that single title's article (such a query
     tests string copying, not retrieval).

Exits non-zero if any gate fails.

Usage:
    python3 eval/validate_gold.py --gold eval/gold_queries_v2.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def psql_lines(sql: str, container: str, db: str, user: str) -> list[str]:
    cmd = ["docker", "exec", "-i", container, "psql", "-U", user, "-d", db, "-At"]
    result = subprocess.run(cmd, input=sql, text=True, capture_output=True, timeout=120)
    if result.returncode != 0:
        sys.exit(f"psql failed: {result.stderr[:500]}")
    return [l for l in result.stdout.splitlines() if l]


def main():
    parser = argparse.ArgumentParser(description="Validate gold_v2 dataset")
    parser.add_argument("--gold", default="eval/gold_queries_v2.jsonl")
    parser.add_argument("--container", default="pg-kazsearch")
    parser.add_argument("--db", default="kazsearch")
    parser.add_argument("--user", default="postgres")
    args = parser.parse_args()

    records = [json.loads(l) for l in Path(args.gold).read_text(encoding="utf-8").splitlines() if l.strip()]
    failures: list[str] = []

    # Gate 3: duplicates
    seen: set[str] = set()
    for r in records:
        if r["query"] in seen:
            failures.append(f"duplicate query: {r['query']!r}")
        seen.add(r["query"])

    # Gate 2: >= 1 relevant
    for r in records:
        if not r.get("relevant_urls"):
            failures.append(f"query with no relevant docs: {r['query']!r}")

    # Gate 1: URLs exist in corpus
    all_urls = sorted({u for r in records for u in r.get("relevant_urls", [])})
    corpus_urls = set(psql_lines("SELECT url FROM articles;", args.container, args.db, args.user))
    missing = [u for u in all_urls if u not in corpus_urls]
    for u in missing:
        failures.append(f"relevant URL not in corpus: {u}")

    # Gate 4: circularity guard
    titles = psql_lines("SELECT url || E'\\t' || title FROM articles;", args.container, args.db, args.user)
    title_of: dict[str, str] = {}
    for line in titles:
        url, _, title = line.partition("\t")
        title_of[url] = title.lower()
    all_titles = list(title_of.values())
    for r in records:
        q = r["query"].lower()
        holders = [t for t in all_titles if q in t]
        if len(holders) == 1:
            rel_titles = {title_of.get(u, "") for u in r["relevant_urls"]}
            if rel_titles <= set(holders):
                failures.append(f"circular query (verbatim substring of its only relevant title): {r['query']!r}")

    n_urls = len(all_urls)
    n_rel = sum(len(r["relevant_urls"]) for r in records)
    themes = {r.get("theme", "?") for r in records}
    print(f"{len(records)} queries, {len(themes)} themes, {n_rel} relevant pairs, {n_urls} distinct URLs")

    if failures:
        print(f"\nFAILED {len(failures)} gate check(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All gates passed.")


if __name__ == "__main__":
    main()

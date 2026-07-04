"""
Build candidate pools for gold_v2 relevance judgment.

For each seed query, retrieves the top-K union from three systems so judgments
are not biased toward any single retrieval method:
  1. kazakh_cfg FTS (stemmed)
  2. simple FTS (no stemming)
  3. trigram word_similarity over title || body

Output: one JSON object per query with candidate {url, title, excerpt} entries,
ready for relevance judgment.

Usage:
    python3 eval/build_gold_pool.py \
        --seed eval/gold_queries_v2_seed.jsonl \
        --output eval/gold_pool.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

CONTAINER = "pg-kazsearch"
DB = "kazsearch"
USER = "postgres"
EXCERPT_CHARS = 500


def qlit(s: str) -> str:
    return s.replace("'", "''").replace("\\", "\\\\")


def psql_json(sql: str, container: str, db: str, user: str) -> list:
    """Run SQL that returns a single json_agg column; parse it."""
    cmd = ["docker", "exec", "-i", container, "psql", "-U", user, "-d", db, "-At"]
    result = subprocess.run(cmd, input=sql, text=True, capture_output=True, timeout=300)
    if result.returncode != 0:
        sys.exit(f"psql failed: {result.stderr[:500]}")
    out = result.stdout.strip()
    if not out or out == "":
        return []
    return json.loads(out)


def pool_query(query: str, k: int, container: str, db: str, user: str) -> list[dict]:
    q = qlit(query)
    sql = f"""
WITH fts AS (
    SELECT id FROM articles
    WHERE fts_vector @@ websearch_to_tsquery('kazakh_cfg', '{q}')
    ORDER BY ts_rank_cd(fts_vector, websearch_to_tsquery('kazakh_cfg', '{q}')) DESC
    LIMIT {k}
),
nostem AS (
    SELECT id FROM articles
    WHERE fts_simple @@ websearch_to_tsquery('simple', '{q}')
    ORDER BY ts_rank_cd(fts_simple, websearch_to_tsquery('simple', '{q}')) DESC
    LIMIT {k}
),
trgm AS (
    SELECT id FROM articles
    ORDER BY word_similarity('{q}', title || ' ' || left(body, 1000)) DESC
    LIMIT {k}
),
pool AS (
    SELECT id FROM fts UNION SELECT id FROM nostem UNION SELECT id FROM trgm
)
SELECT COALESCE(json_agg(json_build_object(
    'url', a.url,
    'title', a.title,
    'excerpt', left(a.body, {EXCERPT_CHARS})
)), '[]'::json)
FROM articles a JOIN pool p ON a.id = p.id;
"""
    return psql_json(sql, container, db, user)


def main():
    parser = argparse.ArgumentParser(description="Build gold_v2 judgment pools")
    parser.add_argument("--seed", default="eval/gold_queries_v2_seed.jsonl")
    parser.add_argument("--output", default="eval/gold_pool.jsonl")
    parser.add_argument("--k", type=int, default=15, help="top-K per retrieval system")
    parser.add_argument("--container", default=CONTAINER)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--user", default=USER)
    args = parser.parse_args()

    seed_path = Path(args.seed)
    queries = [json.loads(l) for l in seed_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    out_path = Path(args.output)
    with out_path.open("w", encoding="utf-8") as out:
        for i, q in enumerate(queries):
            candidates = pool_query(q["query"], args.k, args.container, args.db, args.user)
            record = {
                "query": q["query"],
                "theme": q["theme"],
                "note": q.get("note", ""),
                "candidates": candidates,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            if (i + 1) % 25 == 0 or i + 1 == len(queries):
                print(f"  pooled {i + 1}/{len(queries)} queries", flush=True)

    sizes = []
    for line in out_path.read_text(encoding="utf-8").splitlines():
        sizes.append(len(json.loads(line)["candidates"]))
    print(f"Wrote {len(sizes)} pools to {out_path} "
          f"(candidates per query: min={min(sizes)}, avg={sum(sizes)/len(sizes):.1f}, max={max(sizes)})")


if __name__ == "__main__":
    main()

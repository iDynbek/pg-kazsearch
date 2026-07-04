"""
Evaluate Elasticsearch search quality with kazsearch_stem vs standard analyzer.

Mirrors eval/run_eval.py metrics (Precision@k, Recall@k, MRR, nDCG@k) and its
stratification: metrics are broken out by query `source` (gold, gold_v2,
title_keywords, body_sentence, morpho_variant, ...) because auto-generated
queries are mined from the indexed corpus itself and overstate real-world
quality — the gold rows are the honest headline numbers.

Also loads eval/gold_queries_v2.jsonl, whose queries carry `relevant_urls`
instead of `relevant_ids`; URLs are resolved against the `url` keyword field
stored in the ES index (see eval/load_corpus_es.py).

Usage:
    python3 eval/run_eval_es.py --auto eval/auto_queries.jsonl \
                                --gold eval/gold_queries.jsonl \
                                --gold-v2 eval/gold_queries_v2.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ES_URL = "http://localhost:9200"
INDEX = "articles"
BATCH = 50


def es_request(url: str, method: str = "GET", body: dict | None = None) -> dict | None:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def msearch_es(queries: list[tuple[int, str]], k: int, base_url: str,
               fields: list[str]) -> dict[int, list[int]]:
    if not queries:
        return {}

    lines = []
    for qid, qt in queries:
        lines.append(json.dumps({"index": INDEX}))
        lines.append(json.dumps({
            "size": k,
            "query": {
                "multi_match": {
                    "query": qt,
                    "fields": fields,
                    "type": "best_fields"
                }
            },
            "_source": False
        }))
    payload = "\n".join(lines) + "\n"
    data = payload.encode("utf-8")
    req = urllib.request.Request(f"{base_url}/_msearch", data=data, method="POST")
    req.add_header("Content-Type", "application/x-ndjson")
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())

    results: dict[int, list[int]] = {}
    for i, (qid, _) in enumerate(queries):
        response = result["responses"][i]
        hits = response.get("hits", {}).get("hits", [])
        results[qid] = [int(h["_id"]) for h in hits]
    return results


def resolve_relevant_urls(queries: list[dict], base_url: str) -> None:
    """Resolve `relevant_urls` to ES doc ids in place (gold_v2 format).

    URL-keyed gold files survive corpus reloads where serial ids do not.
    Matches on the `url` keyword field stored by eval/load_corpus_es.py.
    Queries that already carry `relevant_ids` (legacy format) are left alone.
    """
    all_urls = sorted({u for q in queries for u in q.get("relevant_urls", [])})
    if not all_urls:
        return
    id_of: dict[str, int] = {}
    for batch_start in range(0, len(all_urls), 500):
        batch = all_urls[batch_start:batch_start + 500]
        body = {
            "size": 2 * len(batch),
            "query": {"terms": {"url": batch}},
            "_source": ["url"],
        }
        resp = es_request(f"{base_url}/{INDEX}/_search", method="POST", body=body)
        for hit in resp.get("hits", {}).get("hits", []):
            id_of[hit["_source"]["url"]] = int(hit["_id"])
    unresolved = [u for u in all_urls if u not in id_of]
    if unresolved:
        print(f"  WARN: {len(unresolved)} relevant URLs not found in ES index", file=sys.stderr)
    for q in queries:
        urls = q.get("relevant_urls")
        if urls and not q.get("relevant_ids"):
            q["relevant_ids"] = [id_of[u] for u in urls if u in id_of]


def precision_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(1 for x in top if x in relevant) / len(top)


def recall_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    top = retrieved[:k]
    return sum(1 for x in top if x in relevant) / len(relevant)


def mrr(retrieved: list[int], relevant: set[int]) -> float:
    for i, doc_id in enumerate(retrieved):
        if doc_id in relevant:
            return 1.0 / (i + 1)
    return 0.0


def dcg_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    score = 0.0
    for i, doc_id in enumerate(retrieved[:k]):
        rel = 1.0 if doc_id in relevant else 0.0
        score += rel / math.log2(i + 2)
    return score


def ndcg_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    dcg = dcg_at_k(retrieved, relevant, k)
    ideal = sorted([1.0] * min(len(relevant), k) + [0.0] * max(0, k - len(relevant)), reverse=True)
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def load_queries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    queries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                queries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return queries


def _empty_metrics(ks: list[int]) -> dict[int, dict[str, list[float]]]:
    return {k_val: {"precision": [], "recall": [], "mrr": [], "ndcg": []} for k_val in ks}


def _summarize(m: dict[int, dict[str, list[float]]], ks: list[int]) -> dict:
    def _avg(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return {k_val: {name: round(_avg(vals), 4) for name, vals in m[k_val].items()}
            for k_val in ks}


def evaluate_method(name: str, indexed: list[tuple[int, str, set[int]]],
                    source_of: dict[int, str], ks: list[int], base_url: str,
                    fields: list[str]) -> dict:
    max_k = max(ks)
    t0 = time.monotonic()
    print(f"  Running {name} ({len(indexed)} queries)...", end="", flush=True)

    all_results: dict[int, list[int]] = {}
    for batch_start in range(0, len(indexed), BATCH):
        batch = [(idx, qt) for idx, qt, _ in indexed[batch_start:batch_start + BATCH]]
        all_results.update(msearch_es(batch, max_k, base_url, fields))
    elapsed = time.monotonic() - t0
    print(f" {elapsed:.1f}s")

    metrics = _empty_metrics(ks)
    by_source: dict[str, dict[int, dict[str, list[float]]]] = {}

    for idx, qt, relevant in indexed:
        results = all_results.get(idx, [])
        src = source_of.get(idx, "unknown")
        if src not in by_source:
            by_source[src] = _empty_metrics(ks)
        for k_val in ks:
            for store in (metrics, by_source[src]):
                store[k_val]["precision"].append(precision_at_k(results, relevant, k_val))
                store[k_val]["recall"].append(recall_at_k(results, relevant, k_val))
                store[k_val]["mrr"].append(mrr(results[:k_val], relevant))
                store[k_val]["ndcg"].append(ndcg_at_k(results, relevant, k_val))

    k0 = ks[0]
    by_source_summary = {
        src: {
            "metrics": _summarize(m, ks),
            "num_queries": len(m[k0]["recall"]),
        }
        for src, m in sorted(by_source.items())
    }

    return {
        "summary": _summarize(metrics, ks),
        "by_source": by_source_summary,
        "elapsed": elapsed,
    }


def print_report(results: dict, ks: list[int], n_queries: int):
    header = f"{'':36}"
    for k_val in ks:
        header += f"  {'P@' + str(k_val):>8}  {'R@' + str(k_val):>8}  {'MRR@' + str(k_val):>8}  {'nDCG@' + str(k_val):>8}"
    print(f"\n=== Elasticsearch eval ({n_queries} queries) ===")
    print(header)
    print("-" * len(header))
    for label, data in results.items():
        row = f"{label:36}"
        for k_val in ks:
            m = data["summary"][k_val]
            row += f"  {m['precision']:>8.4f}  {m['recall']:>8.4f}  {m['mrr']:>8.4f}  {m['ndcg']:>8.4f}"
        row += f"  ({data['elapsed']:.1f}s)"
        print(row)

    print()
    print("=== Metrics by query source ===")
    print("NOTE: auto-generated sources (title_keywords, body_sentence, morpho_variant)")
    print("are mined from the indexed corpus itself and overstate real-world quality.")
    print("The gold/gold_v2 rows (human-written queries) are the honest headline numbers.")
    for label, data in results.items():
        print(f"\n--- {label} ---")
        print(header)
        print("-" * len(header))
        for src, src_data in data["by_source"].items():
            row = f"{src + ' (n=' + str(src_data['num_queries']) + ')':36}"
            for k_val in ks:
                m = src_data["metrics"][k_val]
                row += f"  {m['precision']:>8.4f}  {m['recall']:>8.4f}  {m['mrr']:>8.4f}  {m['ndcg']:>8.4f}"
            print(row)


def main():
    parser = argparse.ArgumentParser(description="Evaluate ES search quality")
    parser.add_argument("--auto", default="eval/auto_queries.jsonl")
    parser.add_argument("--gold", default="eval/gold_queries.jsonl")
    parser.add_argument("--gold-v2", default="eval/gold_queries_v2.jsonl",
                        help="URL-keyed pooled-judgment gold queries")
    parser.add_argument("--k", type=int, nargs="+", default=[10, 50])
    parser.add_argument("--max-queries", type=int, default=0)
    parser.add_argument("--es-url", default=ES_URL)
    parser.add_argument("--report", default="eval/results/report_es.json")
    args = parser.parse_args()

    queries = (load_queries(Path(args.auto)) + load_queries(Path(args.gold))
               + load_queries(Path(args.gold_v2)))
    if not queries:
        sys.exit("No queries found.")

    resolve_relevant_urls(queries, args.es_url)

    if args.max_queries > 0:
        queries = queries[:args.max_queries]

    print(f"Loaded {len(queries)} queries, k={args.k}")

    indexed: list[tuple[int, str, set[int]]] = []
    source_of: dict[int, str] = {}
    for i, q in enumerate(queries):
        qt = q.get("query", "")
        rel = set(q.get("relevant_ids", []))
        if qt and rel:
            indexed.append((i, qt, rel))
            source_of[i] = q.get("source", "unknown")
    print(f"Valid queries: {len(indexed)}")

    methods = {
        "ES kazsearch_stem": ["title^2", "body"],
        "ES standard (no stemming)": ["title.standard^2", "body.standard"],
    }

    results = {}
    for label, fields in methods.items():
        results[label] = evaluate_method(label, indexed, source_of, args.k,
                                         args.es_url, fields)

    print_report(results, args.k, len(indexed))

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {}
    for label, data in results.items():
        serializable[label] = {
            "summary": {str(k): v for k, v in data["summary"].items()},
            "by_source": {
                src: {
                    "metrics": {str(k): v for k, v in src_data["metrics"].items()},
                    "num_queries": src_data["num_queries"],
                }
                for src, src_data in data["by_source"].items()
            },
            "elapsed_s": round(data["elapsed"], 2),
        }
    serializable["num_queries"] = len(indexed)
    serializable["ks"] = args.k
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()

"""
Measure stemmer token coverage over a token list (e.g. core/tests/bench_tokens.txt).

Definitions (reported separately -- "coverage" is ambiguous otherwise):
  - analyzed rate: share of tokens the stemmer changed (stem != lowercased token)
  - lexicon-valid rate: share of tokens whose final stem is in the lexicon
  - recognized rate: stem changed OR stem is a lexicon entry (a passthrough of a
    dictionary lemma is correct behavior, not a failure)

Uses the kazsearch CLI so the measurement goes through the exact production
Rust code path.

Usage:
    python3 eval/measure_stem_coverage.py \
        --tokens core/tests/bench_tokens.txt \
        --lexicon data/tsearch_data/kaz_stems.dict \
        --report eval/results/stem_coverage.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_cli() -> str:
    for candidate in (
        ROOT / "target" / "release" / "kazsearch",
        ROOT / "target" / "debug" / "kazsearch",
    ):
        if candidate.exists():
            return str(candidate)
    if shutil.which("kazsearch"):
        return "kazsearch"
    sys.exit("kazsearch CLI not found. Build it first: cargo build --release -p kazsearch-cli")


def load_lexicon(path: Path) -> set[str]:
    entries: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if w and not w.startswith("#"):
                entries.add(w)
    return entries


def main():
    parser = argparse.ArgumentParser(description="Measure stemmer token coverage")
    parser.add_argument("--tokens", default="core/tests/bench_tokens.txt",
                        help="File with one token per line")
    parser.add_argument("--lexicon", default="data/tsearch_data/kaz_stems.dict",
                        help="Lexicon dict file (used by the stemmer AND for stem validation)")
    parser.add_argument("--report", default="eval/results/stem_coverage.json")
    args = parser.parse_args()

    tokens_path = Path(args.tokens)
    lexicon_path = Path(args.lexicon)
    if not tokens_path.exists():
        sys.exit(f"Token file not found: {tokens_path}")
    if not lexicon_path.exists():
        sys.exit(f"Lexicon not found: {lexicon_path}")

    tokens = [t.strip() for t in tokens_path.read_text(encoding="utf-8").splitlines()]
    tokens = [t for t in tokens if t]
    lexicon = load_lexicon(lexicon_path)

    cli = find_cli()
    proc = subprocess.run(
        [cli, "stem", "--stdin", "--lexicon", str(lexicon_path)],
        input="\n".join(tokens),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        sys.exit(f"kazsearch stem failed: {proc.stderr[:500]}")

    total = 0
    changed = 0
    stem_in_lexicon = 0
    recognized = 0
    unchanged_oov = 0

    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        word, stem = parts
        total += 1
        was_changed = stem != word.lower()
        in_lex = stem in lexicon
        if was_changed:
            changed += 1
        if in_lex:
            stem_in_lexicon += 1
        if was_changed or in_lex:
            recognized += 1
        else:
            unchanged_oov += 1

    if total == 0:
        sys.exit("No tokens were stemmed")

    def pct(x: int) -> float:
        return round(100.0 * x / total, 2)

    report = {
        "tokens_file": str(tokens_path),
        "lexicon_file": str(lexicon_path),
        "total_tokens": total,
        "analyzed_rate_pct": pct(changed),
        "lexicon_valid_rate_pct": pct(stem_in_lexicon),
        "recognized_rate_pct": pct(recognized),
        "unchanged_oov_pct": pct(unchanged_oov),
        "definitions": {
            "analyzed_rate": "stem differs from lowercased input (a suffix was stripped)",
            "lexicon_valid_rate": "final stem is an entry in the lexicon",
            "recognized_rate": "stem changed OR stem is a lexicon entry",
            "unchanged_oov": "token passed through unchanged and is not in the lexicon",
        },
    }

    print(f"Tokens:              {total}")
    print(f"Analyzed (stemmed):  {pct(changed):.2f}%")
    print(f"Stem in lexicon:     {pct(stem_in_lexicon):.2f}%")
    print(f"Recognized:          {pct(recognized):.2f}%")
    print(f"Unchanged + OOV:     {pct(unchanged_oov):.2f}%")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()

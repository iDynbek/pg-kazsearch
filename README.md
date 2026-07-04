<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/img/logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/img/logo-light.png">
    <img src="docs/img/logo-light.png" alt="pg_kazsearch logo" width="160">
  </picture>
</p>

<h1 align="center">pg_kazsearch</h1>

<p align="center">
  The first full-text search stemmer for the Kazakh language — for <strong>PostgreSQL</strong> and <strong>Elasticsearch</strong>.
</p>

<p align="center">
  <a href="LICENSE">License: LGPL v3</a> &nbsp;·&nbsp;
  <a href="https://www.postgresql.org/">PostgreSQL: 16–18</a>
</p>

---

Kazakh is heavily agglutinative: a single word like `мектептерімізде` carries plural, possessive, and locative suffixes that must all be stripped to reach the root `мектеп`. No existing PostgreSQL or Elasticsearch analyzer handles this. pg_kazsearch fills that gap with a Rust stemmer that plugs into both PostgreSQL (via [pgrx](https://github.com/pgcentralfoundation/pgrx)) and Elasticsearch (via JNI native plugin).

```sql
-- PostgreSQL
CREATE EXTENSION pg_kazsearch;
SELECT to_tsvector('kazakh_cfg', 'президенттің жарлығы');
-- 'жарлық':2 'президент':1
```

```json
// Elasticsearch
{ "filter": { "kaz_stem": { "type": "kazsearch_stem" } } }
// алмаларымыздағы → алма
// мектептеріміздегі → мектеп
// almalar → алма
// mektepterimizdegi → мектеп
```

Latin-script Kazakh is auto-detected and normalized to canonical Cyrillic inside the core stemmer. Successful Latin and Cyrillic inputs therefore converge to the same stem output (always Cyrillic), which keeps indexing and query matching unified across scripts.

Current scope of Latin support:
- Targets the official modern Kazakh Latin orthography first (`ä ö ü ū ğ ş ñ ı`, plus `q`/`w`).
- Leaves mixed-script, unsupported Latin variants (apostrophe/acute/digraph legacy spellings), and low-confidence ASCII tokens unchanged.

---

## Install

### Pre-built package (Debian/Ubuntu)

Download the `.deb` for your PostgreSQL version from [GitHub Releases](https://github.com/darkhanakh/pg-kazsearch/releases):

```bash
# Example: PostgreSQL 18 on amd64
curl -LO https://github.com/darkhanakh/pg-kazsearch/releases/latest/download/postgresql-18-pg-kazsearch_2.0.0_amd64.deb
sudo dpkg -i postgresql-18-pg-kazsearch_2.0.0_amd64.deb
```

Then in psql:

```sql
CREATE EXTENSION pg_kazsearch;
```

### Docker

Use the pre-built image as a drop-in replacement for `postgres`:

```yaml
# docker-compose.yml
services:
  db:
    image: ghcr.io/darkhanakh/pg-kazsearch:18
```

Or add to your existing Dockerfile:

```dockerfile
FROM ghcr.io/darkhanakh/pg-kazsearch:18 AS kazsearch
FROM postgres:18

COPY --from=kazsearch /usr/share/postgresql/18/extension/pg_kazsearch* /usr/share/postgresql/18/extension/
COPY --from=kazsearch /usr/lib/postgresql/18/lib/pg_kazsearch* /usr/lib/postgresql/18/lib/
COPY --from=kazsearch /usr/share/postgresql/18/tsearch_data/kaz_* /usr/share/postgresql/18/tsearch_data/
```

### From source

```bash
# Requires: Rust toolchain, cargo-pgrx, postgresql-server-dev
cargo install --locked cargo-pgrx --version "=0.17.0"
cargo pgrx init --pg18 $(which pg_config)

git clone https://github.com/darkhanakh/pg-kazsearch.git
cd pg-kazsearch
cargo pgrx install --release -p pg_kazsearch

# Install lexicon and stopwords
cp data/tsearch_data/kaz_stems.dict $(pg_config --sharedir)/tsearch_data/
cp data/tsearch_data/kaz_stopwords.stop $(pg_config --sharedir)/tsearch_data/
```

---

## Elasticsearch

The same Kazakh stemmer is available as an Elasticsearch analysis plugin (`kazsearch_stem` token filter). All stemmer logic stays in Rust — the Java side is a thin JNI bridge.

### Install from GitHub Releases

Download the plugin ZIP from [GitHub Releases](https://github.com/darkhanakh/pg-kazsearch/releases) and install:

```bash
bin/elasticsearch-plugin install https://github.com/darkhanakh/pg-kazsearch/releases/latest/download/analysis-kazsearch-0.1.0.zip
```

The pre-built ZIP includes native libraries for linux/amd64 and linux/aarch64.

### Configuration

```json
{
  "settings": {
    "analysis": {
      "filter": {
        "kaz_stem": { "type": "kazsearch_stem" }
      },
      "analyzer": {
        "kazakh": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": ["lowercase", "kaz_stem"]
        }
      }
    }
  }
}
```

### Verify

```bash
curl -X POST 'localhost:9200/my_index/_analyze' \
  -H 'Content-Type: application/json' \
  -d '{"analyzer": "kazakh", "text": "алмаларымыздағы мектептеріміздегі"}'
# → tokens: ["алма", "мектеп"]
```

### Build from source

Requires: Rust toolchain, JDK 21, Gradle 8+, and `cargo-zigbuild` for cross-compilation.

```bash
# Build Rust cdylib (native stemmer library)
just es-native

# Build ES plugin ZIP (includes Java bridge + native lib)
just es-build
# → elastic/java/build/distributions/analysis-kazsearch-0.1.0.zip

# Run tests
just es-up
just es-load-corpus   # index 3000 articles
just es-eval          # run search quality evaluation
```

---

## Usage (PostgreSQL)

The extension creates everything automatically — a text search template, dictionaries, and a ready-to-use configuration called `kazakh_cfg`:

```sql
CREATE EXTENSION pg_kazsearch;

-- Stem individual words
SELECT ts_lexize('pg_kazsearch_dict', 'алмаларымыздағы');
-- {алма}

-- Build tsvectors
SELECT to_tsvector('kazakh_cfg', 'мектептеріміздегі оқушылардың');
-- 'мектеп':1 'оқушы':2

-- Add FTS to a table
ALTER TABLE articles ADD COLUMN fts tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('kazakh_cfg', title), 'A') ||
        setweight(to_tsvector('kazakh_cfg', body), 'B')
    ) STORED;

CREATE INDEX idx_fts ON articles USING GIN (fts);

-- Search
SELECT title FROM articles
WHERE fts @@ websearch_to_tsquery('kazakh_cfg', 'президенттің жарлығы')
ORDER BY ts_rank_cd(fts, websearch_to_tsquery('kazakh_cfg', 'президенттің жарлығы')) DESC
LIMIT 10;
```

### Tuning weights

Penalty weights are tunable at runtime without restarting PostgreSQL:

```sql
ALTER TEXT SEARCH DICTIONARY pg_kazsearch_dict (w_deriv = 3.5, w_short_char = 100.0);
```

### Script mode controls

`pg_kazsearch_dict` defaults to `script_mode = auto` (Latin auto-detection + canonical Cyrillic output). For debugging or strict Cyrillic-only behavior:

```sql
ALTER TEXT SEARCH DICTIONARY pg_kazsearch_dict (script_mode = cyrillic_only);
```

CLI uses the same core default (`auto`) and exposes `--cyrillic-only` on `stem`, `analyze`, and `bench` commands. Elasticsearch currently inherits the core default (`auto`) through the native stemmer config.

---

## Benchmarks

Tested on 2,999 Kazakh news articles from [kaz.tengrinews.kz](https://kaz.tengrinews.kz/). Queries fall into two groups that must be read differently:

- **gold** (n=51): human-written search queries with manually judged relevance — the honest measure of real-world quality
- **auto** (n=8,997): queries mined from the indexed articles themselves (title keywords, body sentences, artificially inflected variants) — useful for regression testing, but *circular*: they overstate absolute quality because each query is derived from the document it must find

All numbers below are reproduced by `just eval-search` and written to `eval/results/report.json` (charts are generated from that file, never hardcoded).

### Does stemming help? (vs identical FTS with no stemming)

Recall@10, same corpus, same ranking, only the dictionary differs:

| Query set                  | pg_kazsearch | `simple` (no stem) | Effect |
| -------------------------- | ------------ | ------------------ | ------ |
| gold (human, n=51)         | **0.199**    | 0.102              | ~2x recall |
| morpho_variant (inflected) | **0.442**    | 0.005              | ~94x — stemming is essential for suffixed queries |
| title_keywords (verbatim)  | 0.986        | 0.992              | no stemming needed for exact-word matches |

Human queries in Kazakh naturally contain inflected forms, which is exactly where the stemmer pays off. Absolute gold-set scores are low partly because gold queries expect up to 10 relevant documents and the corpus is small.

### PostgreSQL: pg_kazsearch vs pg_trgm

Head-to-head on the same 500-query sample (seeded, reproducible):

| Metric    | pg_kazsearch | pg_trgm | Improvement |
| --------- | ------------ | ------- | ----------- |
| Recall@10 | **0.772**    | 0.632   | +22%        |
| MRR@10    | **0.703**    | 0.544   | +29%        |
| nDCG@10   | **0.718**    | 0.565   | +27%        |

Note: pg_trgm here matches against titles only (its typical usage); the sample is dominated by auto-queries, so treat this as a relative comparison, not an absolute quality claim.

### Token coverage

Measured over 45,708 corpus tokens with `python3 eval/measure_stem_coverage.py`:

| Rate | Value | Meaning |
| ---- | ----- | ------- |
| Analyzed | 74.5% | a suffix was stripped |
| Stem in lexicon | 66.3% | final stem is a dictionary lemma |
| Recognized | **86.4%** | stemmed or already a dictionary lemma |


### Elasticsearch: kazsearch_stem vs standard analyzer

On human-written gold queries, the stemmer finds more relevant articles and ranks them higher:


| Metric    | kazsearch_stem | standard | Improvement |
| --------- | -------------- | -------- | ----------- |
| Recall@10 | **0.358**      | 0.309    | +16%        |
| MRR@10    | **0.671**      | 0.591    | +13%        |


### vs Tengrinews.kz native search

Searching the same articles on tengrinews.kz vs ES with kazsearch_stem:


| Search query (Kazakh with suffixes) | tengrinews.kz | ES + kazsearch_stem |
| ----------------------------------- | ------------- | ------------------- |
| мектептердегі оқушылар              | 2             | **159**             |
| балалардың денсаулығы               | 13            | **391**             |
| мұғалімдердің наразылығы            | 0             | **28**              |
| спортшылардың жетістіктері          | 0             | **87**              |
| бензиннің бағасын көтеру            | 0             | **69**              |
| мектептеріміздегі мәселелер         | 0             | **609**             |


### Stemmer examples


| Input            | Output    | Stripped                       |
| ---------------- | --------- | ------------------------------ |
| мектептерімізде  | мектеп    | plural + possessive + locative |
| президенттерінің | президент | plural + possessive + genitive |
| өзгеруі          | өзгеру    | verbal noun possessive         |
| берді            | бер       | past tense                     |
| экономикалық     | экономика | derivational adjective         |


---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Cargo Workspace                        │
│                                                          │
│  core/         Pure Rust stemmer (no PG/ES deps)         │
│  pg_ext/       pgrx PostgreSQL extension                 │
│  cli/          CLI tool (kazsearch stem/analyze/bench)   │
│  elastic/      Elasticsearch plugin (Rust cdylib + JNI)  │
│    src/        C ABI + JNI exports calling core::stem()  │
│    java/       Java bridge + Lucene TokenFilter (~50 LoC)│
│    docker/     ES with plugin pre-installed              │
└──────────────────────────────────────────────────────────┘
```

One stemmer, multiple consumers. The `core/` crate is the single source of truth for all stemming logic — PostgreSQL, Elasticsearch, and CLI all call into it.

The stemmer algorithm:

- **BFS suffix stripper** — breadth-first search over layered morphological rules (predicate, case, possessive, plural, derivational for nouns; person, tense, negation, voice for verbs), with vowel harmony validation
- **Penalty scoring** — candidates scored by syllable count, suffix weakness, derivational depth, and lexicon hits
- **Lexicon** — 21,863 POS-tagged stems from [Apertium-kaz](https://github.com/apertium/apertium-kaz) for overstemming protection
- **Stem repair** — consonant mutation reversal (б→п, г→к, ғ→қ), vowel elision restoration, lexicon-based vowel append

---

## CLI

The `kazsearch` CLI works standalone without PostgreSQL:

```bash
cargo build -p kazsearch-cli --release

# Stem a word
kazsearch stem алмаларымыздағы
# алмаларымыздағы	алма

# Morphological analysis
kazsearch analyze мектептеріміздегі

# Benchmark
kazsearch bench wordlist.txt

# Validate lexicon
kazsearch lexicon validate data/tsearch_data/kaz_stems.dict
```

---

## Development

### PostgreSQL

```bash
just up            # Start PG container
just build         # Build + install extension
just reload        # DROP + CREATE extension
just test-core     # Core Rust unit tests
just test-ext      # Smoke test via SQL
just cli           # Build CLI
```

### Elasticsearch

```bash
just es-native       # Build Rust cdylib for ES plugin
just es-build        # Build plugin ZIP (Gradle)
just es-up           # Start ES container with plugin
just es-load-corpus  # Index 3000 articles
just es-eval         # Run search quality evaluation
just es-down         # Stop ES container
```

---

## Contributing

1. Fork the repo and create a feature branch
2. Make your changes — stemmer logic lives in `core/src/`, extension glue in `pg_ext/src/lib.rs`
3. Run `cargo test -p kazsearch-core --test stem_tests` to verify stemmer correctness
4. Run `just up && just reload && just test-ext` to verify the extension works end-to-end
5. Open a PR

Key things to know:

- Penalty weights in `core/src/explore.rs` are empirically tuned via CMA-ES — changing one can affect many test cases
- Layer guards encode real morphotactic constraints, not heuristics
- Vowel harmony (back/front) is mandatory for suffix validation

---

## References

- Krippes, K.A. (1993). *Kazakh (Qazaq-) Grammatical Sketch with Affix List*. ERIC.
- Washington, J., Salimzyanov, I., Tyers, F. (2014). *Finite-state morphological transducers for three Kypchak languages*. LREC.
- Makhambetov, O. et al. (2015). *Data-driven morphological analysis and disambiguation for Kazakh*. CICLing.

---

## License

- **Code:** [LGPL-3.0](LICENSE)
- **Lexicon data** derived from [Apertium-kaz](https://github.com/apertium/apertium-kaz) (GPL-3.0).


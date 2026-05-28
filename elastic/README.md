# kazsearch — Kazakh Stemmer for Elasticsearch

Analysis plugin that adds a `kazsearch_stem` token filter for Kazakh full-text search.  
BFS suffix-stripping with vowel harmony enforcement — the first Kazakh stemmer for Elasticsearch.

## Compatibility

| Plugin version | Elasticsearch | Java | Architecture |
|---|---|---|---|
| 0.1.0 | 8.17.x | 21+ | linux/aarch64, linux/x86_64, darwin/aarch64 |

## Quick Start (Docker)

The fastest way — one command, no build tools needed:

```bash
# From the repo root:
./elastic/install.sh --docker

# Or manually:
docker run -d --name es-kazsearch \
  -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  kazsearch-elastic:0.1.0
```

## Install from Pre-Built Zip

Download `analysis-kazsearch-0.1.0.zip` from [GitHub Releases](https://github.com/darkhanakh/pg-kazsearch/releases), then:

```bash
# Option A: use the install script
./elastic/install.sh /path/to/analysis-kazsearch-0.1.0.zip

# Option B: install manually
bin/elasticsearch-plugin install file:///path/to/analysis-kazsearch-0.1.0.zip
sudo systemctl restart elasticsearch
```

The zip is self-contained — it includes the Java jar and the native Rust library.

## Build from Source

Requirements: Rust toolchain, Java 21, Gradle.

```bash
# Build native lib + Java plugin + install into local ES
./elastic/install.sh --build
```

Or step by step:

```bash
# 1. Build the native Rust library
./scripts/build_elastic_native.sh

# 2. Build the plugin zip (includes native lib)
cd elastic/java
gradle bundlePlugin
# → build/distributions/analysis-kazsearch-0.1.0.zip

# 3. Install
$ES_HOME/bin/elasticsearch-plugin install \
  file://$(pwd)/build/distributions/analysis-kazsearch-0.1.0.zip

# 4. Restart Elasticsearch
sudo systemctl restart elasticsearch
```

## Usage

### 1. Create an index with the Kazakh analyzer

```json
PUT /articles
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
  },
  "mappings": {
    "properties": {
      "title": { "type": "text", "analyzer": "kazakh" },
      "body":  { "type": "text", "analyzer": "kazakh" }
    }
  }
}
```

### 2. Test the analyzer

```bash
curl -X POST "localhost:9200/articles/_analyze" \
  -H 'Content-Type: application/json' \
  -d '{"analyzer": "kazakh", "text": "мектептерде оқушылар"}'
```

Result: `["мектеп", "оқушы"]` — suffixes stripped, stems returned.

### 3. Index documents

```bash
curl -X POST "localhost:9200/articles/_doc" \
  -H 'Content-Type: application/json' \
  -d '{"title": "Мектептерде жаңа оқу жылы", "body": "Оқушылар жаңа оқулықтарды алды."}'
```

### 4. Search with any inflected form

```bash
# Searching "мектептегі" (at school) finds docs containing
# "мектептерде" (in schools), "мектепте" (at school), etc.
curl -X POST "localhost:9200/articles/_search" \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match": {"body": "мектептегі оқушыларды"}}}'
```

## What It Does

Kazakh is agglutinative — a single word can stack 5–6 suffixes:

```
мектептерінде = мектеп + тер (plural) + і (possessive) + нде (locative)
               "in their schools"
```

The plugin stems all inflected forms to a common root, so search works regardless of which grammatical form appears in the document or query:

| Query form | Document form | Both stem to |
|---|---|---|
| мектептерде | мектептің | мектеп |
| оқушыларды | оқушылар | оқушы |
| дәрігерлерге | дәрігерлердің | дәрігер |
| технологияларды | технологиясын | технология |

## Recommended Index Pattern

For best results, index with both a stemmed and a standard (unstemmed) sub-field:

```json
{
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "analyzer": "kazakh",
        "fields": {
          "exact": { "type": "text", "analyzer": "standard" }
        }
      }
    }
  }
}
```

This lets you boost exact matches while still getting stemmed recall:

```json
{
  "query": {
    "multi_match": {
      "query": "Қазақстан экономикасы",
      "fields": ["title^3", "title.exact^5", "body"]
    }
  }
}
```

## Architecture

```
┌─────────────────────────────────────────────┐
│           Elasticsearch 8.17                │
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │  analysis-kazsearch plugin (Java)    │   │
│  │                                      │   │
│  │  KazakhStemTokenFilter               │   │
│  │    └─► KazakhStemmerNative (JNI)     │   │
│  │          └─► libkazsearch_elastic.so │   │
│  │                └─► kazsearch-core    │   │
│  │                     (pure Rust)      │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

The stemmer logic lives in `kazsearch-core` (pure Rust, no ES/PG dependencies). The same core powers both the PostgreSQL extension and this Elasticsearch plugin.

## Troubleshooting

**Plugin fails to load with `UnsatisfiedLinkError`:**  
The native library for your platform is missing from the zip. Rebuild with `./scripts/build_elastic_native.sh` on a machine matching your ES server's OS/arch, then `gradle bundlePlugin`.

**No stemming effect (tokens unchanged):**  
Make sure your index analyzer uses the `kazsearch_stem` filter. Test with `_analyze` API first.

**ES won't start after install:**  
Check ES version matches (8.17.x). Check `elasticsearch.log` for the exact error. Run `bin/elasticsearch-plugin remove analysis-kazsearch` to uninstall.

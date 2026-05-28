# kazsearch — Kazakh Stemmer for Elasticsearch

Analysis plugin that adds a `kazsearch_stem` token filter for Kazakh full-text search.  
BFS suffix-stripping with vowel harmony enforcement — the first Kazakh stemmer for Elasticsearch.

## Compatibility

| Plugin version | Elasticsearch | Java | Architecture |
|---|---|---|---|
| 0.1.0 | 8.17.x | 21+ | linux/aarch64, linux/x86_64, darwin/aarch64 |

## Quick Start

The install script auto-downloads the latest release from GitHub:

```bash
# Download latest release + install into local ES:
./elastic/install.sh

# Or a specific version:
./elastic/install.sh --version 2.1.0

# Or Docker (no ES install needed):
./elastic/install.sh --docker
```

The release zip is self-contained — Java jar + native Rust library for both x86_64 and aarch64.

## Install Methods

### Method 1: Auto-download (recommended)

```bash
# Downloads latest from GitHub Releases, installs into ES_HOME
./elastic/install.sh
sudo systemctl restart elasticsearch
```

### Method 2: Manual download

Grab `analysis-kazsearch-<version>.zip` from [GitHub Releases](https://github.com/darkhanakh/pg-kazsearch/releases), then:

```bash
bin/elasticsearch-plugin install file:///path/to/analysis-kazsearch-2.1.0.zip
sudo systemctl restart elasticsearch
```

### Method 3: Docker

```bash
# From release:
./elastic/install.sh --docker --version 2.1.0

# Or from source:
./elastic/install.sh --docker

# Then run:
docker run -d --name es-kazsearch \
  -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  kazsearch-elastic:2.1.0
```

### Method 4: Build from source

Requirements: Rust toolchain, Java 21, Gradle.

```bash
./elastic/install.sh --build
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

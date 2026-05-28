#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  kazsearch Elasticsearch plugin installer
#
#  Usage:
#    # Install from pre-built zip (downloaded from GitHub Releases):
#    ./install.sh /path/to/analysis-kazsearch-0.1.0.zip
#
#    # Build from source and install:
#    ./install.sh --build
#
#    # Docker: build image with plugin baked in:
#    ./install.sh --docker
#
#  Requirements:
#    --build  : Rust toolchain, Java 21, Gradle
#    --docker : Docker
#    (default): just elasticsearch-plugin on PATH or ES_HOME set
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_NAME="analysis-kazsearch"
PLUGIN_VERSION="0.1.0"
ZIP_NAME="${PLUGIN_NAME}-${PLUGIN_VERSION}.zip"
JAVA_DIR="${REPO_ROOT}/elastic/java"
DIST_DIR="${JAVA_DIR}/build/distributions"

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
info()  { printf '\033[0;36m→ %s\033[0m\n' "$*"; }

usage() {
    sed -n '2,/^# ─/{ /^# ─/d; s/^#  \?//; p }' "$0"
    exit 1
}

# ── Build native library (Rust → .so / .dylib) ──────────────
build_native() {
    info "Building native library (Rust)..."
    bash "${REPO_ROOT}/scripts/build_elastic_native.sh"
}

# ── Build Java plugin zip ────────────────────────────────────
build_plugin() {
    info "Building Java plugin zip..."
    cd "$JAVA_DIR"

    if command -v gradle &>/dev/null; then
        gradle bundlePlugin
    elif [[ -f ./gradlew ]]; then
        ./gradlew bundlePlugin
    else
        red "ERROR: Neither 'gradle' nor './gradlew' found in ${JAVA_DIR}"
        red "Install Gradle or run: gradle wrapper"
        exit 1
    fi

    if [[ ! -f "${DIST_DIR}/${ZIP_NAME}" ]]; then
        red "ERROR: Expected zip not found: ${DIST_DIR}/${ZIP_NAME}"
        exit 1
    fi
    green "Plugin zip built: ${DIST_DIR}/${ZIP_NAME}"
}

# ── Install into a running Elasticsearch ─────────────────────
install_plugin() {
    local zip_path="$1"

    if [[ ! -f "$zip_path" ]]; then
        red "ERROR: Plugin zip not found: ${zip_path}"
        exit 1
    fi

    # Find elasticsearch-plugin binary
    local es_plugin=""
    if [[ -n "${ES_HOME:-}" ]] && [[ -x "${ES_HOME}/bin/elasticsearch-plugin" ]]; then
        es_plugin="${ES_HOME}/bin/elasticsearch-plugin"
    elif command -v elasticsearch-plugin &>/dev/null; then
        es_plugin="elasticsearch-plugin"
    else
        red "ERROR: Cannot find elasticsearch-plugin."
        red "Set ES_HOME or add elasticsearch-plugin to PATH."
        exit 1
    fi

    # Remove old version if installed
    if $es_plugin list 2>/dev/null | grep -q "$PLUGIN_NAME"; then
        info "Removing existing ${PLUGIN_NAME} plugin..."
        $es_plugin remove "$PLUGIN_NAME" --purge 2>/dev/null || true
    fi

    info "Installing plugin from ${zip_path}..."
    $es_plugin install --batch "file://${zip_path}"

    green "✅ Plugin installed! Restart Elasticsearch to activate."
    echo ""
    echo "  Add to your elasticsearch.yml if not already set:"
    echo "    # No extra config needed — the plugin registers automatically."
    echo ""
    echo "  Create an index with the stemmer:"
    echo '    PUT /my_index'
    echo '    {'
    echo '      "settings": {'
    echo '        "analysis": {'
    echo '          "filter":   { "kaz_stem": { "type": "kazsearch_stem" } },'
    echo '          "analyzer": {'
    echo '            "kazakh": {'
    echo '              "type": "custom",'
    echo '              "tokenizer": "standard",'
    echo '              "filter": ["lowercase", "kaz_stem"]'
    echo '            }'
    echo '          }'
    echo '        }'
    echo '      },'
    echo '      "mappings": {'
    echo '        "properties": {'
    echo '          "title": { "type": "text", "analyzer": "kazakh" },'
    echo '          "body":  { "type": "text", "analyzer": "kazakh" }'
    echo '        }'
    echo '      }'
    echo '    }'
}

# ── Docker mode ──────────────────────────────────────────────
docker_mode() {
    build_native
    build_plugin
    info "Building Docker image..."
    cd "${REPO_ROOT}/elastic/docker"
    docker build -t kazsearch-elastic:${PLUGIN_VERSION} -f Dockerfile "${JAVA_DIR}"
    green "✅ Docker image built: kazsearch-elastic:${PLUGIN_VERSION}"
    echo ""
    echo "  Run it:"
    echo "    docker run -d --name es-kazsearch \\"
    echo "      -p 9200:9200 \\"
    echo "      -e discovery.type=single-node \\"
    echo "      -e xpack.security.enabled=false \\"
    echo "      kazsearch-elastic:${PLUGIN_VERSION}"
}

# ── Main ─────────────────────────────────────────────────────
case "${1:-}" in
    --build)
        build_native
        build_plugin
        install_plugin "$(cd "$DIST_DIR" && pwd)/${ZIP_NAME}"
        ;;
    --docker)
        docker_mode
        ;;
    --help|-h|"")
        if [[ -z "${1:-}" ]]; then
            usage
        fi
        usage
        ;;
    *)
        # Treat argument as path to pre-built zip
        zip_path="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
        install_plugin "$zip_path"
        ;;
esac

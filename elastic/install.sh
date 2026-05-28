#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  kazsearch Elasticsearch plugin installer
#
#  Usage:
#    # Auto-download latest release and install:
#    ./install.sh
#
#    # Download + install a specific version:
#    ./install.sh --version 2.1.0
#
#    # Install from a local pre-built zip:
#    ./install.sh /path/to/analysis-kazsearch-2.1.0.zip
#
#    # Build from source and install:
#    ./install.sh --build
#
#    # Docker: build image with plugin baked in:
#    ./install.sh --docker
#
#  Requirements:
#    (default) : curl + elasticsearch-plugin on PATH (or ES_HOME set)
#    --build   : Rust toolchain, Java 21, Gradle
#    --docker  : Docker
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_NAME="analysis-kazsearch"
GITHUB_REPO="darkhanakh/pg-kazsearch"
JAVA_DIR="${REPO_ROOT}/elastic/java"
DIST_DIR="${JAVA_DIR}/build/distributions"

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
info()  { printf '\033[0;36m→ %s\033[0m\n' "$*"; }

usage() {
    cat <<'EOF'
kazsearch Elasticsearch plugin installer

Usage:
  ./install.sh                              Download latest release + install
  ./install.sh --version 2.1.0              Download specific version + install
  ./install.sh /path/to/plugin.zip          Install from local zip
  ./install.sh --build                      Build from source + install
  ./install.sh --docker                     Build Docker image from source
  ./install.sh --docker --version 2.1.0     Build Docker image from release

Requirements:
  (default)  curl + elasticsearch-plugin on PATH (or ES_HOME set)
  --build    Rust toolchain, Java 21, Gradle
  --docker   Docker
EOF
    exit 1
}

# ── Detect latest release version from GitHub ────────────────
detect_latest_version() {
    local url="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"
    local tag
    if command -v curl &>/dev/null; then
        tag=$(curl -sf "$url" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"v\?\([^"]*\)".*/\1/')
    elif command -v wget &>/dev/null; then
        tag=$(wget -qO- "$url" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"v\?\([^"]*\)".*/\1/')
    else
        red "ERROR: curl or wget required to download releases."
        exit 1
    fi
    if [[ -z "$tag" ]]; then
        red "ERROR: Could not detect latest release version."
        red "Check: https://github.com/${GITHUB_REPO}/releases"
        exit 1
    fi
    echo "$tag"
}

# ── Download plugin zip from GitHub Releases ─────────────────
download_plugin() {
    local version="$1"
    local zip_name="${PLUGIN_NAME}-${version}.zip"
    local url="https://github.com/${GITHUB_REPO}/releases/download/v${version}/${zip_name}"
    local dest="/tmp/${zip_name}"

    info "Downloading ${zip_name} from GitHub Releases..."
    if command -v curl &>/dev/null; then
        curl -fSL -o "$dest" "$url"
    else
        wget -q -O "$dest" "$url"
    fi

    if [[ ! -f "$dest" ]]; then
        red "ERROR: Download failed."
        red "URL: ${url}"
        exit 1
    fi

    green "Downloaded: ${dest}"
    echo "$dest"
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

    local zip_file
    zip_file=$(ls "${DIST_DIR}/${PLUGIN_NAME}"-*.zip 2>/dev/null | head -1)
    if [[ -z "$zip_file" ]]; then
        red "ERROR: Plugin zip not found in ${DIST_DIR}/"
        exit 1
    fi
    green "Plugin zip built: ${zip_file}"
    echo "$zip_file"
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
    $es_plugin install --batch "file://$(realpath "$zip_path")"

    green "✅ Plugin installed! Restart Elasticsearch to activate."
    cat <<'USAGE'

  Create an index with the Kazakh stemmer:

    PUT /my_index
    {
      "settings": {
        "analysis": {
          "filter":   { "kaz_stem": { "type": "kazsearch_stem" } },
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
USAGE
}

# ── Docker mode ──────────────────────────────────────────────
docker_mode() {
    local version="${1:-}"

    if [[ -z "$version" ]]; then
        # Build from source
        build_native
        local zip_file
        zip_file=$(build_plugin)
        version=$(basename "$zip_file" | sed "s/${PLUGIN_NAME}-//; s/\.zip//")
    else
        # Download release
        local zip_path
        zip_path=$(download_plugin "$version")
        mkdir -p "${DIST_DIR}"
        cp "$zip_path" "${DIST_DIR}/"
    fi

    info "Building Docker image..."
    cd "${REPO_ROOT}/elastic/docker"
    docker build -t kazsearch-elastic:"${version}" \
        --build-arg PLUGIN_VERSION="${version}" \
        -f Dockerfile "${JAVA_DIR}"

    green "✅ Docker image built: kazsearch-elastic:${version}"
    echo ""
    echo "  Run it:"
    echo "    docker run -d --name es-kazsearch \\"
    echo "      -p 9200:9200 \\"
    echo "      -e discovery.type=single-node \\"
    echo "      -e xpack.security.enabled=false \\"
    echo "      kazsearch-elastic:${version}"
}

# ── Main ─────────────────────────────────────────────────────
VERSION=""

case "${1:-}" in
    --build)
        build_native
        zip_file=$(build_plugin)
        install_plugin "$zip_file"
        ;;
    --docker)
        shift
        if [[ "${1:-}" == "--version" ]]; then
            VERSION="$2"
        fi
        docker_mode "$VERSION"
        ;;
    --version)
        VERSION="${2:-}"
        if [[ -z "$VERSION" ]]; then
            red "ERROR: --version requires a value (e.g., --version 2.1.0)"
            exit 1
        fi
        zip_path=$(download_plugin "$VERSION")
        install_plugin "$zip_path"
        ;;
    --help|-h)
        usage
        ;;
    "")
        # Default: download latest and install
        VERSION=$(detect_latest_version)
        info "Latest release: v${VERSION}"
        zip_path=$(download_plugin "$VERSION")
        install_plugin "$zip_path"
        ;;
    *)
        # Treat argument as path to pre-built zip
        zip_path="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
        install_plugin "$zip_path"
        ;;
esac

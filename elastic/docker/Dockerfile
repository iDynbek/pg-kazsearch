ARG PLUGIN_VERSION=0.1.0
FROM docker.elastic.co/elasticsearch/elasticsearch:8.17.0

ARG PLUGIN_VERSION
COPY build/distributions/analysis-kazsearch-${PLUGIN_VERSION}.zip /tmp/plugin.zip
RUN bin/elasticsearch-plugin install --batch file:///tmp/plugin.zip; \
    rm -f /tmp/plugin.zip || true

# Copy the platform-appropriate native lib to the plugin root
RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64|amd64) PLATFORM=linux-x86_64 ;; \
      aarch64|arm64) PLATFORM=linux-aarch64 ;; \
      *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    PLUGIN_DIR=/usr/share/elasticsearch/plugins/analysis-kazsearch && \
    if [ -d "$PLUGIN_DIR/$PLATFORM" ]; then \
      cp "$PLUGIN_DIR/$PLATFORM/"*.so "$PLUGIN_DIR/"; \
    fi

ENV LD_LIBRARY_PATH=/usr/share/elasticsearch/plugins/analysis-kazsearch

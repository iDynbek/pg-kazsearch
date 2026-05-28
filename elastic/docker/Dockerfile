ARG PLUGIN_VERSION=0.1.0
FROM docker.elastic.co/elasticsearch/elasticsearch:8.17.0

ARG PLUGIN_VERSION
COPY build/distributions/analysis-kazsearch-${PLUGIN_VERSION}.zip /tmp/plugin.zip
RUN bin/elasticsearch-plugin install --batch file:///tmp/plugin.zip; \
    rm -f /tmp/plugin.zip || true

ENV LD_LIBRARY_PATH=/usr/share/elasticsearch/plugins/analysis-kazsearch

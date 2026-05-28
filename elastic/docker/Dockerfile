FROM docker.elastic.co/elasticsearch/elasticsearch:8.17.0

COPY build/distributions/analysis-kazsearch-0.1.0.zip /tmp/analysis-kazsearch-0.1.0.zip
RUN bin/elasticsearch-plugin install --batch file:///tmp/analysis-kazsearch-0.1.0.zip; \
    rm -f /tmp/analysis-kazsearch-0.1.0.zip || true

ENV LD_LIBRARY_PATH=/usr/share/elasticsearch/plugins/analysis-kazsearch

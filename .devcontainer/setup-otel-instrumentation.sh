WORKSPACE_DIR=$(dirname $(dirname $(realpath $0)))

OTEL_ENV="$WORKSPACE_DIR/.otelenv"

if [ -f "$OTEL_ENV" ]; then
    echo "Skipping otelenv setup"
else
    echo "Setting up otelenv"

    pip install elastic-opentelemetry
    echo "OTEL_EXPORTER_OTLP_ENDPOINT=" >> "$OTEL_ENV"
    echo "OTEL_EXPORTER_OTLP_HEADERS=" >> "$OTEL_ENV"

    echo "OTEL_SERVICE_NAME=homeassistant-elasticsearch" >> "$OTEL_ENV"
    echo "OTEL_TRACES_EXPORTER=console,otlp" >> "$OTEL_ENV"
    echo "OTEL_METRICS_EXPORTER=console,otlp" >> "$OTEL_ENV"
    echo "OTEL_LOGS_EXPORTER=console,otlp" >> "$OTEL_ENV"
    echo "OTEL_RESOURCE_ATTRIBUTES=service.name=ha-elasticsearch,deployment.environment=development" >> "$OTEL_ENV"

    edot-bootstrap --action=install
    echo
    echo "You must provide the OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS in the otelenv file before proceeding further"
fi


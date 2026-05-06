# Observability Backends

OGX exports traces and metrics in standard OpenTelemetry Protocol (OTLP) format — anything that speaks OTLP can receive them. This guide sets up a receiver so Module 10's Jaeger screenshot moment actually has a UI to point at.

This guide covers two paths:

- **Path A — Jaeger all-in-one**. A single Deployment with a built-in OTLP receiver and trace UI. Right for the tutorial.
- **Path B — your cluster's existing observability stack**. Right when you've already got Tempo / a managed OpenTelemetry Collector / a corporate observability platform.

## Path A: Jaeger all-in-one

Jaeger's all-in-one image bundles an OTLP receiver, an in-memory trace store, and the Jaeger UI in a single container. Perfect for tutorials and dev clusters; not for production.

### 1. Create a namespace

```bash
oc new-project observability
```

### 2. Deploy Jaeger

Save as `jaeger.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger
  namespace: observability
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jaeger
  template:
    metadata:
      labels:
        app: jaeger
    spec:
      containers:
        - name: jaeger
          image: jaegertracing/all-in-one:1.76.0
          env:
            - name: COLLECTOR_OTLP_ENABLED
              value: "true"
          ports:
            - name: ui
              containerPort: 16686
            - name: otlp-grpc
              containerPort: 4317
            - name: otlp-http
              containerPort: 4318
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: jaeger
  namespace: observability
spec:
  selector:
    app: jaeger
  ports:
    - name: ui
      port: 16686
      targetPort: 16686
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
    - name: otlp-http
      port: 4318
      targetPort: 4318
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: jaeger-ui
  namespace: observability
spec:
  to:
    kind: Service
    name: jaeger
  port:
    targetPort: ui
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

```bash
oc apply -f jaeger.yaml
oc rollout status deployment/jaeger -n observability --timeout=120s
```

### 3. Get the UI URL

```bash
JAEGER_UI="https://$(oc get route jaeger-ui -n observability -o jsonpath='{.spec.host}')"
echo "$JAEGER_UI"
```

Open it in a browser. You should see the Jaeger UI with no services listed yet — that's expected; nothing has emitted traces.

### 4. Point OGX at the OTLP endpoint

OGX is in a different namespace, so use the cluster-internal DNS name. The OTLP HTTP endpoint is what we'll point OGX at.

!!! warning "v0.7.1 needs the `opentelemetry-instrument` wrapper to export traces"
    OGX v0.7.1's built-in telemetry initializer only sets up a `MeterProvider` (metrics), not a `TracerProvider` — the routers create spans, but they go to the no-op default tracer and are discarded. To make traces flow, override the container entrypoint to wrap the server with `opentelemetry-instrument`, which auto-configures both providers from env vars. The `opentelemetry-distro` and `opentelemetry-instrumentation-*` packages are already in the starter image.

    The override below replicates the existing entrypoint's v0.7.1 startup path (uvicorn factory mode); if you upgrade to a future distribution image whose entrypoint differs, refresh this from the upstream image's command. Track [llama-stack#5189](https://github.com/meta-llama/llama-stack/issues) for native `TracerProvider` support landing upstream — once it does, the `command`/`args` override here becomes unnecessary.

Edit the `LlamaStackDistribution` from [Install OGX](install-ogx.md):

```bash
oc edit llamastackdistribution ogx -n ogx
```

Add the `command`/`args` override and four env vars under `spec.server.containerSpec`:

```yaml
spec:
  server:
    containerSpec:
      command: ["opentelemetry-instrument"]
      args:
        - uvicorn
        - llama_stack.core.server.server:create_app
        - --host
        - "0.0.0.0"
        - --port
        - "8321"
        - --workers
        - "1"
        - --factory
      env:
        # ...existing entries (VLLM_URL etc.)...
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://jaeger.observability.svc.cluster.local:4318"
        - name: OTEL_SERVICE_NAME
          value: "ogx"
        - name: OTEL_TRACES_EXPORTER
          value: "otlp"
        - name: OTEL_EXPORTER_OTLP_PROTOCOL
          value: "http/protobuf"
```

`OTEL_SERVICE_NAME` controls the name traces appear under in Jaeger; default is `llama-stack`, which is why we override. `OTEL_TRACES_EXPORTER=otlp` and `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` tell auto-instrumentation to send via OTLP HTTP (Jaeger's all-in-one OTLP receiver speaks both gRPC and HTTP; HTTP is the simpler path on port 4318).

The Operator rolls the pod automatically. Wait for it:

```bash
oc rollout status deployment/ogx -n ogx --timeout=180s
```

### 5. Verify traces flow

Hit OGX's `/v1/chat/completions` to generate a span:

```bash
curl -s "$OGX_ENDPOINT/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vllm/RedHatAI/gpt-oss-20b",
    "messages": [{"role": "user", "content": "Say hi."}],
    "max_tokens": 300
  }' > /dev/null
```

Refresh the Jaeger UI. The **Service** dropdown should now include `ogx`. Pick it, click **Find Traces**, and you'll see a trace per request with spans for inference and any tool calls OGX orchestrated.

### 6. Export for Module 10

```bash
export JAEGER_UI="$JAEGER_UI"
```

Module 10 references this URL when telling you to go look at a trace.

## Path B: existing observability stack

If your cluster already has an observability stack — Red Hat OpenShift distributed tracing (Tempo Operator), a managed OpenTelemetry Collector, Datadog Agent with OTLP receiver, etc. — point OGX at its OTLP endpoint instead of Jaeger.

You need two things from your platform team:

| Item | Format | Notes |
|------|--------|-------|
| OTLP endpoint URL | `http://collector.<ns>.svc.cluster.local:4318` | HTTP receiver port |
| Trace UI URL | varies | Tempo, Grafana Tempo datasource, Datadog APM, etc. |

Set `OTEL_EXPORTER_OTLP_ENDPOINT` on the `LlamaStackDistribution` to the collector URL. The trace UI is whatever your platform team gives you — Module 10's "go find your trace" step works the same whether you're looking at Jaeger or Tempo.

If you're running OpenShift's [distributed tracing platform (Tempo)](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/distributed_tracing/distributed-tracing-platform-tempo), the OTLP receiver is part of the `TempoStack` CR (look for `spec.template.distributor`).

## Next

**[Module 10: Guardrails and Observability](../10-guardrails-and-observability.md)**.

## Further reading

- [Jaeger getting started](https://www.jaegertracing.io/docs/latest/getting-started/)
- [OTLP specification](https://opentelemetry.io/docs/specs/otlp/)
- [OGX telemetry](https://ogx-ai.github.io/docs/building_applications/telemetry)

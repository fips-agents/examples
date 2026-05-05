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
          image: jaegertracing/all-in-one:1.62
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

OGX is in a different namespace, so use the cluster-internal DNS name. The OTLP HTTP endpoint is what OGX's `telemetry` provider expects.

Edit the `OGXDistribution` from [Install OGX](install-ogx.md):

```bash
oc edit ogxdistribution ogx -n ogx
```

Add or update the `OTEL_EXPORTER_OTLP_ENDPOINT` env var under `spec.server.containerSpec.env`:

```yaml
spec:
  server:
    containerSpec:
      env:
        # ...existing entries...
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://jaeger.observability.svc.cluster.local:4318"
```

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
    "model": "ibm-granite/granite-3.3-8b-instruct",
    "messages": [{"role": "user", "content": "Say hi."}]
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

Set `OTEL_EXPORTER_OTLP_ENDPOINT` on the `OGXDistribution` to the collector URL. The trace UI is whatever your platform team gives you — Module 10's "go find your trace" step works the same whether you're looking at Jaeger or Tempo.

If you're running OpenShift's [distributed tracing platform (Tempo)](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/distributed_tracing/distributed-tracing-platform-tempo), the OTLP receiver is part of the `TempoStack` CR (look for `spec.template.distributor`).

## Next

**[Module 10: Guardrails and Observability](../10-guardrails-and-observability.md)**.

## Further reading

- [Jaeger getting started](https://www.jaegertracing.io/docs/latest/getting-started/)
- [OTLP specification](https://opentelemetry.io/docs/specs/otlp/)
- [OGX telemetry](https://ogx-ai.github.io/docs/building_applications/telemetry)

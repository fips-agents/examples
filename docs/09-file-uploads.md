# 9. File Uploads and Document Processing

Your hardened stack handles chat, tool calls, code execution, and observability.
The next thing real users will ask for is the ability to *attach a document*
and have the agent read it. PDFs of regulations. Spreadsheets of measurements.
Slide decks of meeting notes. In this module you'll add the file-upload track
end-to-end: the agent's `/v1/files` endpoint, the streaming gateway proxy, the
drag-drop UI, Docling-based parsing, and a ClamAV sidecar for virus scanning.

## What you'll build

```
Browser ──▶  UI    ──▶  Gateway      ──▶  Agent
            (drag,    (size cap +        (POST /v1/files,
             paste,    MIME allowlist,    Docling parse,
             chip)     streaming proxy)   FileStore persist)
                                                │
                                                ▼
                                         ClamAV sidecar
                                         (localhost:8088)
```

The pipeline runs in this order on every upload: **size cap → MIME sniff →
virus scan → parse → persist**. Each layer is independent — disabling the
scanner doesn't change the parser, swapping the FileStore backend doesn't
change the gateway. By the end of this module a user will be able to drop a
PDF onto the chat input, watch a progress chip while it uploads, and ask
questions whose answers come from the document's contents.

## Use cases

| Use case | What the agent does |
|----------|---------------------|
| **Document Q&A** | "Summarise sections 3 and 4 of this regulation" |
| **Report analysis** | "Pull the action items from the attached meeting notes" |
| **Data ingestion** | "Validate this CSV against the schema and flag anomalies" |
| **Compliance review** | "Cross-check this contract against the policy library" |

In every case the agent's job is the same: receive an opaque `file_id`,
retrieve the extracted text, and reason over it. The framework handles
everything between "user clicked attach" and "extracted text is ready".

## Configuring the agent server

File uploads are off by default. Toggle them on with three changes to
`agent.yaml`:

```yaml
server:
  storage:
    backend: ${STORAGE_BACKEND:-sqlite}    # files needs persistence
    sqlite_path: ${SQLITE_PATH:-./agent.db}

  files:
    enabled: ${FILES_ENABLED:-true}
    backend: ${FILES_BACKEND:-sqlite}      # sqlite | postgres | "" (Null)
    max_file_size_bytes: 52428800          # 50 MiB
    bytes_dir: ./files                     # PVC mount in production
    allowed_mime_types: []                 # empty defers to gateway
    scanner:
      url: "${FILES_SCANNER_URL:-}"        # ClamAV sidecar URL
      timeout_seconds: 30.0
      fail_mode: ${FILES_SCANNER_FAIL_MODE:-open}
```

The `[files]` extra pulls in **Docling** (text extraction) and
**python-magic** (content-based MIME sniffing). It adds about 500 MB to the
container image because of Docling's torch and transformers dependencies, so
keep it opt-in for agents that don't ingest files:

```toml
# pyproject.toml
[project.optional-dependencies]
files = ["fipsagents[files]"]
```

Rebuild the container with `make build` after enabling the extra. The
endpoint surface comes online automatically:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/files` | Upload a file (multipart) |
| `GET` | `/v1/files?session_id=<id>` | List a session's files |
| `GET` | `/v1/files/{file_id}` | Fetch metadata for a single file |
| `DELETE` | `/v1/files/{file_id}` | Remove metadata + bytes |

A successful upload returns the JSON metadata record:

```json
{
  "file_id": "file_abc123def456...",
  "filename": "report.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 124567,
  "sha256": "9f2b...",
  "parse_status": "completed",
  "session_id": "s_42",
  "created_at": "2026-04-28T18:09:42+00:00"
}
```

Hold on to that `file_id`. Pass it back to `/v1/chat/completions` via the
`file_ids` array, and the framework injects the file's extracted text into
the conversation before the LLM sees the user's message:

```bash
curl http://my-agent:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [{"role": "user", "content": "What are the action items?"}],
    "file_ids": ["file_abc123def456..."]
  }'
```

No tool call required. The injection is automatic.

## Docling: format support and parser semantics

`PlaintextParser` handles `text/*`, `application/json`, and a small structured-
text allowlist (markdown, csv, yaml). Everything else routes to **Docling**,
which converts a wide range of formats to clean Markdown:

| Format | MIME types | What Docling extracts |
|--------|------------|-----------------------|
| **PDF** | `application/pdf` | Text, tables, headings, page structure |
| **Office documents** | `application/vnd.openxmlformats-officedocument.*` | Word, Excel, PowerPoint content |
| **HTML** | `text/html` | Stripped of nav/script, content preserved |
| **Images** | `image/png`, `image/jpeg` | OCR via the bundled OCR engine |

Parsing runs **inline** — the upload response only returns once
`parse_status` is `completed` (or `failed`). For large documents this can
take seconds. The framework runs Docling under `asyncio.to_thread` so it
doesn't block the event loop, but if your typical upload is a 200-page PDF
you'll want to consider background-queue parsing (a future framework
feature; see `agent-template#100`).

`parse_status` transitions:

- `pending` — bytes uploaded, parsing not yet attempted
- `processing` — parse in flight
- `completed` — `extracted_text` is populated
- `failed` — `parse_error` is populated
- `skipped` — file type intentionally not parsed (binary, unknown)

A `failed` parse still persists the upload — the user gets a `file_id` they
can reference, and a tool can still inspect the raw bytes via
`get_bytes(file_id)`.

## Persistence: SQLite, Postgres, and bytes layout

The `FileStore` ABC has three concrete backends today:

- **`null`** — uploads accepted then discarded (smoke testing, demos).
- **`sqlite`** — metadata in SQLite, bytes on local FS sharded by `file_id`
  prefix. Single-replica only.
- **`postgres`** — metadata in Postgres, bytes still on local FS. Use when
  the agent runs alongside other Postgres-backed features (sessions,
  feedback, traces) so you only run one database.

Both `sqlite` and `postgres` write bytes to `bytes_dir`, which **must be a
PVC** in production. Without one, every pod restart loses uploaded files.
The reference Helm values put a sane default in place:

```yaml
# chart/values.yaml — production fragment
config:
  STORAGE_BACKEND: postgres
  # DATABASE_URL is injected from a Secret — see Module 8.  Use the
  # postgresql:// scheme; the actual credentials never live in values.yaml.
  FILES_ENABLED: "true"
  FILES_BACKEND: postgres

files:
  enabled: true
  backend: postgres
  # bytes_dir defaults to ./files inside the container; mount a PVC there.
```

!!! warning "S3-compatible bytes backend is not yet shipped"
    The framework keeps bytes on local FS regardless of the metadata
    backend. An S3-compatible `BytesStore` ABC is on the roadmap. Until
    it lands, multi-replica deployments need a `ReadWriteMany` PVC or a
    sticky-session ingress to keep uploads consistent.

### MinIO as the bytes target (looking ahead)

When the S3 backend lands, the recommended setup will be a **MinIO**
deployment alongside the agent:

```bash
# Future scaffolding (not yet shipped):
helm install minio bitnami/minio \
  -n calculus-agent \
  --set auth.rootUser=agent --set auth.rootPassword='<from-secret>' \
  --set defaultBuckets=agent-files

# agent.yaml would then point at:
files:
  bytes_backend: s3
  s3:
    endpoint: http://minio:9000
    bucket: agent-files
    access_key_secret: minio-credentials
```

MinIO is on-cluster, supports the S3 API, and works with the FIPS-validated
TLS settings discussed in [Module 8](08-secrets-and-production.md). For now
treat this as documentation of intent — keep an eye on agent-template#100
for the real release.

## Security: defense in depth

User-uploaded files are an obvious attack surface. The stack runs three
independent security layers, and the layered behavior is not an accident —
each one catches a class of failure the others can miss.

### Layer 1: Size cap (gateway and agent)

The **gateway** enforces `GATEWAY_FILES_MAX_BYTES` (default 25 MiB) by
inspecting `Content-Length` and falling back to a `MaxBytesReader` mid-
stream. Requests over the cap return 413 *before any byte reaches the
agent*. The **agent** then enforces a second cap via
`server.files.max_file_size_bytes` (default 50 MiB) — set the agent cap
higher than the gateway cap so honest uploads aren't double-rejected.

### Layer 2: MIME validation

The gateway validates the multipart file part's declared `Content-Type`
against `GATEWAY_FILES_ALLOWED_MIME` (supports `image/*` wildcards). The
agent runs **libmagic** content sniffing on the bytes themselves and
re-validates against `server.files.allowed_mime_types`. A client cannot
rename `evil.exe` to `report.pdf` and lie about the MIME header — libmagic
reads magic bytes:

```python
# fipsagents/server/files.py — abridged
def detect_mime(data: bytes) -> str | None:
    # python-magic + libmagic; falls back to client claim with a warning
    # when libmagic isn't available.
    ...

# In the upload handler:
sniffed = detect_mime(data)
mime_type = sniffed or file.content_type or "application/octet-stream"
if files_cfg.allowed_mime_types and mime_type not in files_cfg.allowed_mime_types:
    raise HTTPException(status_code=415, detail=...)
```

### Layer 3: Virus scanning (ClamAV sidecar)

For production deployments, run **ClamAV** as a sidecar container in the
same pod. The agent's `HttpScanner` POSTs each upload to a configurable URL
and expects a JSON response of `{"infected": bool, "viruses": [...]}`:

```yaml
# chart/values.yaml — enable the sidecar
files:
  enabled: true
  virusScanner:
    enabled: true
    failMode: closed              # production: 503 the upload on scanner errors
    image:
      repository: clamav/clamav
      tag: stable
    persistence:
      enabled: true               # PVC for the signature database
      size: 2Gi
```

The Helm chart wires `FILES_SCANNER_URL=http://localhost:8088/scan` onto
the agent container automatically when both `files.enabled` and
`files.virusScanner.enabled` are true.

!!! tip "ClamAV requires an HTTP shim"
    The reference `clamav/clamav:stable` image ships clamd on TCP 3310 but
    does not expose the `{infected, viruses}` JSON contract on its own.
    Either build a custom image with a small FastAPI shim that wraps clamd,
    or deploy a tiny adapter container alongside it. The framework's
    contract is documented at
    `packages/fipsagents/src/fipsagents/server/scanner.py`.

`fail_mode` controls behavior when the scanner is unreachable: `open`
(accept the upload, log a warning — fine for development) or `closed`
(return 503 — production-recommended). Set it to `closed` once you have
confidence in the sidecar's uptime.

## The gateway: streaming proxy, not just pass-through

The gateway-template's `FilesUploadHandler` is purpose-built for multipart:
it walks the inbound multipart synchronously up to the first file part,
validates its `Content-Type` against the allowlist, then streams the body
through to the agent via a `multipart.Writer` over an `io.Pipe`. The body
is **never buffered in gateway memory**.

This matters because the gateway is the customer-facing entry point and
needs to fail fast on obviously-bad uploads. Validation happens before the
upstream request fires, so a 415 response never costs a TCP connection to
the agent. Configure via four env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_FILES_MAX_BYTES` | `25m` (26 MiB) | Hard cap; supports `k`/`m`/`g` |
| `GATEWAY_FILES_ALLOWED_MIME` | unset | Comma-separated allowlist; `image/*` ok |
| `GATEWAY_FILES_UPLOAD_TIMEOUT` | `5m` | Per-request deadline for backend POST |

The Helm chart's `files` block sets all three. Match the agent's caps and
allowlist so a request the gateway accepts never gets bounced by the
agent on the next layer.

## The UI: drag, paste, and progress chips

The chat UI exposes file upload through three input affordances:

- **Drag-and-drop** — dragging files over the input shows a dashed-border
  drop zone overlay
- **Paste** — pasting a clipboard image or file from Finder triggers an
  upload alongside any typed message
- **File picker** — a paperclip button opens the OS file dialog

Each attachment renders as a chip with a real **determinate progress bar**
(via `XMLHttpRequest`'s upload-progress events; `fetch` lacks them). The
chip stores `{status: uploading | ready | failed, progress, file_id?,
error?}`. Send is disabled while any chip is still uploading.

When the user submits, the UI snapshots `readyFileIds()` and includes them
on the chat-completion request body as `file_ids: [...]`. Failed chips
don't block sending — they have no `file_id` so they're effectively
no-ops.

Server-side errors surface directly on the chip:

| Status | Surfaced as |
|--------|-------------|
| 413 | "File too large" |
| 415 | "File type not allowed" |
| 422 | "File rejected (virus scan)" |
| any other | JSON `error` field or "HTTP NNN" |

Configure the UI's pre-flight cap via two env vars surfaced through
`/api/config`:

```yaml
# chart/values.yaml for the UI
files:
  maxBytes: "25m"                          # match the gateway
  allowedMime: "application/pdf,image/*"   # optional, defers to gateway when empty
```

## Lab exercise: PDF Q&A on the calculus agent

Add a PDF Q&A capability to the calculus agent you've been building.

**Step 1: Enable the upload track**

Edit `calculus-agent/agent.yaml`:

```yaml
server:
  storage:
    backend: sqlite
    sqlite_path: ./agent.db
  files:
    enabled: true
    backend: sqlite
    max_file_size_bytes: 52428800
    allowed_mime_types:
      - application/pdf
      - text/plain
```

Add the extra to `pyproject.toml` and reinstall:

```bash
cd calculus-agent
sed -i '' 's/^dev = \[/files = ["fipsagents[files]"]\ndev = [/' pyproject.toml
pip install -e '.[files]'
```

**Step 2: Test the endpoint locally**

```bash
make run-local &
echo "%PDF-1.4 stub" > /tmp/example.pdf
curl -F "file=@/tmp/example.pdf" http://localhost:8080/v1/files | jq
```

You should see a `file_id` and `parse_status: "completed"` (or `skipped`
for the stub).

**Step 3: Try a real document**

Drop in a small actual PDF:

```bash
curl -F "file=@./real-document.pdf" http://localhost:8080/v1/files | jq -r .file_id > /tmp/file_id
curl http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d "{
    \"messages\": [{\"role\": \"user\", \"content\": \"Summarise this document in 3 bullets.\"}],
    \"file_ids\": [\"$(cat /tmp/file_id)\"]
  }" | jq -r '.choices[0].message.content'
```

The agent answers using the document's content. No tool call was needed —
the framework injected the extracted text before the LLM saw the prompt.

**Step 4: Verify the security controls**

Try uploading something disallowed:

```bash
echo MZbinary > /tmp/evil.exe
curl -i -F "file=@/tmp/evil.exe;type=application/x-msdownload" http://localhost:8080/v1/files
# HTTP/1.1 415 Unsupported Media Type
# {"detail": "MIME type 'application/x-msdownload' is not in the allowlist"}
```

Try uploading something oversized:

```bash
dd if=/dev/zero of=/tmp/huge.pdf bs=1M count=100 2>/dev/null
curl -i -F "file=@/tmp/huge.pdf;type=application/pdf" http://localhost:8080/v1/files
# HTTP/1.1 413 Request Entity Too Large
```

**Step 5: Deploy with the gateway and UI**

Once the agent is happy locally, redeploy:

```bash
make deploy PROJECT=calculus-agent
helm upgrade calculus-gateway ../calculus-gateway/chart \
  -n calculus-agent \
  --set files.maxBytes=25m \
  --set files.allowedMime="application/pdf,image/*"
helm upgrade calculus-ui ../calculus-ui/chart \
  -n calculus-agent \
  --set files.maxBytes=25m
```

Open the UI, drag a PDF onto the chat input, watch the progress chip,
then ask a question.

## Verifying everything is wired up

```bash
# Agent: file uploads enabled?
curl http://my-agent:8080/v1/agent-info | jq '.server.files.enabled'

# Gateway: configured caps?
oc logs deployment/calculus-gateway -n calculus-agent | grep files_max_bytes

# UI: config exposed?
curl http://my-ui:3000/api/config | jq

# Round-trip: upload through the gateway and confirm the chip path
echo test > /tmp/x.txt
curl -F "file=@/tmp/x.txt" https://calculus-gateway.apps.cluster/v1/files | jq
```

If any layer rejects, the error surfaces with a JSON message — read the
status code first, then the body. The most common gotchas are
gateway/agent allowlist mismatches and forgotten PVCs eating uploaded
files on pod restart.

## What's next

You now have file ingestion wired across the full stack. Some directions
to take it further:

- **Background-queue parsing** for large documents (multi-hundred-page
  PDFs). Tracked on `agent-template#100`.
- **Chunking + pgvector retrieval** so the agent doesn't dump entire
  documents into context. Also tracked on `agent-template#100`; needs
  a fresh ADR before code.
- **Custom parsers** beyond Docling — for example, the
  [xml-analysis-framework](https://github.com/redhat-ai-americas/xml-analysis-framework)
  for S1000D technical documentation, plugged in via the `FileParser`
  ABC.
- **Per-tenant quotas** so a single user can't monopolise the bytes PVC.
  Combine with the per-tenant cost tracking from
  [Module 8](08-secrets-and-production.md).

The patterns from this module — opt-in extras, layered security,
streaming proxies, and explicit failure modes — apply equally to any
new ingestion surface you bolt onto the agent. File uploads are the
first; webhooks, message-queue ingestion, and scheduled pulls follow
the same shape.

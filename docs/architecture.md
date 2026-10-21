# Architecture

The dependency direction is inward: infrastructure adapters depend on application ports and
domain types, never the reverse. CLI and the MCP adapter invoke the same application
services. Ingestion produces normalized domain data without knowing which embedding provider
or index implementation is active.

```text
CLI / MCP / optional HTTP
          |
  Application services
          |
 Domain models and ports
          ^
 SQLite / Qdrant / source and model adapters
```

SQLite is the source of truth for source versions, documents, chunks, synchronization state,
and the active-snapshot FTS5/BM25 index. Qdrant is the replaceable dense retrieval index. Both
retrieval channels are constrained by the active SQLite source versions. An embedding profile identifies its model,
revision, vector shape, normalization, pooling, and preprocessing. A profile change that is
not index-compatible requires a separate Qdrant collection and atomic activation; reranker
changes do not require reindexing.

Documents and repositories are untrusted input. Source adapters enforce size, path, network,
and allowlist boundaries before content enters the application. Secrets remain outside YAML,
metadata databases, vector payloads, and logs.

## Milestone 1 decisions

- Domain models use dataclasses and protocols without Pydantic or SQLAlchemy dependencies.
- Configuration uses strict Pydantic models; environment variables override YAML values.
- SQLite access is asynchronous, while migrations use Alembic through its async bridge.
- Logs are structured and emitted to stderr in preparation for MCP stdio safety.
- Heavy model frameworks remain optional dependencies and are not loaded by the foundation.

## Retrieval decisions

- Snapshot activation replaces a source's BM25 rows in the same SQLite transaction that marks
  the new source version active.
- Dense and sparse adapters implement application protocols; fusion and result shaping remain
  infrastructure-independent.
- RRF combines channel ranks before a small trust tie-breaker. Trust cannot compensate for a
  missing relevance signal.
- Reranking runs after fusion on a bounded candidate set and does not require index changes.
- Local and HTTP model providers implement domain protocols. Provider endpoints and API keys
  are resolved from named environment variables only.
- FastMCP is a thin stdio adapter. It owns no retrieval logic and exposes only three read-only
  tools. A lazy per-profile service pool reuses model instances and closes all resources during
  server shutdown.
- Evaluation calls the same search service through a diagnostic response that adds timings but
  does not change normal CLI or MCP results. Metric calculation stays in the domain layer; JSONL,
  report files, hardware inspection, and service composition remain adapters.

## Documented implementation deviation

FastMCP 1.26 generates top-level argument models that ignore unknown keys. The MCP adapter
switches those generated models to Pydantic `extra=forbid` after registration and regenerates
their schemas. This is intentionally isolated in `mcp/server.py` and covered by an in-memory MCP
test; it should be rechecked when upgrading the MCP dependency.

# Engineering Knowledge MCP

A local, read-only engineering knowledge base for Codex in the JetBrains AI Assistant.
The project will ingest curated PDFs, documentation websites, Git repositories, and local
directories, then expose a small set of referenced excerpts through MCP.

## Prerequisites

- Python 3.12 or newer (the development environment uses Python 3.13)
- Docker with Compose
- Git
- Optional CUDA-capable NVIDIA GPU; CPU fallback will be supported

## Development setup

```bash
/home/mawi/.penv/python-local-3.13/bin/python3.13 -m pip install -e '.[dev,models]'
cp config/settings.example.yaml config/settings.yaml
cp config/sources.example.yaml config/sources.yaml
mkdir -p data
alembic upgrade head
```

Start Qdrant and validate the configuration:

```bash
docker compose up -d qdrant
kb validate-config
```

The first local synchronization downloads the configured embedding model. Run synchronization
and hybrid dense/BM25 search with:

```bash
kb sync --source local-pdfs
kb sync --source python-patterns
kb search "How should architectural boundaries be designed?"
kb search "dependency injection" --source local-pdfs --json
kb models inspect --profile local_bge
kb models benchmark --profile local_bge
```

`kb sync` never runs when the MCP server starts. A repeated sync with unchanged source files
does not extract or embed them again. `--force` intentionally rebuilds all configured PDF
chunks.

Start the read-only MCP server over stdio after synchronization:

```bash
KB_PYTHON=/home/mawi/.penv/python-local-3.13/bin/python3.13 ./scripts/start-mcp.sh
```

The process writes only MCP protocol messages to stdout. See
[JetBrains MCP setup](docs/mcp-jetbrains.md) for registration examples.

Run the curated retrieval evaluation for one profile or compare profiles:

```bash
kb evaluate --profile local_bge
kb evaluate --compare local_bge local_qwen cloud
```

Reports are written as JSON and Markdown below `reports/evaluation`. Adapt the starter questions
to the sources actually indexed before using the 80 percent Recall@5 target for model selection.
See [evaluation](docs/evaluation.md) for metric semantics and reproducible comparisons.

## Current status

Milestones 1 through 8 provide the project foundation, PDF, Git, and controlled website
ingestion, local embeddings, versioned Qdrant and SQLite FTS5 indexes, incremental
synchronization, and hybrid CLI search with filtering, RRF, deduplication, diversification, and
server-side token budgets. Local BGE/Qwen and HTTP reranking, local and OpenAI-compatible
embeddings, GPU inspection, bounded OOM recovery, and model benchmarks are integrated. MCP
transport with three read-only tools, profile evaluation, security checks, recovery tests, and
operational documentation are integrated.

## Quality checks

```bash
pytest
ruff check .
ruff format --check .
mypy
python -m build
docker compose config --quiet
```

See [architecture](docs/architecture.md) for the dependency boundaries and
[retrieval](docs/retrieval.md) for the search pipeline.
Model setup and GPU behavior are documented in [models](docs/models.md).
Backup, restore, reindexing, and troubleshooting are documented in
[operations](docs/operations.md). The final evidence matrix is in
[acceptance](docs/acceptance.md).

Contributors and AI agents must start with the durable
[development contract](docs/development.md), which records invariants, extension rules, scope
limits, quality gates, and known follow-up work.

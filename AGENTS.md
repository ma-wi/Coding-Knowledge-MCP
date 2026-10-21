# Repository working rules

- Before changing behavior, read `docs/specifications.md`, `docs/development.md` and the relevant topic documentation.
- Make changes in small, reviewable steps and inspect existing code first.
- Do not add large dependencies without documenting the reason.
- Never commit secrets or include them in logs, SQLite, or Qdrant.
- Unit tests must not access the network.
- When MCP uses stdio, protocol output is the only output allowed on stdout; logs go to stderr.
- Keep Domain and Application layers independent of infrastructure frameworks.
- Make all external interfaces mockable.
- Run tests, linting, and type checking after every milestone.
- Document deviations from the target architecture.
- Do not implement functionality outside the MVP without an explicit reason.

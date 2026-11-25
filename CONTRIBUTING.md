# Contributing

Thanks for helping! Issues and pull requests are welcome in English or German.

## Ways to help

- **Bug reports:** what you did, what happened, what you expected; QuietBoard version (`System` tab), `docker compose logs status` (remove tokens and addresses).
- **Host recipes:** your NAS, router or backup tool – how to report updates and jobs to QuietBoard.
- **Translations:** German and English first; more languages later via Weblate.
- **Docs:** unclear steps are bugs, too.

## Development

```bash
make setup     # venv (outside the repo, ~/.cache/quietboard), tools, pre-commit hooks
make dev       # http://localhost:8088 with sample data, live reload
make test lint # before every commit
make e2e       # fresh install in a throwaway Docker project, like CI
```

Guidelines:

- Code, identifiers and commit messages in English; user-facing texts currently German.
- No secrets or personal data (domains, IPs, names) in the repository – gitleaks runs in pre-commit and CI.
- Every container gets a `mem_limit`; upstream images are pinned to exact versions.
- Scripts in `bootstrap/` are embedded into `compose.yaml` – run `make configs` after changing them.
- One topic per pull request; CI (lint, tests, e2e, license check, docs) must be green.

## Releases

Maintainers run `make release VERSION=X.Y.Z` on an up-to-date `main` with green CI. This updates `CHANGELOG.md`, tags `vX.Y.Z` and triggers images (`vX.Y.Z`, `vX.Y`, `vX`, `latest`) and the GitHub release with install bundle, SBOM and checksums.

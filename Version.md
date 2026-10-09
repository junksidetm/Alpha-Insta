# Version Tracking (Version.md)

This file is the permanent, immutable ledger of the `Alpha-Insta` project evolution.

---

## [2026-10-09 16:23:00 IST] - Repository Genesis & Autonomous Pipeline Architecture
- **Action**: Initialized the `Alpha-Insta` project as a dedicated autonomous upstream ingestion engine for Instagram Alpha `arm64-v8a` releases.
- **Components Added**:
  - `scripts/download-instagram-alpha.mjs`: Native Node.js crawler utilizing APKUpdater API authentication headers (`APKUpdater-v0`) to bypass Cloudflare bot challenge, discover latest alpha builds, resolve high-density `arm64-v8a` variants, and stream bundles directly to disk.
  - `.github/workflows/fetch-and-release-alpha.yml`:
    - Daily scheduled cron trigger at 03:00 UTC (`0 3 * * *`).
    - Smart release gate checking `gh release view` prior to download to avoid redundant bandwidth consumption when no new Alpha was published.
    - Automated split bundle decomposition with 7z/unzip and APKEditor merging.
    - SHA-256 cryptographic hashing and `metadata.json` generation.
    - Official GitHub Release publication tagged `v<VERSION>` with downloadable standalone APKs.
  - `README.md`: Architecture overview, asset specifications, and downstream integration guidelines for `junksidetm/instafel`.
- **Status**: 100% (Completed)
## [2026-10-09 16:26:00 IST] - Release Creation & Asset Upload Resilience
- **Action**: Corrected GitHub CLI release command syntax to conditionally execute `gh release create` for new tags or `gh release upload --clobber` for existing releases, eliminating invalid `--clobber` flag invocation on create.
- **Components Modified**:
  - `.github/workflows/fetch-and-release-alpha.yml`: Added branch logic checking if tag exists via `gh release view` before deciding between `create` and `upload`.
- **Status**: 100% (Completed)

## [2026-10-09 19:28:00 IST] - Multi-Platform Mirror CI/CD Integration
- **Action**: Added GitLab CI pipeline and Forgejo Actions workflow for autonomous crawler execution and syntax verification on mirror platforms.
- **Components Added**:
  - `.gitlab-ci.yml`: Node 22 crawler script syntax validation.
  - `.forgejo/workflows/fetch-and-release-alpha.yml`: Codeberg Actions pipeline.
  - `Version.md`: Appended tracking entry.
- **Status**: 100% (Completed & Synced)

# Alpha-Insta 🚀

Autonomous, headless ingestion pipeline that monitors, downloads, merges, and releases clean **Instagram Alpha** APK packages (`arm64-v8a`) on a daily schedule.

---

## 🎯 Architecture & Purpose

1. **Autonomous Upstream Monitor**:
   - Executes daily scheduled crawls across APKMirror to discover newly posted Instagram Alpha builds (e.g. `451.0.0.0.70`).
   - Authenticated with official APKUpdater headers to cleanly navigate Cloudflare and anti-bot challenges without credentials or manual web visits.
2. **Bundle Unpacking & Split Merging**:
   - Resolves the high-dpi `arm64-v8a` variant bundle.
   - Decompresses APKM split packages and merges architecture and density splits into a unified, standalone `instagram-alpha-v<VERSION>-arm64-v8a.apk` using `APKEditor`.
3. **Decoupled Downstream Consumption**:
   - Publishes verified GitHub Releases tagged `v<VERSION>` with complete SHA-256 checksums and `metadata.json`.
   - Modding engines like **[Instafel](https://github.com/junksidetm/instafel)** query this repository's releases, downloading clean pre-bundled APKs to inject custom typography (SF Pro, Google Sans Flex) and custom emojis (iOS 26.4, Google 3D).

---

## 📦 Release Assets Specification

Every GitHub Release in this repository provides:
| Asset | Description |
|---|---|
| `instagram-alpha-v<VERSION>-arm64-v8a.apk` | Clean, standalone merged APK ready for installation or patching |
| `instagram-alpha-v<VERSION>-arm64-v8a.apk.sha256` | SHA-256 cryptographic checksum |
| `metadata.json` | Machine-readable release metadata (version, architecture, timestamp, file size) |

---

## ⚡ GitHub Actions Automation

- **Schedule**: Runs automatically every day at `03:00 UTC` (`cron: '0 3 * * *'`).
- **Release Gate**: Queries GitHub Releases before downloading; if the latest version is already released, the workflow terminates within 10 seconds to conserve CI bandwidth and resources.
- **Manual Trigger**: Supports `workflow_dispatch` with optional `force_release` and `target_version` inputs.

---

<div align="center">
<a href="https://github.com/junksidetm/junksidetm.github.io">
  <img src="https://raw.githubusercontent.com/junksidetm/assests/981a029b9f59b8ed581bbee9be318c86da52dcca/Images/Codium/Codium%20Banner/SVG/Codium%20-%20Banner%20Black.svg" width="360"></a>
<br><br>
<sub>
<p>This repository is a part of `"Codeium"`. A part of Darkside Studio.
</p>
</sub>
<p><b><sub>© 2026 Abhijeet Yadav.  All rights reserved. All logos are Copyright Law </sub></b></p>

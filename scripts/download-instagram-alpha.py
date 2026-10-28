#!/usr/bin/env python3
"""
Alpha-Insta Autonomous Alpha Crawler & Downloader

Automatically discovers, resolves, and streams the latest Instagram Alpha
(arm64-v8a) package from APKMirror into the CI workspace with multi-strategy
Cloudflare bypass using curl_cffi and justapk fallback.
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_URL = "https://www.apkmirror.com"
ORG_SLUG = "instagram"
REPO_SLUG = "instagram-instagram"
FEED_URL = f"{BASE_URL}/apk/{ORG_SLUG}/{REPO_SLUG}/feed/"


def write_github_output(key: str, value: str):
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def parse_semver(version_str: str):
    return [int(x) for x in re.findall(r"\d+", version_str)]


def get_latest_alpha_release(target_version: str = ""):
    print(f"[Crawler] Fetching releases feed from {FEED_URL}...")
    import urllib.request

    req = urllib.request.Request(
        FEED_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        },
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_content = resp.read().decode("utf-8")

    root = ET.fromstring(xml_content)
    releases = []

    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is None or link_el is None:
            continue

        title = title_el.text or ""
        link = (link_el.text or "").strip()
        is_alpha = bool(re.search(r"alpha", title, re.IGNORECASE))
        match = re.search(r"Instagram\s+([0-9]+(?:\.[0-9]+)+)", title, re.IGNORECASE)

        if match:
            releases.append({
                "version": match.group(1),
                "is_alpha": is_alpha,
                "link": link,
            })

    if not releases:
        raise RuntimeError("No Instagram releases found in RSS feed.")

    print(f"[Crawler] Discovered {len(releases)} recent releases in feed:")
    for r in releases[:5]:
        print(f"  - v{r['version']} [Alpha: {r['is_alpha']}] ({r['link']})")

    if target_version:
        matched = next((r for r in releases if r["version"] == target_version), None)
        if matched:
            print(f"[Crawler] Matched requested target version: v{matched['version']}")
            return matched
        print(f"[Crawler] Target v{target_version} not in feed, constructing direct canonical link...")
        slug = target_version.replace(".", "-")
        return {
            "version": target_version,
            "is_alpha": True,
            "link": f"{BASE_URL}/apk/{ORG_SLUG}/{REPO_SLUG}/instagram-{slug}-release/",
        }

    alpha_releases = [r for r in releases if r["is_alpha"]]
    candidates = alpha_releases if alpha_releases else releases

    candidates.sort(key=lambda r: parse_semver(r["version"]), reverse=True)
    selected = candidates[0]
    print(f"[Crawler] Selected latest Alpha build: v{selected['version']}")
    return selected


def download_via_curl_cffi(release: dict, dest_path: Path) -> bool:
    print("\n[Strategy 1] Attempting TLS-impersonated download via curl_cffi...")
    try:
        from curl_cffi import requests
    except ImportError:
        print("[Strategy 1] curl_cffi not installed, skipping...")
        return False

    session = requests.Session(impersonate="chrome131")
    session.headers.update({
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
    })

    # Step 1: Variants Page
    print(f"[Strategy 1] Fetching variant table from {release['link']}...")
    res = session.get(release["link"], timeout=30)
    if res.status_code != 200:
        print(f"[Strategy 1] Failed variant page: HTTP {res.status_code}")
        return False

    html = res.text
    # Find variant download links
    variant_matches = re.findall(
        r'href="(/apk/instagram/instagram-instagram/[^"]+android-apk-download/)"',
        html,
    )
    if not variant_matches:
        print("[Strategy 1] No variant download links found in release HTML.")
        return False

    unique_variants = [f"{BASE_URL}{v}" for v in set(variant_matches)]
    print(f"[Strategy 1] Found {len(unique_variants)} variants.")

    # Prioritize variant 2 (arm64-v8a standard) or first variant
    target_variant = next(
        (v for v in unique_variants if "-2-android-apk-download" in v),
        unique_variants[0],
    )
    print(f"[Strategy 1] Selected target variant: {target_variant}")

    # Step 2: Intermediate download button page
    session.headers["Referer"] = release["link"]
    res_var = session.get(target_variant, timeout=30)
    if res_var.status_code != 200:
        print(f"[Strategy 1] Failed on variant detail page: HTTP {res_var.status_code}")
        return False

    dl_page_match = re.search(
        r'href="(/apk/[^"]+android-apk-download/download/[^"]*)"',
        res_var.text,
    )
    if not dl_page_match:
        print("[Strategy 1] Intermediate download button not found.")
        return False

    staging_url = f"{BASE_URL}{dl_page_match.group(1)}"
    print(f"[Strategy 1] Navigating to staging page: {staging_url}...")

    # Step 3: Staging download page
    session.headers["Referer"] = target_variant
    res_stage = session.get(staging_url, timeout=30)
    if res_stage.status_code != 200:
        print(f"[Strategy 1] Failed on staging page: HTTP {res_stage.status_code}")
        return False

    final_match = re.search(
        r'href="([^"]*wp-content/themes/APKMirror/download\.php[^"]*)"',
        res_stage.text,
    )
    if not final_match:
        print("[Strategy 1] Final download.php link not found on staging page.")
        return False

    final_url = f"{BASE_URL}{final_match.group(1)}"
    print(f"[Strategy 1] Resolved final direct download URL: {final_url}")

    # Step 4: Stream download
    session.headers["Referer"] = staging_url
    print(f"[Strategy 1] Streaming payload to {dest_path}...")
    res_dl = session.get(final_url, stream=True, timeout=120)
    if res_dl.status_code != 200:
        print(f"[Strategy 1] Stream request failed: HTTP {res_dl.status_code}")
        return False

    total_bytes = 0
    with open(dest_path, "wb") as f:
        for chunk in res_dl.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total_bytes += len(chunk)
                mb = total_bytes / (1024 * 1024)
                if int(mb) % 10 == 0:
                    print(f"  - Downloaded {mb:.1f} MB...", flush=True)

    file_size_mb = total_bytes / (1024 * 1024)
    print(f"[Strategy 1] Download completed successfully: {file_size_mb:.2f} MB saved.")

    # Guard: APKM / APK bundle for Instagram must be at least 30 MB
    if file_size_mb < 30.0:
        print(f"[Strategy 1] Warning: Downloaded file size too small ({file_size_mb:.2f} MB). Likely challenge response.")
        dest_path.unlink(missing_ok=True)
        return False

    return True


def download_via_justapk(version: str, dest_dir: Path) -> Path | None:
    print("\n[Strategy 2] Attempting download via justapk fallback engine...")
    import shutil
    import subprocess

    justapk_bin = shutil.which("justapk")
    if not justapk_bin:
        print("[Strategy 2] justapk binary not in PATH, trying python module invocation...")
        cmd = [sys.executable, "-m", "justapk", "download", "com.instagram.android", "-v", version, "-s", "apkmirror", "-o", str(dest_dir)]
    else:
        cmd = [justapk_bin, "download", "com.instagram.android", "-v", version, "-s", "apkmirror", "-o", str(dest_dir)]

    print(f"[Strategy 2] Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"[Strategy 2] Output:\n{result.stdout}")
    if result.stderr:
        print(f"[Strategy 2] Stderr:\n{result.stderr}")

    # Check for downloaded files in dest_dir
    downloaded = list(dest_dir.glob("*.apk*")) + list(dest_dir.glob("*.xapk"))
    if downloaded:
        target = downloaded[0]
        print(f"[Strategy 2] Success! Downloaded: {target} ({target.stat().st_size / (1024*1024):.2f} MB)")
        return target

    return None


def main():
    target_dir = Path(os.environ.get("DOWNLOAD_DIR", "downloads"))
    target_version = os.environ.get("TARGET_VERSION", "").strip()
    check_only = os.environ.get("CHECK_ONLY", "false").lower() == "true"

    target_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Discover latest Alpha
    release = get_latest_alpha_release(target_version)
    version = release["version"]
    write_github_output("version", version)

    if check_only:
        print(f"[Crawler] CHECK_ONLY enabled. Discovered v{version}. Exiting.")
        sys.exit(0)

    dest_file = target_dir / f"instagram-v{version}-bundle.apkm"

    # Step 2: Try Strategy 1 (curl_cffi)
    success = download_via_curl_cffi(release, dest_file)

    # Step 3: Try Strategy 2 (justapk fallback) if Strategy 1 fails
    if not success:
        print("[Crawler] Strategy 1 failed, executing Strategy 2 (justapk)...")
        fallback_file = download_via_justapk(version, target_dir)
        if fallback_file and fallback_file.exists():
            dest_file = fallback_file
            success = True

    if not success or not dest_file.exists() or dest_file.stat().st_size < (30 * 1024 * 1024):
        print("\n::error::[Fatal] All download strategies failed to retrieve the Instagram Alpha bundle.")
        sys.exit(1)

    print(f"\n[Success] Verified bundle ready at: {dest_file} ({dest_file.stat().st_size / (1024*1024):.2f} MB)")
    write_github_output("file_path", str(dest_file))


if __name__ == "__main__":
    main()

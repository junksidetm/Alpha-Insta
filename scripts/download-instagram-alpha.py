#!/usr/bin/env python3
"""
Alpha-Insta Autonomous Alpha Crawler & Downloader

Discovers, resolves, and streams the latest Instagram Alpha (arm64-v8a)
package from APKMirror into the CI workspace with multi-layer Cloudflare
bypass (TLS impersonation + SeleniumBase UC Mode fallback).
"""

import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_URL = "https://www.apkmirror.com"
ORG_SLUG = "instagram"
REPO_SLUG = "instagram-instagram"
FEED_URL = f"{BASE_URL}/apk/{ORG_SLUG}/{REPO_SLUG}/feed/"

AUTH_HEADERS = {
    "User-Agent": "APKUpdater-v0",
    "Authorization": "Basic YXBpLWFwa3VwZGF0ZXI6cm01cmNmcnVVakt5MDRzTXB5TVBKWFc4",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def write_github_output(key: str, value: str):
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def parse_semver(version_str: str):
    return [int(x) for x in re.findall(r"\d+", version_str)]


def get_latest_alpha_release(target_version: str = ""):
    print(f"[Crawler] Fetching releases feed from {FEED_URL}...")
    xml_content = ""

    try:
        from curl_cffi import requests

        session = requests.Session(impersonate="chrome131")
        resp = session.get(FEED_URL, headers=AUTH_HEADERS, timeout=30)
        if resp.status_code == 200:
            xml_content = resp.text
        else:
            print(f"[Crawler] Feed fetch returned HTTP {resp.status_code}")
    except Exception as e:
        print(f"[Crawler] curl_cffi feed fetch failed ({e}), falling back to urllib...")

    if not xml_content:
        import urllib.request

        req = urllib.request.Request(FEED_URL, headers=AUTH_HEADERS)
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
        print(f"[Crawler] Target v{target_version} not in feed, constructing canonical link...")
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

    # Step 1: Variants Page
    print(f"[Strategy 1] Fetching variant table from {release['link']}...")
    res = session.get(release["link"], headers=AUTH_HEADERS, timeout=30)
    if res.status_code != 200:
        print(f"[Strategy 1] Variant page returned HTTP {res.status_code}")
        return False

    html = res.text
    variant_matches = re.findall(
        r'href="(/apk/instagram/instagram-instagram/[^"]+android-apk-download/)"',
        html,
    )
    if not variant_matches:
        print("[Strategy 1] No variant download links found in HTML.")
        return False

    unique_variants = [f"{BASE_URL}{v}" for v in set(variant_matches)]
    print(f"[Strategy 1] Found {len(unique_variants)} variants.")

    target_variant = next(
        (v for v in unique_variants if "-2-android-apk-download" in v),
        unique_variants[0],
    )
    print(f"[Strategy 1] Selected target variant: {target_variant}")

    # Step 2: Intermediate download button page
    headers_var = dict(AUTH_HEADERS)
    headers_var["Referer"] = release["link"]
    res_var = session.get(target_variant, headers=headers_var, timeout=30)
    if res_var.status_code != 200:
        print(f"[Strategy 1] Variant detail page returned HTTP {res_var.status_code}")
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
    headers_stage = dict(AUTH_HEADERS)
    headers_stage["Referer"] = target_variant
    res_stage = session.get(staging_url, headers=headers_stage, timeout=30)
    if res_stage.status_code != 200:
        print(f"[Strategy 1] Staging page returned HTTP {res_stage.status_code}")
        return False

    final_match = re.search(
        r'href="([^"]*wp-content/themes/APKMirror/download\.php[^"]*)"',
        res_stage.text,
    )
    if not final_match:
        print("[Strategy 1] download.php link not found on staging page.")
        return False

    final_url = f"{BASE_URL}{final_match.group(1)}"
    print(f"[Strategy 1] Resolved final direct download URL: {final_url}")

    # Step 4: Stream download
    headers_dl = dict(AUTH_HEADERS)
    headers_dl["Referer"] = staging_url
    print(f"[Strategy 1] Streaming payload to {dest_path}...")
    res_dl = session.get(final_url, headers=headers_dl, stream=True, timeout=120)
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
    print(f"[Strategy 1] Download finished: {file_size_mb:.2f} MB saved.")

    if file_size_mb < 30.0:
        print(f"[Strategy 1] File size too small ({file_size_mb:.2f} MB), likely challenge response.")
        dest_path.unlink(missing_ok=True)
        return False

    return True


def download_via_seleniumbase(release_url: str, dest_dir: Path) -> Path | None:
    print("\n[Strategy 2] Attempting download via SeleniumBase UC Mode (Virtual Framebuffer)...")
    try:
        from seleniumbase import SB
    except ImportError:
        print("[Strategy 2] seleniumbase not installed, skipping...")
        return None

    dest_dir_abs = dest_dir.resolve()
    print(f"[Strategy 2] Target download directory: {dest_dir_abs}")

    with SB(uc=True, test=True, xvfb=True, locale="en") as sb:
        # Step 1: Release page
        print(f"[Strategy 2] Navigating to {release_url} in CDP mode...")
        sb.activate_cdp_mode(release_url)
        sb.sleep(2)

        title = sb.get_title()
        print(f"[Strategy 2] Page title after CDP load: '{title}'")

        if "Just a moment" in title or sb.is_element_visible('iframe[src*="challenges.cloudflare.com"]'):
            print("[Strategy 2] Cloudflare Turnstile detected, solving via CDP solve_captcha()...")
            try:
                sb.solve_captcha()
            except Exception as e:
                print(f"[Strategy 2] solve_captcha exception: {e}")
            sb.sleep(5)
            title = sb.get_title()
            print(f"[Strategy 2] Page title after solve_captcha: '{title}'")

        html = sb.get_page_source()
        print(f"[Strategy 2] HTML length: {len(html)}")

        # Search for all links with apk-download
        all_apk_links = re.findall(r'href="([^"]*apk-download[^"]*)"', html, re.IGNORECASE)
        print(f"[Strategy 2] Discovered {len(all_apk_links)} raw apk-download links in page.")
        if all_apk_links:
            for l in all_apk_links[:5]:
                print(f"  - candidate: {l}")

        variant_matches = [
            l for l in all_apk_links
            if "android-apk-download" in l and "instagram" in l.lower()
        ]
        if not variant_matches:
            print("[Strategy 2] No variant links found in HTML.")
            return None

        target_variant = next(
            (v for v in set(variant_matches) if "-2-android-apk-download" in v),
            variant_matches[0],
        )
        variant_url = target_variant if target_variant.startswith("http") else f"{BASE_URL}{target_variant}"
        print(f"[Strategy 2] Opening variant page: {variant_url}...")
        sb.activate_cdp_mode(variant_url)
        sb.sleep(2)
        if "Just a moment" in sb.get_title():
            sb.solve_captcha()
            sb.sleep(4)

        html_var = sb.get_page_source()
        dl_match = re.search(
            r'href="([^"]*apk/[^"]*android-apk-download/download/[^"]*)"',
            html_var,
        )
        if not dl_match:
            print("[Strategy 2] Intermediate download link not found.")
            return None

        staging_href = dl_match.group(1)
        staging_url = staging_href if staging_href.startswith("http") else f"{BASE_URL}{staging_href}"
        print(f"[Strategy 2] Opening staging page: {staging_url}...")
        sb.activate_cdp_mode(staging_url)
        sb.sleep(2)
        if "Just a moment" in sb.get_title():
            sb.solve_captcha()
            sb.sleep(4)

        html_stage = sb.get_page_source()
        final_match = re.search(
            r'href="([^"]*wp-content/themes/APKMirror/download\.php[^"]*)"',
            html_stage,
        )
        if not final_match:
            print("[Strategy 2] download.php link not found on staging page.")
            return None

        final_href = final_match.group(1)
        final_url = final_href if final_href.startswith("http") else f"{BASE_URL}{final_href}"
        print(f"[Strategy 2] Resolved final download URL: {final_url}")

        # Extract cleared session cookies and user-agent from Chrome
        cookies = {c["name"]: c["value"] for c in sb.get_cookies()}
        ua = sb.get_user_agent()
        print(f"[Strategy 2] Extracted {len(cookies)} browser cookies (including cf_clearance: {'cf_clearance' in cookies}).")

        # Stream download using curl_cffi with authenticated browser session
        from curl_cffi import requests
        dl_session = requests.Session(impersonate="chrome131")
        dest_file = dest_dir / "instagram_bundle.apkm"
        print(f"[Strategy 2] Streaming payload to {dest_file} with browser clearance session...")

        res_dl = dl_session.get(
            final_url,
            cookies=cookies,
            headers={
                "User-Agent": ua,
                "Referer": staging_url,
                "Accept": "*/*",
            },
            stream=True,
            timeout=120,
        )

        if res_dl.status_code == 200:
            total = 0
            with open(dest_file, "wb") as f:
                for chunk in res_dl.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
                        mb = total / (1024 * 1024)
                        if int(mb) % 10 == 0:
                            print(f"  - Downloaded {mb:.1f} MB...", flush=True)

            size_mb = total / (1024 * 1024)
            print(f"[Strategy 2] Streamed {size_mb:.2f} MB to {dest_file}")
            if size_mb >= 30.0:
                return dest_file

        # Fallback to in-browser download
        print("[Strategy 2] Direct stream returned non-200, navigating browser to trigger file download...")
        sb.activate_cdp_mode(final_url)
        for _ in range(30):
            time.sleep(2)
            candidates = list(Path.home().glob("Downloads/*.apk*")) + list(dest_dir.glob("*.apk*"))
            completed = [f for f in candidates if not f.name.endswith(".crdownload") and f.stat().st_size > (30 * 1024 * 1024)]
            if completed:
                target_file = completed[0]
                dest_file = dest_dir / target_file.name
                if target_file != dest_file:
                    import shutil
                    shutil.move(str(target_file), str(dest_file))
                print(f"[Strategy 2] In-browser download confirmed: {dest_file} ({dest_file.stat().st_size / (1024*1024):.2f} MB)")
                return dest_file

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

    # Step 2: Try Strategy 1 (curl_cffi with APKUpdater Auth)
    success = download_via_curl_cffi(release, dest_file)

    # Step 3: Try Strategy 2 (SeleniumBase UC Mode) if Strategy 1 fails
    if not success:
        print("[Crawler] Strategy 1 failed, engaging Strategy 2 (SeleniumBase UC Mode)...")
        sb_file = download_via_seleniumbase(release["link"], target_dir)
        if sb_file and sb_file.exists() and sb_file.stat().st_size >= (30 * 1024 * 1024):
            dest_file = sb_file
            success = True

    if not success or not dest_file.exists() or dest_file.stat().st_size < (30 * 1024 * 1024):
        print("\n::error::[Fatal] All download strategies failed to retrieve the Instagram Alpha bundle.")
        sys.exit(1)

    print(f"\n[Success] Verified bundle ready at: {dest_file} ({dest_file.stat().st_size / (1024*1024):.2f} MB)")
    write_github_output("file_path", str(dest_file))


if __name__ == "__main__":
    main()

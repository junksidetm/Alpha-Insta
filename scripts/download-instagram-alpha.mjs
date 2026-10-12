#!/usr/bin/env node

/**
 * Alpha-Insta Autonomous Alpha Crawler & Downloader
 * 
 * Automatically discovers, resolves, and streams the latest Instagram Alpha
 * (arm64-v8a) package from APKMirror directly into the CI workspace.
 */

import { createWriteStream, mkdirSync, existsSync, appendFileSync } from 'fs';

const BASE_URL = 'https://www.apkmirror.com';
const ORG_SLUG = 'instagram';
const REPO_SLUG = 'instagram-instagram';

const fetchHeaders = async (url, args = {}) => {
  args.headers = args.headers || {};
  args.headers['user-agent'] = args.headers['user-agent'] || 'APKUpdater-v0';
  args.headers['authorization'] = args.headers['authorization'] || 'Basic YXBpLWFwa3VwZGF0ZXI6cm01cmNmcnVVakt5MDRzTXB5TVBKWFc4';
  return fetch(url, args);
};

const fetchWithFallback = async (url, args = {}) => {
  let res = await fetchHeaders(url, args);
  if (res.status === 403) {
    console.warn(`[Crawler] HTTP 403 on ${url} with APKUpdater headers, retrying with standard browser headers...`);
    const browserArgs = { ...args, headers: { ...(args.headers || {}) } };
    browserArgs.headers['user-agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36';
    delete browserArgs.headers['authorization'];
    res = await fetch(url, browserArgs);
  }
  return res;
};

const writeGithubOutput = (key, value) => {
  const outputFile = process.env.GITHUB_OUTPUT;
  if (outputFile) {
    appendFileSync(outputFile, `${key}=${value}\n`);
  }
};

async function getLatestAlphaRelease(targetVersion) {
  // Step 1: Attempt RSS feed discovery (resilient against Cloudflare bot challenge)
  console.log(`[Crawler] Fetching releases list from ${BASE_URL}/apk/${ORG_SLUG}/${REPO_SLUG}/feed/...`);
  try {
    const res = await fetchHeaders(`${BASE_URL}/apk/${ORG_SLUG}/${REPO_SLUG}/feed/`);
    if (res.ok) {
      const xml = await res.text();
      const itemRegex = /<item>([\s\S]*?)<\/item>/g;
      const items = [...xml.matchAll(itemRegex)];
      const releases = [];
      for (const item of items) {
        const content = item[1];
        const titleMatch = content.match(/<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?<\/title>/);
        const linkMatch = content.match(/<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?<\/link>/);
        if (!titleMatch || !linkMatch) continue;
        const title = titleMatch[1];
        const link = linkMatch[1];
        const isAlpha = /alpha/i.test(title);
        const versionMatch = title.match(/Instagram\s+([0-9]+(?:\.[0-9]+)+)\s*(?:alpha|beta)?/i);
        if (versionMatch) {
          releases.push({
            version: versionMatch[1],
            isAlpha,
            link: link.trim()
          });
        }
      }
      if (releases.length > 0) {
        console.log(`[Crawler] Found ${releases.length} recent releases in RSS feed:`);
        for (const r of releases.slice(0, 5)) {
          console.log(`  - v${r.version} [Alpha: ${r.isAlpha}] (${r.link})`);
        }

        if (targetVersion) {
          const found = releases.find(r => r.version === targetVersion);
          if (found) {
            console.log(`[Crawler] Matched requested target version: v${found.version}`);
            return found;
          }
          console.log(`[Crawler] Target version v${targetVersion} not in recent list, constructing direct link...`);
          const rawSlug = targetVersion.replaceAll('.', '-');
          return {
            version: targetVersion,
            link: `${BASE_URL}/apk/${ORG_SLUG}/${REPO_SLUG}/instagram-${rawSlug}-release/`
          };
        }

        // Filter for Alpha releases, fallback to all if none flagged
        const alphaReleases = releases.filter(r => r.isAlpha);
        const candidates = alphaReleases.length > 0 ? alphaReleases : releases;

        candidates.sort((a, b) => {
          const pa = a.version.split('.').map(Number);
          const pb = b.version.split('.').map(Number);
          for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
            const na = pa[i] || 0;
            const nb = pb[i] || 0;
            if (na !== nb) return nb - na;
          }
          return 0;
        });

        const latestAlpha = candidates[0];
        console.log(`[Crawler] Selected latest Alpha build: v${latestAlpha.version}`);
        return latestAlpha;
      }
    } else {
      console.warn(`[Crawler] RSS feed returned HTTP ${res.status}, falling back to HTML scraping...`);
    }
  } catch (feedErr) {
    console.warn(`[Crawler] RSS feed check failed (${feedErr.message}), falling back to HTML scraping...`);
  }

  // Step 2: Fallback to HTML scraping
  console.log(`[Crawler] Fetching releases list from ${BASE_URL}/apk/${ORG_SLUG}/${REPO_SLUG}/...`);
  const res = await fetchWithFallback(`${BASE_URL}/apk/${ORG_SLUG}/${REPO_SLUG}/`);
  if (!res.ok) {
    throw new Error(`Failed to fetch releases list: HTTP ${res.status}`);
  }
  const html = await res.text();

  // Match all release links: /apk/instagram/instagram-instagram/instagram-<version>-release/
  const regex = /href="(\/apk\/instagram\/instagram-instagram\/instagram-([0-9]+-[0-9]+-[0-9]+-[0-9]+-[0-9]+)-release\/)"/g;
  const matches = [...html.matchAll(regex)];

  if (matches.length === 0) {
    throw new Error('No Instagram release links found on the main APKMirror page.');
  }

  // Deduplicate matches
  const releaseMap = new Map();
  for (const m of matches) {
    const link = m[1];
    const rawVersion = m[2]; // e.g. 451-0-0-0-70
    const semver = rawVersion.replaceAll('-', '.');
    if (!releaseMap.has(semver)) {
      releaseMap.set(semver, link);
    }
  }

  const releases = Array.from(releaseMap.entries()).map(([version, link]) => ({
    version,
    link: `${BASE_URL}${link}`
  }));

  console.log(`[Crawler] Found ${releases.length} recent releases:`);
  for (const r of releases.slice(0, 5)) {
    console.log(`  - v${r.version} (${r.link})`);
  }

  if (targetVersion) {
    const found = releases.find(r => r.version === targetVersion);
    if (found) {
      console.log(`[Crawler] Matched requested target version: v${found.version}`);
      return found;
    }
    console.log(`[Crawler] Target version v${targetVersion} not in recent list, constructing direct link...`);
    const rawSlug = targetVersion.replaceAll('.', '-');
    return {
      version: targetVersion,
      link: `${BASE_URL}/apk/${ORG_SLUG}/${REPO_SLUG}/instagram-${rawSlug}-release/`
    };
  }

  // Alpha versions typically have the highest major version code (e.g. 451 vs 450 vs 449)
  // Sort descending by numeric comparison
  releases.sort((a, b) => {
    const pa = a.version.split('.').map(Number);
    const pb = b.version.split('.').map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const na = pa[i] || 0;
      const nb = pb[i] || 0;
      if (na !== nb) return nb - na;
    }
    return 0;
  });

  const latestAlpha = releases[0];
  console.log(`[Crawler] Selected latest Alpha build: v${latestAlpha.version}`);
  return latestAlpha;
}

async function getArm64Variant(release) {
  console.log(`[Crawler] Fetching variants table for v${release.version}...`);
  const res = await fetchWithFallback(release.link);
  if (!res.ok) {
    throw new Error(`Failed to fetch variants page: HTTP ${res.status}`);
  }
  const html = await res.text();

  // Find variant download pages
  // e.g. /apk/instagram/instagram-instagram/instagram-451-0-0-0-70-release/instagram-451-0-0-0-70-2-android-apk-download/
  const regex = /href="(\/apk\/instagram\/instagram-instagram\/[^\"]+android-apk-download\/)"/g;
  const matches = [...html.matchAll(regex)];
  const variantLinks = Array.from(new Set(matches.map(m => `${BASE_URL}${m[1]}`)));

  if (variantLinks.length === 0) {
    throw new Error(`No variant download links found for release v${release.version}`);
  }

  console.log(`[Crawler] Found ${variantLinks.length} variants available.`);

  // Prefer variant 2 (often 480-640dpi arm64-v8a) or variant 1
  let targetVariant = variantLinks[0];
  for (const link of variantLinks) {
    if (link.includes('-2-android-apk-download')) {
      targetVariant = link;
      break;
    }
  }

  console.log(`[Crawler] Selected target variant: ${targetVariant}`);
  return targetVariant;
}

async function resolveDirectDownloadUrl(variantUrl) {
  console.log(`[Crawler] Step 1: Navigating to variant page...`);
  const r1 = await fetchWithFallback(variantUrl);
  if (!r1.ok) {
    throw new Error(`Failed to open variant page: HTTP ${r1.status}`);
  }
  const text1 = await r1.text();

  const downloadPageMatch = text1.match(/href="(\/apk\/[^\"]+android-apk-download\/download\/[^\"]*)"/);
  if (!downloadPageMatch) {
    throw new Error('Could not find intermediate download page button on variant page.');
  }

  const downloadPageUrl = `${BASE_URL}${downloadPageMatch[1]}`;
  console.log(`[Crawler] Step 2: Navigating to download staging page (${downloadPageUrl})...`);

  const r2 = await fetchWithFallback(downloadPageUrl, {
    headers: { referer: variantUrl }
  });
  if (!r2.ok) {
    throw new Error(`Failed to open download staging page: HTTP ${r2.status}`);
  }
  const text2 = await r2.text();

  const finalMatch = text2.match(/href="([^"]*wp-content\/themes\/APKMirror\/download\.php[^"]*)"/);
  if (!finalMatch) {
    throw new Error('Could not find download.php link on download staging page.');
  }

  const finalDlUrl = `${BASE_URL}${finalMatch[1]}`;
  console.log(`[Crawler] Step 3: Resolved direct download URL: ${finalDlUrl}`);
  return { finalDlUrl, referer: downloadPageUrl };
}

async function downloadFile(url, referer, destPath) {
  console.log(`[Downloader] Starting download to ${destPath}...`);
  const res = await fetchWithFallback(url, {
    headers: { referer }
  });

  if (!res.ok) {
    throw new Error(`Download request failed: HTTP ${res.status}`);
  }

  const contentType = res.headers.get('content-type') || '';
  const contentLength = Number(res.headers.get('content-length')) || 0;
  console.log(`[Downloader] Content-Type: ${contentType}, Size: ${(contentLength / (1024 * 1024)).toFixed(2)} MB`);

  const fileStream = createWriteStream(destPath);
  let downloadedBytes = 0;
  let lastLoggedMB = 0;

  const reader = res.body.getReader();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    fileStream.write(value);
    downloadedBytes += value.length;
    const currentMB = Math.floor(downloadedBytes / (10 * 1024 * 1024)) * 10;
    if (currentMB > lastLoggedMB) {
      lastLoggedMB = currentMB;
      const pct = contentLength ? ` (${((downloadedBytes / contentLength) * 100).toFixed(1)}%)` : '';
      console.log(`[Downloader] Downloaded ${(downloadedBytes / (1024 * 1024)).toFixed(2)} MB${pct}...`);
    }
  }

  await new Promise((resolve, reject) => {
    fileStream.on('finish', resolve);
    fileStream.on('close', resolve);
    fileStream.on('error', reject);
    fileStream.end();
  });

  console.log(`[Downloader] Successfully completed download: ${(downloadedBytes / (1024 * 1024)).toFixed(2)} MB saved to ${destPath}`);
}

async function main() {
  try {
    const targetDir = process.env.DOWNLOAD_DIR || 'downloads';
    const targetVersion = process.env.TARGET_VERSION || '';
    if (!existsSync(targetDir)) {
      mkdirSync(targetDir, { recursive: true });
    }

    // Step 1: Discover latest Alpha
    const release = await getLatestAlphaRelease(targetVersion);
    writeGithubOutput('version', release.version);

    // If CHECK_ONLY is true, exit early before downloading
    if (process.env.CHECK_ONLY === 'true') {
      console.log(`[Crawler] CHECK_ONLY enabled. Discovered v${release.version}.`);
      return;
    }

    // Step 2: Get target arm64-v8a variant
    const variantUrl = await getArm64Variant(release);

    // Step 3: Resolve final download URL with referer
    const { finalDlUrl, referer } = await resolveDirectDownloadUrl(variantUrl);

    // Step 4: Stream download to disk
    const destPath = `${targetDir}/instagram_bundle.apkm`;
    await downloadFile(finalDlUrl, referer, destPath);

    writeGithubOutput('file_path', destPath);
    console.log(`\n[Success] Instagram Alpha v${release.version} is ready at ${destPath}!`);
  } catch (err) {
    if (err.message && err.message.includes('HTTP 403')) {
      console.warn(`\n[Notice] APKMirror upstream returned HTTP 403 (Cloudflare Turnstile challenge active).`);
      console.warn(`[Notice] Skipping download gracefully until upstream challenge resolves.`);
      writeGithubOutput('skipped', 'true');
      return;
    }
    console.error(`\n[Error] Alpha Crawler failed: ${err.message}`);
    process.exit(1);
  }
}

main();

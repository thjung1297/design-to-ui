/*
 * Design-To-UI
 * Copyright (c) 2026-present NAVER Corp.
 * Apache-2.0
 */
/*
 * design-qa web 공용 캡처 유틸 — capture_story.mjs / run.mjs 공유.
 * storybook-static 정적 서빙 + 스토리 요소 스크린샷(fonts.ready 대기).
 */
import http from 'http';
import { createReadStream, existsSync, statSync } from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

// 대상 프로젝트의 playwright를 동적 import로 해소한다(ESM은 NODE_PATH를 bare import에 안 씀).
// 우선순위: env FIGMA_OVERLAY_PLAYWRIGHT → <cwd>/node_modules/playwright.
export async function loadChromium() {
    const base = process.env.FIGMA_OVERLAY_PLAYWRIGHT
        ? path.resolve(process.env.FIGMA_OVERLAY_PLAYWRIGHT)
        : path.resolve(process.cwd(), 'node_modules/playwright');
    const entry = existsSync(path.join(base, 'index.js')) ? path.join(base, 'index.js') : base;
    const mod = await import(pathToFileURL(entry).href);
    return (mod.chromium || mod.default?.chromium);
}

// 대상 프로젝트에서 실행되는 스킬 — storybook-static 경로는 프로젝트 기준으로 해소한다.
// 우선순위: 환경변수 FIGMA_OVERLAY_STATIC → <cwd>/storybook-static.
export const STATIC_ROOT = process.env.FIGMA_OVERLAY_STATIC
    ? path.resolve(process.env.FIGMA_OVERLAY_STATIC)
    : path.resolve(process.cwd(), 'storybook-static');

const MIME = {
    '.html': 'text/html',
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.svg': 'image/svg+xml',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.map': 'application/json',
};

export function serveStatic(root = STATIC_ROOT) {
    const server = http.createServer((req, res) => {
        const urlPath = decodeURIComponent(req.url.split('?')[0]);
        const filePath = path.resolve(root, '.' + (urlPath === '/' ? '/index.html' : urlPath));
        // root 밖 escape 방지 — 문자열 prefix가 아니라 path.relative로 판정(형제 디렉터리 escape 차단).
        const rel = path.relative(root, filePath);
        const outside = rel.startsWith('..') || path.isAbsolute(rel);
        if (outside || !existsSync(filePath) || statSync(filePath).isDirectory()) {
            res.writeHead(404);
            res.end('not found');
            return;
        }
        res.writeHead(200, { 'Content-Type': MIME[path.extname(filePath)] || 'application/octet-stream' });
        createReadStream(filePath).pipe(res);
    });
    return new Promise((resolve) => server.listen(0, () => resolve(server)));
}

/**
 * 스토리 1건을 렌더해 대상 요소를 스크린샷으로 저장.
 * @returns {Promise<{box:object}>}
 */
export async function captureElement(page, { port, story, theme = 'light', selector, out, themeGlobalKey }) {
    // 다크/라이트 전환 Storybook global 키는 프로젝트마다 다를 수 있어 설정 가능하게 둔다
    // (기본 darkModeType, override: node-map $meta.themeGlobalKey 또는 env FIGMA_OVERLAY_THEME_GLOBAL).
    const globalKey = themeGlobalKey || process.env.FIGMA_OVERLAY_THEME_GLOBAL || 'darkModeType';
    const url =
        `http://127.0.0.1:${port}/iframe.html?viewMode=story&id=${encodeURIComponent(story)}` +
        `&globals=${globalKey}:${theme === 'dark' ? 'dark' : 'light'}`;
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.waitForSelector(selector, { state: 'visible', timeout: 15000 });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(200); // 트랜지션/레이아웃 안정화
    const el = await page.$(selector);
    if (!el) {
        throw new Error(`selector 매칭 없음: ${selector} (story=${story})`);
    }
    await el.screenshot({ path: out });
    return { box: await el.boundingBox() };
}

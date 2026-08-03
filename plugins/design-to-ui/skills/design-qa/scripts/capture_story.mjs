/*
 * Design-To-UI
 * Copyright (c) 2026-present NAVER Corp.
 * Apache-2.0
 */
/*
 * design-qa web 웹 캡처 어댑터(단건) — design-qa capture.py(adb)의 웹판.
 * 지정 스토리를 Playwright(Chromium)로 렌더해 대상 요소를 real.png 로 저장한다.
 * 요소 스크린샷이라 풀스크린 crop 이 불필요하다. 실폰트 정합 위해 document.fonts.ready 를 대기한다.
 * (다건 오케스트레이션은 run.mjs 참조.)
 *
 * usage:
 *   node capture_story.mjs --story <storyId> --out <real.png> [--theme light|dark] [--selector <css>] [--width <px>]
 */
import { existsSync } from 'fs';
import { STATIC_ROOT, serveStatic, captureElement, loadChromium } from './lib.mjs';

function parseArgs(argv) {
    const out = { theme: 'light', selector: 'body', width: 400 };
    for (let i = 2; i < argv.length; i += 2) {
        out[argv[i].replace(/^--/, '')] = argv[i + 1];
    }
    out.width = Number(out.width);
    return out;
}

async function main() {
    const args = parseArgs(process.argv);
    if (!args.story || !args.out) {
        console.error('usage: node capture_story.mjs --story <id> --out <real.png> [--theme] [--selector] [--width]');
        process.exit(2);
    }
    if (!existsSync(STATIC_ROOT)) {
        console.error(`storybook-static 없음: ${STATIC_ROOT} — 먼저 npm run build-storybook`);
        process.exit(2);
    }

    const chromium = await loadChromium();
    const server = await serveStatic();
    const port = server.address().port;
    const browser = await chromium.launch();
    const ctx = await browser.newContext({ viewport: { width: args.width, height: 900 }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();

    const { box } = await captureElement(page, { port, ...args });
    console.log(JSON.stringify({ out: args.out, story: args.story, theme: args.theme, box }));

    await browser.close();
    server.close();
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});

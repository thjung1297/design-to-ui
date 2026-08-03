/*
 * Design-To-UI
 * Copyright (c) 2026-present NAVER Corp.
 * Apache-2.0
 */
/*
 * design-qa web 오케스트레이션 러너 — node-map.json 기반 다건 렌더 대조.
 *
 * 각 entry에 대해: (1) 스토리 요소 캡처 → out/<id>_real.png(휘발),
 * (2) Figma 원본 캐시 figma/<id>.png 가 있으면 trim 후 overlay(rubric3) 실행·metrics 수집,
 * (3) 없으면 fetch 필요 목록에 기록, (4) out/OVERLAY-REPORT.md 생성.
 *
 * Figma get_screenshot 은 MCP라 스크립트에서 직접 못 부른다(design-qa와 동일 제약). 또 비싼 조회라
 * 원본은 figma/ 에 '캐시'해 보존·재사용한다 — 스킬(에이전트) 절차가 get_screenshot→curl로 figma/<id>.png 를
 * 한 번 받아두면 이후 실행은 재조회 없이 그 캐시를 쓴다. 미확보 entry만 fetch 매니페스트로 출력한다.
 * (real 캡처만 매 실행 재생성. Figma 시안이 바뀌었을 때만 figma/ 캐시를 갱신한다.)
 *
 * usage: node run.mjs [--map node-map.json] [--only <id,id>]
 */
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execFileSync } from 'child_process';
import { STATIC_ROOT, serveStatic, captureElement, loadChromium } from './lib.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// 산출물은 대상 프로젝트 기준(.design-qa web/out), probes는 스킬과 함께 배포된다.
// out/ = 휘발(real 캡처·trim·cmp·리포트, 매 실행 재생성). figma/ = 캐시(Figma 원본, 보존·재사용).
// Figma get_screenshot은 비싼 조회라 원본은 보존하고 없을 때만 fetch 매니페스트로 재수집한다.
const OUT = process.env.FIGMA_OVERLAY_OUT
    ? path.resolve(process.env.FIGMA_OVERLAY_OUT)
    : path.resolve(process.cwd(), '.design-qa web/out');
const FIGMA = process.env.FIGMA_OVERLAY_FIGMA
    ? path.resolve(process.env.FIGMA_OVERLAY_FIGMA)
    : path.resolve(process.cwd(), '.design-qa web/figma');
const PROBES = __dirname; // design-qa scripts는 평평 구조
const ID_RE = /^[A-Za-z0-9._-]+$/; // entry id는 파일명 안전문자만(/, \, .. 금지)
const rel = (p) => path.relative(process.cwd(), p); // 리포트 경로는 cwd 상대(env override에도 정확)

function parseArgs(argv) {
    const out = { map: path.resolve(process.cwd(), '.design-qa web/node-map.json') };
    for (let i = 2; i < argv.length; i += 2) {
        out[argv[i].replace(/^--/, '')] = argv[i + 1];
    }
    return out;
}

const py = (script, args) =>
    execFileSync('python3', [path.join(PROBES, script), ...args], { encoding: 'utf8' });

async function main() {
    const args = parseArgs(process.argv);
    if (!existsSync(STATIC_ROOT)) {
        console.error(`storybook-static 없음 — 먼저 npm run build-storybook`);
        process.exit(2);
    }
    mkdirSync(OUT, { recursive: true });
    mkdirSync(FIGMA, { recursive: true });
    const map = JSON.parse(readFileSync(args.map, 'utf8'));
    const only = args.only ? new Set(args.only.split(',')) : null;
    const entries = map.entries.filter((e) => !only || only.has(e.id));

    const chromium = await loadChromium();
    const server = await serveStatic();
    const port = server.address().port;
    const browser = await chromium.launch();

    const results = [];
    const fetchNeeded = [];
    for (const e of entries) {
        // id는 파일명/디렉터리명에 쓰이므로 basename-safe만 허용(경로 탈출 차단).
        if (!ID_RE.test(e.id)) {
            console.error(`entry id 부적합(영숫자·._- 만 허용): ${e.id} — 건너뜀`);
            results.push({ ...e, status: 'invalid-id' });
            continue;
        }
        // entry 단위 격리 — 한 항목 실패(selector miss·손상 PNG·probe 오류)가 배치 전체를 중단시키지 않게.
        try {
            const realPath = path.join(OUT, `${e.id}_real.png`);
            const figmaPath = path.join(FIGMA, `${e.id}.png`);
            const ctx = await browser.newContext({
                viewport: { width: e.width || 375, height: 900 },
                deviceScaleFactor: 2,
            });
            const page = await ctx.newPage();
            await captureElement(page, {
                port,
                story: e.story,
                theme: e.theme,
                selector: e.selector,
                out: realPath,
                themeGlobalKey: map.$meta && map.$meta.themeGlobalKey,
            });
            await ctx.close();

            if (!existsSync(figmaPath)) {
                fetchNeeded.push({ id: e.id, figmaNode: e.figmaNode });
                results.push({ ...e, status: 'figma-missing' });
                continue;
            }
            const rt = path.join(OUT, `${e.id}_real_t.png`);
            const ft = path.join(OUT, `${e.id}_figma_t.png`);
            py('trim.py', [realPath, rt]);
            py('trim.py', [figmaPath, ft]);
            const cmpDir = path.join(OUT, `${e.id}_cmp`);
            const metricsRaw = py('overlay.py', [ft, rt, cmpDir, '--rubric', '3', '--grid', '8,6', '--top', '4']);
            results.push({ ...e, status: 'compared', metrics: JSON.parse(metricsRaw) });
        } catch (err) {
            console.error(`entry ${e.id} 실패: ${err.message}`);
            results.push({ ...e, status: 'error', error: err.message });
        }
    }

    await browser.close();
    server.close();

    // 리포트 생성
    const lines = ['# design-qa web 렌더 대조 리포트', '', `- fileKey: \`${map.$meta.fileKey}\``, ''];
    for (const r of results) {
        lines.push(`## ${r.id}  (${r.story})`);
        lines.push(`- 노드 \`${r.figmaNode}\` · theme ${r.theme} · textParity ${r.textParity}`);
        if (r.status === 'invalid-id') {
            lines.push(`- ⚠️ id 부적합(영숫자·._- 만) → 건너뜀.`);
        } else if (r.status === 'error') {
            lines.push(`- ❌ 실패: ${r.error}`);
        } else if (r.status === 'figma-missing') {
            lines.push(`- ⚠️ Figma 원본 캐시 없음 → \`${rel(path.join(FIGMA, `${r.id}.png`))}\` 필요(아래 매니페스트).`);
        } else {
            const m = r.metrics;
            lines.push(`- resize_ratio \`${JSON.stringify(m.resize_ratio)}\` · mean_diff ${m.mean_diff} · pct_over_32 ${m.pct_over_32}`);
            lines.push(`- blend: \`${rel(path.join(OUT, `${r.id}_cmp/blend50.png`))}\` · 진단: \`${rel(path.join(OUT, `${r.id}_cmp`))}/cmp_*.png\``);
        }
        lines.push('');
    }
    if (fetchNeeded.length) {
        lines.push('## Figma fetch 매니페스트', '', '아래 노드를 get_screenshot(maxDimension≥real 긴변)으로 받아 캐시 경로에 curl 저장 후 재실행(원본은 보존·재사용):', '');
        for (const f of fetchNeeded) {
            lines.push(`- \`${f.figmaNode}\` → \`${rel(path.join(FIGMA, `${f.id}.png`))}\``);
        }
        lines.push('');
    }
    const report = path.join(OUT, 'OVERLAY-REPORT.md');
    writeFileSync(report, lines.join('\n'));
    console.log(`report → ${report}`);
    console.log(JSON.stringify({ compared: results.filter((r) => r.status === 'compared').length, fetchNeeded }, null, 2));
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});

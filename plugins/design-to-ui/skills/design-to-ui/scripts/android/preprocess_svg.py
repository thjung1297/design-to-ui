#!/usr/bin/env python3
# Design-To-UI
# Copyright (c) 2026-present NAVER Corp.
# Apache-2.0
"""
Figma SVG → vd-tool 호환 SVG 전처리기

핵심 변환:
1. CSS var() → 실제 색상값
2. named color (white, black 등) → hex
3. stop-opacity / stroke-opacity → 알파 채널 병합
4. <mask> → <clipPath> 변환 (★ 핵심)
5. <filter> 제거 (VD 미지원)
6. <circle>, <rect> → <path> 변환 (clipPath 내부 + 일반 요소 모두)
7. width/height를 viewBox 기반으로 설정
8. opacity → fillAlpha 속성으로 분리 (SVG 색상 형식 유지)

사용법:
    python3 preprocess_svg.py [입력디렉토리] [출력디렉토리]

    기본값:
        입력: /tmp/figma_svg
        출력: /tmp/figma_svg/preprocessed
"""

import re, os, sys

# ─── Named Color 매핑 ───
COLOR_MAP = {
    'white': '#FFFFFF', 'black': '#000000', 'red': '#FF0000',
    'green': '#008000', 'blue': '#0000FF', 'yellow': '#FFFF00',
    'cyan': '#00FFFF', 'magenta': '#FF00FF', 'orange': '#FFA500',
    'gray': '#808080', 'grey': '#808080', 'transparent': '#00000000',
    'none': 'none',
}


def named_to_hex(c):
    return COLOR_MAP.get(c.strip().lower(), c.strip())


def resolve_css_var(val):
    """var(--fill-0, #FFD800) → #FFD800"""
    m = re.match(r'var\([^,]+,\s*(.+?)\)', val)
    return named_to_hex(m.group(1)) if m else val


def hex_to_rgb(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    if len(h) == 6:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if len(h) == 8:
        return int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    return None


def apply_alpha(hex_color, alpha):
    """#RRGGBB + alpha(0~1) → #AARRGGBB"""
    rgb = hex_to_rgb(hex_color)
    if not rgb:
        return hex_color
    a = int(round(alpha * 255))
    return '#{:02X}{:02X}{:02X}{:02X}'.format(a, *rgb)


def circle_to_path_d(cx, cy, r):
    """<circle cx cy r> → SVG path d 문자열 (2-arc)"""
    return 'M{},{} a{},{} 0 1,0 {},0 a{},{} 0 1,0 {},0 Z'.format(
        cx - r, cy, r, r, 2 * r, r, r, -2 * r)


def rect_to_path_d(x, y, w, h, rx=0, ry=0):
    """<rect x y w h rx ry> → SVG path d 문자열"""
    rx = min(rx, w / 2)
    ry = min(ry or rx, h / 2)
    if rx == 0 and ry == 0:
        return 'M{},{}H{}V{}H{}Z'.format(x, y, x + w, y + h, x)
    return (
        'M{},{}H{}Q{},{} {},{}V{}Q{},{} {},{}H{}Q{},{} {},{}V{}Q{},{} {},{}Z'
        .format(
            x + rx, y, x + w - rx, x + w, y, x + w, y + ry, y + h - ry,
            x + w, y + h, x + w - rx, y + h, x + rx, x, y + h, x, y + h - ry,
            y + ry, x, y, x + rx, y
        )
    )


# ─── mask 정의 파싱 ───
def parse_mask_shapes(content):
    """<mask id="...">의 자식 shape를 path d 문자열로 추출"""
    masks = {}
    for m in re.finditer(
            r'<mask\s+id="([^"]*)"[^>]*>(.*?)</mask>', content, re.DOTALL):
        mask_id = m.group(1)
        body = m.group(2)
        paths = []

        # <circle> 추출
        for c in re.finditer(r'<circle[^>]*?(?=/>|>)', body):
            tag = c.group(0)
            cx_m = re.search(r'cx="([^"]*)"', tag)
            cy_m = re.search(r'cy="([^"]*)"', tag)
            r_m = re.search(r'(?<!\w)r="([^"]*)"', tag)
            if cx_m and cy_m and r_m:
                paths.append(circle_to_path_d(
                    float(cx_m.group(1)),
                    float(cy_m.group(1)),
                    float(r_m.group(1))))

        # <rect> 추출
        for r_match in re.finditer(r'<rect[^>]*?(?=/>|>)', body):
            tag = r_match.group(0)

            def attr(name, default='0'):
                a = re.search(r'{}="([^"]*)"'.format(name), tag)
                return float(a.group(1)) if a else float(default)

            paths.append(rect_to_path_d(
                attr('x'), attr('y'), attr('width'), attr('height'), attr('rx')))

        # <path> 추출
        for p in re.finditer(r'<path[^>]*d="([^"]*)"', body):
            paths.append(p.group(1))

        if paths:
            masks[mask_id] = ' '.join(paths)
    return masks


def process_svg(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # ── 1. viewBox → width/height ──
    vb = re.search(r'viewBox="([^"]*)"', content)
    if vb:
        parts = vb.group(1).split()
        if len(parts) == 4:
            vw, vh = parts[2], parts[3]
            content = re.sub(r'\s+width="[^"]*"',
                             ' width="{}"'.format(vw), content, count=1)
            content = re.sub(r'\s+height="[^"]*"',
                             ' height="{}"'.format(vh), content, count=1)

    # ── 2. CSS var() 해석 ──
    content = re.sub(
        r'(fill|stroke|stop-color)="(var\([^)]*\))"',
        lambda m: '{}="{}"'.format(m.group(1),
                                   named_to_hex(resolve_css_var(m.group(2)))),
        content)

    # ── 3. named color → hex ──
    def replace_named(m):
        attr_name, color = m.group(1), m.group(2)
        if color.startswith(('#', 'url(')) or color == 'none':
            return m.group(0)
        return '{}="{}"'.format(attr_name, named_to_hex(color))

    content = re.sub(r'(fill|stroke|stop-color)="([^"]*)"',
                     replace_named, content)

    # ── 4. stop-opacity → 알파 병합 ──
    def merge_stop_opacity(m):
        tag = m.group(0)
        sc = re.search(r'stop-color="([^"]*)"', tag)
        so = re.search(r'stop-opacity="([^"]*)"', tag)
        if sc and so:
            new_c = apply_alpha(sc.group(1), float(so.group(1)))
            tag = tag.replace(sc.group(1), new_c)
            tag = re.sub(r'\s*stop-opacity="[^"]*"', '', tag)
        return re.sub(r'\s+', ' ', tag).strip()

    content = re.sub(r'<stop[^/>]*/>', merge_stop_opacity, content)

    # ── 5. stroke-opacity → 알파 병합 ──
    def merge_stroke_opacity(m):
        tag = m.group(0)
        sc = re.search(r'stroke="([^"]*)"', tag)
        so = re.search(r'stroke-opacity="([^"]*)"', tag)
        if sc and so and not sc.group(1).startswith('url('):
            tag = tag.replace(
                'stroke="{}"'.format(sc.group(1)),
                'stroke="{}"'.format(apply_alpha(sc.group(1),
                                                 float(so.group(1)))))
            tag = re.sub(r'\s*stroke-opacity="[^"]*"', '', tag)
        return tag

    content = re.sub(
        r'<(?:circle|path|line|rect)[^>]*stroke-opacity="[^"]*"[^>]*/?(?:>|/>)',
        merge_stroke_opacity, content)

    # ── 6. path opacity → fill-opacity 변환 (SVG 색상 형식 유지) ──
    def convert_opacity_to_fill_opacity(m):
        tag = m.group(0)
        op = re.search(r'\bopacity="([^"]*)"', tag)
        fl = re.search(r'fill="([^"]*)"', tag)
        if op and fl and fl.group(1) != 'none':
            tag = re.sub(r'\bopacity="([^"]*)"',
                         'fill-opacity="{}"'.format(op.group(1)), tag)
        return tag

    content = re.sub(r'<path[^>]*\bopacity="[^"]*"[^>]*/?>', convert_opacity_to_fill_opacity, content)

    # ── 6b. fill-opacity는 그대로 유지 ──

    # ── 6c. 잘못된 fill- 잔여 제거 (VD 파서 오류 방지) ──
    content = re.sub(r'\s*fill-\s*/?>', ' />', content)

    # ── 6d. 모든 <circle> → <path> 변환 ──
    def circle_to_path_tag(m):
        tag = m.group(0)
        cx_m = re.search(r'cx="([^"]*)"', tag)
        cy_m = re.search(r'cy="([^"]*)"', tag)
        r_m = re.search(r'(?<!\w)r="([^"]*)"', tag)
        if not (cx_m and cy_m and r_m):
            return tag
        cx = float(cx_m.group(1))
        cy = float(cy_m.group(1))
        r = float(r_m.group(1))
        d = circle_to_path_d(cx, cy, r)
        new_tag = tag
        new_tag = re.sub(r'\s*cx="[^"]*"', '', new_tag)
        new_tag = re.sub(r'\s*cy="[^"]*"', '', new_tag)
        new_tag = re.sub(r'\s*(?<!\w)r="[^"]*"', '', new_tag)
        new_tag = new_tag.replace('<circle', '<path d="{}"'.format(d), 1)
        return new_tag

    content = re.sub(r'<circle[^>]*(?:/>|>)', circle_to_path_tag, content)

    # ── 7. ★ <mask> → <clipPath> 변환 ──
    masks = parse_mask_shapes(content)

    clip_defs = ''
    for mask_id, path_d in masks.items():
        clip_id = mask_id.replace('mask', 'clip')
        clip_defs += (
            '<clipPath id="{}">'
            '<path d="{}"/>'
            '</clipPath>\n'
        ).format(clip_id, path_d)

    content = re.sub(r'<mask[^>]*>.*?</mask>', '', content, flags=re.DOTALL)

    if clip_defs:
        if '<defs>' in content:
            content = content.replace('<defs>', '<defs>\n' + clip_defs, 1)
        elif '</defs>' in content:
            content = content.replace('</defs>', clip_defs + '</defs>', 1)
        else:
            content = re.sub(
                r'(<svg[^>]*>)',
                r'\1\n<defs>' + clip_defs + '</defs>',
                content, count=1)

    def replace_mask_ref(m):
        mask_id = m.group(1)
        clip_id = mask_id.replace('mask', 'clip')
        return 'clip-path="url(#{})"'.format(clip_id)

    content = re.sub(r'mask="url\(#([^)]*)\)"', replace_mask_ref, content)

    # ── 8. <filter> 제거 (VD 미지원) ──
    content = re.sub(r'<filter[^>]*>.*?</filter>', '', content, flags=re.DOTALL)
    content = re.sub(r'\s*filter="url\([^)]*\)"', '', content)

    # ── 9. 불필요한 속성 제거 ──
    content = re.sub(r'\s*style="[^"]*"', '', content)
    content = re.sub(r'\s*overflow="[^"]*"', '', content)
    content = re.sub(r'\s*preserveAspectRatio="[^"]*"', '', content)

    # ── 10. 빈 <defs> 정리 ──
    content = re.sub(r'<defs>\s*</defs>', '', content)

    # ── 11. 과학적 표기법 정리 ──
    def fix_sci(m):
        v = float(m.group(0))
        return '0' if abs(v) < 1e-4 else '{:.4f}'.format(v).rstrip('0').rstrip('.')

    content = re.sub(r'-?\d+\.?\d*e[+-]?\d+', fix_sci, content)

    # ── 12. 공백 정리 ──
    content = re.sub(r'[ \t]+', ' ', content)
    content = re.sub(r'\n\s*\n', '\n', content)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)


def main():
    in_dir = sys.argv[1] if len(sys.argv) > 1 else '/tmp/figma_svg'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(in_dir, 'preprocessed')
    os.makedirs(out_dir, exist_ok=True)

    svg_files = sorted([f for f in os.listdir(in_dir) if f.endswith('.svg')])
    if not svg_files:
        print('No SVG files found in', in_dir)
        sys.exit(1)

    ok_count = 0
    fail_count = 0
    for f in svg_files:
        try:
            process_svg(os.path.join(in_dir, f), os.path.join(out_dir, f))
            print('OK:', f)
            ok_count += 1
        except Exception as e:
            print('FAIL:', f, '-', e)
            fail_count += 1

    print('\nDone: {} OK, {} FAIL'.format(ok_count, fail_count))


if __name__ == '__main__':
    main()

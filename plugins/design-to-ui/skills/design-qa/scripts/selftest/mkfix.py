#!/usr/bin/env python3
"""design-qa 사각 재현용 합성 픽스처 — 에뮬레이터 없이 측정기 자체만 검증한다.

#186 (얇은 옅은색 구분선 full-bleed→패딩) + #187 (아이콘 10% 축소) 재현 + golden(정상) 픽스처.
"""
from PIL import Image, ImageDraw, ImageFilter

S = 3                      # @3x
W, H = 360 * S, 780 * S
BG, INK, LINE = (255, 255, 255), (26, 26, 26), (229, 229, 229)   # LINE = 1dp 옅은 회색
DIV_Y = 280 * S
CX, CY = 40 * S, 600 * S


def base():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([16 * S, 24 * S, 200 * S, 44 * S], fill=INK)                       # 제목
    for i in range(4):                                                             # 본문
        d.rectangle([16 * S, (60 + i * 14) * S, (300 - i * 20) * S, (70 + i * 14) * S], fill=(90, 90, 90))
    d.rectangle([16 * S, 140 * S, 344 * S, 260 * S], outline=(220, 220, 220), width=S)   # 카드
    for i in range(6):
        d.rectangle([16 * S, (300 + i * 40) * S, 240 * S, (312 + i * 40) * S], fill=(90, 90, 90))
    return im, d


def cross(d, size_dp, thick_dp=2):
    h, t = size_dp * S // 2, thick_dp * S // 2
    d.rectangle([CX - h, CY - t, CX + h, CY + t], fill=INK)
    d.rectangle([CX - t, CY - h, CX + t, CY + h], fill=INK)


# ── #186 — 구분선 full-bleed(figma) vs 좌우 16dp 패딩(real) ────────────────────
figma, d = base()
d.rectangle([0, DIV_Y, W, DIV_Y + S - 1], fill=LINE)                       # full-bleed (figma 가이드)
figma.save("fix1_figma.png")

real, d = base()
d.rectangle([16 * S, DIV_Y, W - 16 * S, DIV_Y + S - 1], fill=LINE)         # 좌우 16dp 패딩 (플러그인 결과)
real.save("fix1_real.png")

Image.open("fix1_real.png").filter(ImageFilter.GaussianBlur(0.4)).save("fix1_real_aa.png")

# ── #187 — 20dp 아이콘(figma) vs 18dp(real, 10% 작음), 중심 동일 ──────────────
figma, d = base()
cross(d, 20)
figma.save("fix2_figma.png")

real, d = base()
cross(d, 18)
real.save("fix2_real.png")

# 경계 임계 곡선용 — 5% / 10% / 14% 축소 (19dp / 18dp / 17dp)
for dp, pct in ((19, 5), (18, 10), (17, 15)):
    im, d = base()
    cross(d, dp)
    im.save(f"fix2_real_{dp}dp.png")

# ── golden — 기하는 figma와 동일, real 만 AA 잔차. 오탐 검사용 ────────────────
g, d = base()
d.rectangle([0, DIV_Y, W, DIV_Y + S - 1], fill=LINE)   # full-bleed (정상)
cross(d, 20)                                            # 20dp (정상)
g.save("g_figma.png")
for blur in (0.4, 1.2, 2.0):
    g.filter(ImageFilter.GaussianBlur(blur)).save(f"g_real_{blur}.png")
g.filter(ImageFilter.GaussianBlur(0.4)).save("g_real.png")

# ── 실측에서 나온 케이스들 (튜토리얼 앱 + MCP 실응답으로 확인된 것) ─────────────
# (a) 라운드 코너가 **투명한** figma export. 그냥 RGB 로 변환하면 투명이 검정이 되어 max_diff 를
#     아티팩트로 채운다(실측: 코너 3280px 가 max_diff 245 를 만들었다).
rgba, d = base()
rgba = rgba.convert("RGBA")
d = ImageDraw.Draw(rgba)
d.rectangle([0, DIV_Y, W, DIV_Y + S - 1], fill=LINE)
R = 16 * S
corner = Image.new("L", (W, H), 255)
cd = ImageDraw.Draw(corner)
cd.rectangle([0, 0, W, H], fill=0)
cd.rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=255)
rgba.putalpha(corner)
rgba.save("t_figma_rgba.png")
# real 은 불투명하고 코너까지 배경색이 차 있다 (실기 캡처가 그렇다)
opaque, d = base()
d.rectangle([0, DIV_Y, W, DIV_Y + S - 1], fill=LINE)
opaque.save("t_real_opaque.png")

# (b) 저대비(옅은 회색) 아이콘 — 절대 ink 임계로는 안 보인다(실측 대비 15).
#     figma 20dp vs real 18dp 로 크기 오차도 함께 넣어 "저대비 + 크기오차" 를 검사한다.
PALE = (230, 230, 230)
for dp, path in ((20, "p_figma.png"), (18, "p_real.png")):
    im, d = base()
    d.rectangle([16 * S, 590 * S, 64 * S, 638 * S], fill=(245, 245, 245))   # 옅은 카드 배경
    h = dp * S // 2
    t = 2 * S // 2
    d.rectangle([CX - h, CY - t, CX + h, CY + t], fill=PALE)
    d.rectangle([CX - t, CY - h, CX + t, CY + h], fill=PALE)
    im.save(path)

# (c) MCP get_metadata 의 실제 응답 형태 — XML, 좌표는 **부모 기준 상대값**, 타입은 태그명.
#     응답 뒤에 안내문이 붙어 오는 것까지 재현한다(실측).
open("meta_mcp.xml", "w").write(
    '<frame id="1:1" name="Screen" x="0" y="0" width="360" height="780">\n'
    '  <frame id="1:2" name="Content" x="0" y="24" width="360" height="732">\n'
    '    <frame id="1:3" name="Card" x="16" y="116" width="328" height="120">\n'
    '      <boolean-operation id="1:4" name="CheckIcon" x="290" y="50" width="20" height="20">\n'
    '        <vector id="1:5" name="part-a" x="0" y="0" width="20" height="10" />\n'
    '        <vector id="1:6" name="part-b" x="0" y="10" width="20" height="10" />\n'
    '      </boolean-operation>\n'
    '      <text id="1:7" name="Title" x="16" y="16" width="200" height="20" />\n'
    '    </frame>\n'
    '    <rectangle id="1:8" name="Divider" x="0" y="256" width="360" height="1" />\n'
    '  </frame>\n'
    '</frame>'
    "IMPORTANT: After you call this tool, you MUST call get_design_context ...\n")

# (d) glyph_probe 전역 편차·국소 이상치 — 실측에서 ±12% 개별 임계를 **통과해버린** 두 오차의 재현.
#     letterSpacing -0.5% → width_ratio 0.988(1.2%), 한글 줄바꿈 차이 → 1.052(5.2%). 둘 다 12% 아래다.
#     짧은 텍스트(`9:41`, `←`)는 advance 가 누적되지 않아 1.000 으로 나오는 것까지 재현한다 — 이것들이
#     방향 일치 분모에 들어가면 진짜 전역 편차가 희석된다.
GW, GH = 720, 900
GLYPH_FIG = [600, 600, 600, 600, 60, 40, 600, 600]     # 마지막 2개 중 하나가 이상치가 된다
GLYPH_SYS = [593, 593, 593, 593, 60, 40, 593, 630]     # 전역 -1.2% + 1개만 +5%
GLYPH_OK = [598, 601, 599, 600, 60, 40, 602, 599]      # AA 수준 흔들림만


def glyph_bars(path, widths):
    im = Image.new("RGB", (GW, GH), BG)
    d = ImageDraw.Draw(im)
    for i, w in enumerate(widths):
        y = 20 + i * 100
        d.rectangle([40, y, 40 + w - 1, y + 40], fill=(30, 30, 30))
    im.save(path)


glyph_bars("gs_figma.png", GLYPH_FIG)
glyph_bars("gs_real_sys.png", GLYPH_SYS)
glyph_bars("gs_real_ok.png", GLYPH_OK)
open("gs_regions.txt", "w").write(
    "; ".join(f"t{i}:30,{20 + i * 100 - 5},710,{20 + i * 100 + 45}" for i in range(len(GLYPH_FIG))))

# (e) 잠든 기기 캡처 — screencap 은 성공을 반환하고 크기도 맞는데 내용만 단색 검정이다.
Image.new("RGB", (1080, 2340), (0, 0, 0)).save("solid_black.png")


# (f) extent 불일치 — 시스템 영역 높이차만 있는 페어. dp/crop 게이트는 통과하는데 resize 가
#     만든 유령이 진짜 오차를 상쇄해 mean_diff 순위가 **뒤집힌다**(정합본 10.26 > 8dp 오차본 8.55).
def _bottom_anchor(w_dp, h_dp, sys_zone_dp, btn_margin_dp, path):
    K, W, H = 3, w_dp * 3, h_dp * 3
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([16 * K, 52 * K, 200 * K, 80 * K], fill=INK)
    cw = (w_dp - 44) / 2
    y = 96
    for _ in range(3):
        for c in range(2):
            x = 16 + c * (cw + 12)
            d.rectangle([int(x * K), y * K, int((x + cw) * K) - 1, (y + 120) * K - 1], fill=(240, 241, 243))
        y += 132
    sys_top = h_dp - sys_zone_dp
    if sys_zone_dp:
        d.rectangle([0, sys_top * K, W, H - 1], fill=(222, 224, 228))
    bb = sys_top - btn_margin_dp
    d.rectangle([16 * K, (bb - 52) * K, (w_dp - 16) * K - 1, bb * K - 1], fill=(3, 199, 90))
    im.save(path)

_bottom_anchor(393, 852, 34, 16, "e_figma.png")     # iOS 프레임 — 인디케이터존 34dp 포함
_bottom_anchor(393, 828, 0, 16, "e_real_ok.png")    # Android crop — 제스처바 제외, 코드 정합
_bottom_anchor(393, 828, 0, 24, "e_real_bad.png")   # 같은 crop, 버튼이 8dp 위 (진짜 오차)

print(f"생성 {W}x{H} @{S}x  구분선 y={DIV_Y}px  아이콘 중심=({CX},{CY})  "
      "+ 투명코너/저대비/MCP-XML/글리프편차/단색/extent불일치 픽스처")

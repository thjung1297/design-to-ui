# design-qa — iOS 캡처 계층 (최소 스캐폴드)

> 비교·측정 엔진(`overlay`/`align_probe`/`glyph_probe`/
> `color_probe`)은 플랫폼 중립이라 그대로 쓰고, 아래는 iOS 고유의 **캡처·crop**과 실기 검증으로 확인된
> **두 gotcha**만 담는다. 나머지 보정 어휘(텍스트 메트릭·분포·SF Symbol C→A 등)는 android.md와 동형 —
> iOS를 실제로 빌드할 때 SwiftUI/UIKit 처방으로 채운다.
> **글리프 재export 변환(iOS):** `figma-asset-download` SVG → **SVG→PDF `.imageset`**(codegen iOS 에셋 파이프라인, 손 전사 ❌).

## 0. 뷰포트 pt 정규화 (SKILL 워크플로우 0단계 — 캡처보다 먼저)

**Figma 프레임의 dp 크기 = iOS 의 pt 크기다.** 프레임과 **같은 pt 크기의 기종**을 골라 booted 한 뒤 캡처한다
(사다리 ①). iOS 는 Android 의 `wm size`/`wm density` 처럼 논리 크기를 임의로 덮어쓰는 수단이 없으므로
**기종 선택이 유일한 정규화 경로**이고, 맞는 기종이 없으면 사다리 ③(중단·사용자 통보)이다.

**기종 표를 외우거나 하드코딩하지 말 것 — 설치된 Xcode 에서 직접 뽑는다.** 기종별 pt 크기는 Xcode 버전마다
목록이 바뀌고(실측: Xcode 26.3 에는 `iPhone 13 mini` 기종 정의는 있지만 **시뮬레이터 인스턴스가 없어**
`simctl boot "iPhone 13 mini"` 가 `Invalid device` 로 실패한다 — `create` 가 필요하다), 같은 pt 에 여러
기종·다른 scale 이 섞인다(414×896pt 는 @2x iPhone 11 과 @3x 11 Pro Max 가 공존).

```bash
# 프레임 pt → 그 논리 크기를 가진 기종 찾기 (설치된 Xcode 의 실제 정의에서 산출)
python3 - <<'PY'
import plistlib, pathlib
WANT = (360, 780)                      # ← Figma 프레임 dp
for d in sorted(pathlib.Path("/Library/Developer/CoreSimulator/Profiles/DeviceTypes").glob("*.simdevicetype")):
    f = d / "Contents/Resources/profile.plist"
    if not f.exists(): continue
    p = plistlib.load(open(f, "rb"))
    w, h, s = p.get("mainScreenWidth"), p.get("mainScreenHeight"), p.get("mainScreenScale")
    if not all(isinstance(v, (int, float)) for v in (w, h, s)): continue
    if (w / s, h / s) == WANT:
        print(f'{p.get("displayName")}: {w}x{h}px @{s:g}x = {w/s:g}x{h/s:g}pt')
PY

# 인스턴스가 없으면 만들어서 부팅한다 (기종 정의만으로는 boot 되지 않는다)
UDID=$(xcrun simctl create "dqa-360x780" "iPhone 13 mini" com.apple.CoreSimulator.SimRuntime.iOS-26-3)
xcrun simctl boot "$UDID"
xcrun simctl io "$UDID" screenshot "$OUT/cap_full.png"      # → 1080x2340px = 360x780pt @3x
```

**실측 (Xcode 26.3 / iOS 26.3):** `iPhone 12 mini`·`iPhone 13 mini` = **360×780pt @3x = 1080×2340px** —
360×780dp Figma 프레임과 정확히 일치하고, Android 를 `wm size 1080x2340` + `wm density 480` 으로 정규화한
캡처와 **픽셀 1:1** 이다. 그 외 자주 쓰는 값: 375×812(11 Pro/X/Xs) · 390×844(12·13·14·16e) ·
393×852(14 Pro·15·15 Pro·16) · 402×874(16 Pro·17·17 Pro) · 420×912(Air), 전부 @3x.

정규화 여부는 **캡처 픽셀 크기 ÷ scale** 로 역산해 프레임 pt 와 대조한다 (실측 확인: `simctl io … screenshot`
이 정확히 `mainScreenWidth × mainScreenHeight` 를 준다). `overlay.py --figma-dp 360x780 --real-dp 360x780`
으로 게이트를 켜 두면 불일치 시 멈춘다.

> ⚠️ **iOS 에는 사다리 ②가 없다.** Android 의 `wm size`/`wm density` 처럼 논리 크기를 임의 값으로 덮어쓰는
> 수단이 없으므로 **기종 선택(①)이 유일한 경로**이고, 프레임 pt 와 같은 기종이 없으면 곧바로 **③(중단)** 이다.
> 그래서 iOS 검수를 전제한 시안은 **위 실측 목록의 pt 중 하나로 프레임을 잡는 것**이 실질적인 예방책이다.

dp 외에 같이 고정할 변수: Dynamic Type(`-UIPreferredContentSizeCategoryName UICTContentSizeCategoryL`
런치 인자), 다크/라이트는 프레임에 맞춰 전환(`xcrun simctl ui booted appearance dark|light`, 한쪽 고정 금지),
목/데모 데이터 고정.

> **미검증:** 기종 선택·캡처 크기 역산은 위와 같이 실측했다. Dynamic Type 런치 인자가 실제로 먹는지,
> `simctl ui appearance` 전환 후 캡처가 즉시 반영되는지(Android 는 프레임버퍼 지연이 있었다)는 확인하지 않았다.

## 실행 전제 & 캡처

- `xcrun simctl list devices`에 booted 시뮬레이터. 인프라 0(`xcrun`만).
- 캡처: `OUT="$HOME/Desktop/design-qa/{검수화면}"; mkdir -p "$OUT"` 후 `xcrun simctl io booted screenshot "$OUT/cap_full.png"`
  (기본 산출물 위치는 SKILL "산출물 위치(outdir)" — Desktop)
- 시뮬 스크린샷은 **device scale(@2x/@3x) 픽셀**이다 → crop box 좌표를 **point가 아니라 픽셀**로 준다.
  figma 기준 이미지는 `download_assets(defaultScale=k)` 로 받아(`get_screenshot` 은 파일이 안 나온다 — SKILL.md 3단계) `overlay.py`가 real 크기로 resize한다(`resize_ratio` 두 축이 크게 다르면 crop 축 불일치).

## exact-crop

앱이 전체 화면이면 스크린샷에서 상태바만 잘라 `crop.py box`(중립):
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/crop.py" box cap.png real.png --box 0,<statusbar_px>,<W>,<H>
```
그 외(분할·노치 등 오프셋 불확실) crop 모드 선택은 **플랫폼 중립** — SKILL 워크플로우 참조.

## iOS 고유 gotcha (실기 검증 시 반드시)

- **faux-bold:** iOS도 정확한 weight face를 안 주면 시스템이 합성 bold를 만들어 advance가 어긋난다
  (`glyph_probe` coverage↑로 검출). 커스텀 폰트는 weight별 face를 직접 지정(`.custom("Pretendard-Bold", …)`),
  단일 Regular + `.fontWeight(.bold)` 합성 금지. variable 폰트는 `UIFontDescriptor` wght 축 지정.
- **letterSpacing 단위:** figma `style.letterSpacing`는 `letterSpacingUnit`에 따라 px일 수도 %일 수도 있다.
  `PIXELS`면 그 값을 그대로 `.tracking`(pt)에, `PERCENT`일 때만 `fontSize × value`. (px에 fontSize 곱하면 오보정.)

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

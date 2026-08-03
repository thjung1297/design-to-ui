# design-qa — iOS 캡처 계층 (최소 스캐폴드)

> 비교·측정 엔진(`overlay`/`align_probe`/`glyph_probe`/
> `color_probe`)은 플랫폼 중립이라 그대로 쓰고, 아래는 iOS 고유의 **캡처·crop**과 실기 검증으로 확인된
> **두 gotcha**만 담는다. 나머지 보정 어휘(텍스트 메트릭·분포·SF Symbol C→A 등)는 android.md와 동형 —
> iOS를 실제로 빌드할 때 SwiftUI/UIKit 처방으로 채운다.
> **글리프 재export 변환(iOS):** `figma-asset-download` SVG → **SVG→PDF `.imageset`**(codegen iOS 에셋 파이프라인, 손 전사 ❌).

## 실행 전제 & 캡처

- `xcrun simctl list devices`에 booted 시뮬레이터. 인프라 0(`xcrun`만).
- 캡처: `OUT="$HOME/Desktop/design-qa/{검수화면}"; mkdir -p "$OUT"` 후 `xcrun simctl io booted screenshot "$OUT/cap_full.png"`
  (기본 산출물 위치는 SKILL "산출물 위치(outdir)" — Desktop)
- 시뮬 스크린샷은 **device scale(@2x/@3x) 픽셀**이다 → crop box 좌표를 **point가 아니라 픽셀**로 준다.
  figma 기준 이미지는 `get_screenshot`으로 받고 `overlay.py`가 real 크기로 resize한다(`resize_ratio` 두 축이 크게 다르면 crop 축 불일치).

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

# design-qa — Flutter 캡처 계층 & 보정 어휘

SKILL.md의 중립 루프 중 **플랫폼 종속 부분(캡처·exact-crop·뷰포트 정규화)** 은 Flutter 앱이 실제로 도는 **호스트 OS reference에 위임**하고, 이 문서는 **Flutter 보정 어휘**만 담는다. Flutter 전용 캡처 계층은 만들지 않는다.

## 0단계·캡처·crop — 호스트 OS reference 위임

Flutter 앱은 Android 기기/에뮬레이터 또는 iOS 시뮬레이터 위에서 돈다. 뷰포트 dp 정규화·캡처·exact-crop은 **그 호스트의 reference를 그대로 쓴다.**

- **Android에서 실행** → [`android.md`](./android.md). `viewport.py apply --freeze --theme`, `capture.py --expect-package`, `crop.py frame`가 모두 유효하다 — `wm size`/`wm density`/`font_scale`/`uimode`는 **시스템 설정**이라 Flutter 앱에도 그대로 적용된다.
- **iOS 시뮬레이터에서 실행** → [`ios.md`](./ios.md). simctl 캡처·시뮬레이터 bounds crop 그대로.

## 테마 전환

- 시스템 다크모드를 따르는 앱(`ThemeMode.system`)은 호스트 설정 전환(Android `cmd uimode night yes|no`, iOS 시뮬레이터 Appearance)만으로 충분하다.
- `ThemeMode.light`/`dark`를 코드에 **하드코딩**한 앱은 호스트 설정을 바꿔도 안 바뀐다 — 코드에서 반대 테마로 전환한 뒤 재빌드해 캡처한다.

## 보정 어휘 (오차 카테고리 → Flutter 선언값)

확정된 오차만 Figma 선언값으로 교체한다(픽셀 nudge ❌). SKILL 판정 rubric이 짚은 카테고리를 아래 Flutter 선언값으로 되짚는다.

| 오차 카테고리 | Flutter 처방 |
|---|---|
| 간격 (요소 사이) | `SizedBox(width/height:)` · Flex `spacing:`(3.27+) · `Padding(EdgeInsets…)` |
| 크기 (고정 w/h) | `SizedBox` · `BoxConstraints`(부모가 tight면 `Align`/`Center`로 loose 만든 뒤 지정 — [references/flutter/flutter.md 제약 원칙](../../design-to-ui/references/flutter/flutter.md)) |
| 텍스트 메트릭 (세로 드리프트·행 높이) | `height`(=lineHeight÷fontSize) + `leadingDistribution: TextLeadingDistribution.even` + `letterSpacing`(=size×tracking) — 전 `TextStyle`에 전역 적용, 개별 nudge ❌. 상세는 [references/flutter/flutter.md 텍스트 정합 절](../../design-to-ui/references/flutter/flutter.md) |
| 글자 폭·weight (faux-bold) | 가변폰트는 `fontVariations: [FontVariation('wght', N)]` + `fontWeight` 병기, 정적 폰트는 pubspec `fonts:`에 weight별 등록 |
| 색 | 프로젝트 테마 토큰(`ColorScheme`/`AppColors`)으로 매핑 — hex 하드코딩 ❌ |
| 에셋 재export·재배치 | [`figma-asset-download`](../../figma-asset-download/SKILL.md)로 올바른 노드 재추출 → [`scripts/flutter/convert_assets.sh`](../../design-to-ui/scripts/flutter/convert_assets.sh)로 재배치(손 전사 ❌) |

## 재빌드

- 보정 후 `flutter run`이 살아 있으면 hot reload로 재캡처할 수 있으나, **최종 판정 캡처는 클린 빌드**로 한다(hot reload는 상태·에셋 캐시 잔재가 남을 수 있다).

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

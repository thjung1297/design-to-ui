# @Preview 자동 생성 — 차량용(IVI)

> `compose.md`(Step 6)에서 참조하는 문서. Compose 코드 변환을 마친 뒤 적용한다.

코드 변환 완료 후, 화면 단위로 `@Preview` Composable을 생성합니다. Preview는 Step 7 검증의 시각 기준으로도 활용되므로, Mock 데이터를 추측이 아니라 **Figma 디자인에 명시된 실제 값**으로 채워야 합니다.

**생성 전 확인:** 프로젝트에 기존 Preview 컨벤션(파일 위치, 네이밍, `@PreviewParameter` 사용 여부, 공통 Preview 어노테이션)이 있으면 `Glob`/`Grep`으로 먼저 찾아 그 컨벤션을 따른다. 없으면 아래 규칙을 적용한다.

## 1. 화면 단위로 생성

개별 컴포넌트가 아니라 **변환한 화면(메인 export 함수에 대응하는 최상위 Composable) 단위**로 Preview를 만든다. 화면을 구성하는 하위 컴포넌트는 화면 Preview 안에서 함께 렌더되므로 별도 Preview를 만들지 않는다.

## 2. 타겟 디바이스 매트릭스

차량용 디스플레이는 모바일과 달리 **하나의 화면비로 수렴하지 않는다.** 표준 비율(16:9 등), 와이드/파노라마(4.5:1, 24:9 등), 세로형이 같은 앱에서 동시에 지원 대상이 되고, 제조사·차종마다 스펙이 다르다. 따라서 **디바이스 매트릭스를 프로젝트가 정의하고 Preview는 그 정의만 참조**하도록 설계한다.

### 2-1. 디바이스 dp 값 확보 순서

다음 우선순위로 각 디바이스의 `widthDp`/`heightDp`를 결정한다.

1. **프로젝트에 이미 정의된 디바이스 상수 (최우선)** — 기존 Preview나 상수 파일(`object ...Device`, `dimens`, 빌드 설정 등)에 지원 기기 목록이 있으면 그것을 그대로 쓴다. `Glob`/`Grep`으로 먼저 찾는다.
2. **대상 기기·에뮬레이터에서 실측** — 아래 2-2 참고.
3. **Figma 프레임 크기** — 위 둘이 없으면 구현 대상 Figma 화면의 width/height를 사용한다.

프로젝트가 지원 기기 목록을 아직 갖고 있지 않다면, **임의의 값을 추측해 넣지 말고 어떤 기기를 지원해야 하는지 먼저 확인**한다.

### 2-2. dp는 물리 해상도 ÷ density와 다를 수 있다

`@Preview`에 넣어야 하는 값은 물리 해상도가 아니라 **앱에 실제로 주어지는 논리 영역(dp)** 이다.

- 기본 환산은 `dp = px / (density)`, `density = dpi / 160`. 차량 IVI는 density 1.0(160dpi)인 경우가 많아 `px ≈ dp`가 되기도 한다.
- 다만 IVI는 **시스템 UI·OEM 런처 영역·멀티윈도(분할) 호스트**가 화면 일부를 점유하는 경우가 흔해, 앱 영역이 전체 해상도보다 **가로·세로 각각 다른 비율로 작아질 수 있다.** 단순 환산값을 그대로 쓰면 Preview와 실기기가 어긋난다.
- 그러므로 가능하면 실기기/에뮬레이터에서 앱 영역 크기를 확인한 값을 쓴다. Android는 `adb shell wm size` / `adb shell dumpsys window` 로 확인할 수 있고, design-qa의 `crop.py`가 같은 정보를 사용한다.

### 2-3. 매트릭스 정의 템플릿

확인한 기기를 아래 형태로 정리한 뒤 상수로 옮긴다. **구분 이름은 제조사·차종명이 아니라 폼팩터로 둔다**(재사용·확장에 유리하다).

| 구분 | 화면비 | 인치 | 해상도(px) | Landscape(dp) | Portrait(dp) |
|------|--------|------|------------|---------------|--------------|
| `SMALL` (소형 센터) |  |  |  |  |  |
| `STD` (표준 비율) |  |  |  |  |  |
| `WIDE` (와이드·파노라마) |  |  |  |  |  |

### 2-4. 확장성 원칙 (필수)

디바이스별 W/H(dp) 값을 **한 곳의 상수로 정의**하고 Preview는 그 상수만 참조하도록 설계한다. 기기를 추가할 때 상수 테이블에 항목만 더하면 전체 Preview에 반영되어야 한다. **해상도 px를 Preview 함수에 직접 하드코딩하지 않는다.**

`@Preview`의 인자는 컴파일 타임 상수(`const val`)만 받으므로 `object`에 상수로 모은다:

```kotlin
// ▶︎ 사이즈 조정: 아래 상수만 변경하면 모든 Preview에 반영됨.
// 지원 제조사가 여럿이면 동일 패턴의 object 를 제조사별로 추가한다(<Vendor>Device).
private object IviDevice {
    // STD — 표준 비율 센터 디스플레이
    const val STD_LAND_W = 0; const val STD_LAND_H = 0
    const val STD_PORT_W = 0; const val STD_PORT_H = 0
    // WIDE — 와이드·파노라마
    const val WIDE_LAND_W = 0; const val WIDE_LAND_H = 0
    const val WIDE_PORT_W = 0; const val WIDE_PORT_H = 0
    // … 지원 기기별로 동일하게 추가
}
```

> 위 `0`은 플레이스홀더다. 2-1의 순서로 확보한 실제 dp 값으로 채운다.

### 2-5. 레이아웃 모드 (1단/2단)

- `Portrait → isSinglePane = true` (1단) / `Landscape → isSinglePane = false` (2단)
- Preview에서는 config 기반 판단이 동작하지 않으므로, **각 Preview가 `isSinglePane` 값을 명시적으로 주입**한다. 디바이스마다 Landscape/Portrait 두 Preview를 생성한다.
- 이 규칙은 제조사·기기와 무관하게 공통으로 적용한다.

```kotlin
@Preview(name = "STD Landscape(2단)", widthDp = IviDevice.STD_LAND_W, heightDp = IviDevice.STD_LAND_H)
@Composable
private fun WeatherScreen_Std_Land() {
    WeatherScreen(isSinglePane = false, uiState = previewWeatherState)
}

@Preview(name = "STD Portrait(1단)", widthDp = IviDevice.STD_PORT_W, heightDp = IviDevice.STD_PORT_H)
@Composable
private fun WeatherScreen_Std_Port() {
    WeatherScreen(isSinglePane = true, uiState = previewWeatherState)
}
```

### 2-6. 커스텀 멀티프리뷰 어노테이션

Preview가 많아지면 **커스텀 멀티프리뷰 어노테이션**(예: `@IviLandscapePreviews`, `@IviPortraitPreviews`)으로 디바이스 세트를 묶어, 1단/2단 wrapper 함수에 각각 붙이는 방식으로 정리한다. 제조사별로 세트를 나눌 경우 `@<Vendor>LandscapePreviews` 형태로 확장한다.

## 3. Mock 데이터는 Figma 기반으로

Preview에 주입하는 Mock 데이터는 **Figma 디자인에 표시된 실제 텍스트·수치·상태값을 그대로** 사용한다. 임의의 더미 값("Lorem ipsum", 123 등)을 쓰지 않는다.

- design_context의 텍스트 노드, `get_variable_defs`의 값, 스크린샷에 보이는 라벨/수치를 그대로 옮긴다.
- 재사용 가능하도록 Preview용 Mock 데이터를 named 상수/팩토리로 분리한다 (예: `previewWeatherState`). 이렇게 하면 **Step 7 검증에서 Preview 렌더 결과를 Figma 스크린샷과 1:1 대조**할 수 있다.
- URL 이미지(Coil `AsyncImage`)는 Preview에서 렌더되지 않으므로, `@PreviewParameter` 또는 placeholder로 대체하되 레이아웃 크기는 디자인 값 유지.

## 4. Figma 시나리오/variant 기반 추가 Preview

Figma에 정의된 시나리오나 컴포넌트 variant가 있으면, 위 매트릭스에 더해 **각 case별 Preview를 추가 생성**한다.

- Figma variant(예: 빈 상태/로딩/에러, 데이터 많음/적음, 강조 on/off 등) 각각에 대응하는 Mock 데이터로 Preview를 만든다.
- variant를 결정하는 파라미터를 각 Preview에서 해당 case 값으로 고정하고, `@Preview(name = ...)`에 어떤 시나리오인지 명시한다.
- 어떤 variant가 존재하는지는 design_context/스크린샷/`get_variable_defs`에서 확인한다.

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

# @Preview 자동 생성 — 모바일

> `compose.md`(Step 6)에서 참조하는 문서. Compose 코드 변환을 마친 뒤 적용한다.

코드 변환 완료 후, 화면 단위로 `@Preview` Composable을 생성합니다. Preview는 Step 7 검증의 시각 기준으로도 활용되므로, Mock 데이터를 추측이 아니라 **Figma 디자인에 명시된 실제 값**으로 채워야 합니다.

**생성 전 확인:** 프로젝트에 기존 Preview 컨벤션(파일 위치, 네이밍, `@PreviewParameter` 사용 여부, 공통 Preview 어노테이션)이 있으면 `Glob`/`Grep`으로 먼저 찾아 그 컨벤션을 따른다. 없으면 아래 규칙을 적용한다.

## 1. 화면 단위로 생성

개별 컴포넌트가 아니라 **변환한 화면(메인 export 함수에 대응하는 최상위 Composable) 단위**로 Preview를 만든다. 화면을 구성하는 하위 컴포넌트는 화면 Preview 안에서 함께 렌더되므로 별도 Preview를 만들지 않는다.

## 2. 타겟 디바이스

다음 우선순위로 Preview의 `widthDp`/`heightDp`를 결정한다:

1. **Figma 화면 크기 참조 (최우선):** 구현 대상 Figma 화면의 width/height dp 값을 `@Preview`의 `widthDp`/`heightDp`에 주입한다.
2. **기존 Preview 참조:** Figma에서 참조할 width/height 값이 없을 경우, 프로젝트에 이미 생성된 Preview의 `widthDp`/`heightDp` 값을 따른다.
3. **기기 해상도 폴백:** 기존 Preview도 없을 경우, 삼성 또는 Pixel 최신 기기 해상도 1종을 선택해 화면 단위 Preview를 만든다.

```kotlin
// 1순위: Figma 화면 크기(예: 390×844)를 직접 주입
@Preview(name = "Mobile", widthDp = 390, heightDp = 844)
@Composable
private fun WeatherScreenPreview() {
    WeatherScreen(uiState = previewWeatherState)
}

// 3순위 폴백: 기기 디바이스 지정
@Preview(name = "Mobile", device = "id:pixel_8_pro")
@Composable
private fun WeatherScreenPreview() {
    WeatherScreen(uiState = previewWeatherState)
}
```

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

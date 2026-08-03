# Compose 변환 (Step 6)

## Step 6: React → Compose 1:1 변환 + 프로젝트 컨벤션 적용

MCP 출력(React+Tailwind)을 Android Jetpack Compose로 변환하면서 프로젝트 디자인 시스템을 적용합니다.

**에셋 참조:** Step 4~5 산출물 기반으로 에셋을 참조한다.
- **유형 A:** `painterResource(R.drawable.ic_xxx)` / `painterResource(R.drawable.img_xxx)`
- **유형 B:** Step 5에서 `Read`로 확인한 SVG 파라미터를 그대로 Canvas 코드에 반영한다. 추측 금지. **Canvas 코드 작성 완료 후 `/tmp/figma_type_b` 디렉터리를 삭제한다.**
- **유형 C:** 기존 `painterResource(R.drawable.xxx)` 재사용 + **design_context에서 해당 요소의 색상 정보를 확인하고 `ColorFilter.tint()`로 Figma 지정 색상을 적용**한다
- **URL 이미지:** Coil `AsyncImage`

**기존 컴포넌트 재사용:** Step 2의 `get_code_connect_map` 결과에 매핑된 컴포넌트는 **새로 만들지 않고 재사용**합니다. 매핑의 `snippet` 코드를 참고하여 기존 컴포넌트를 호출합니다.

**컴포넌트 트리 검증 (코드 작성 전 필수):** design_context의 메인 export 함수를 보고, 호출되는 모든 자식 컴포넌트를 나열한다. 그런 다음 각 컴포넌트가 Compose 코드에서 어떻게 구현되는지 1:1로 매핑한다. 이 매핑에 빈칸이 있으면 — 즉, React에서 호출되지만 Compose에 대응하는 구현이 없는 컴포넌트가 있으면 — 코드를 작성하기 전에 해결한다. 이 절차의 목적은 "React에 있는데 Compose에 없는 요소"를 코드 작성 전에 잡아내는 것이다. 컴포넌트가 단순 래퍼(아이콘을 감싸는 컨테이너 등)라도 시각적으로 보이는 요소를 포함하면 반드시 대응이 있어야 한다.

**레이아웃 overflow:** React/CSS에서는 overflow가 암묵적으로 처리되지만, **Compose에서는 스크롤을 명시적으로 선언**해야 한다. 코드 변환 전에 다음을 확인한다:
1. **컨테이너 높이 계산:** design_context에서 고정 높이를 가진 컨테이너(`h-[Npx]`)를 식별
2. **자식 요소 합계 계산:** 해당 컨테이너 내부의 자식 높이 합계 (항목 높이 × 개수 + gap/divider)
3. **overflow 판단:** 자식 합계 > 컨테이너 높이이면 `verticalScroll` 또는 `LazyColumn` 적용
4. **스크롤 방향의 유한 제약 확보 (필수):** `verticalScroll`/`horizontalScroll`이 동작하려면, 스크롤 방향에 **유한한 크기 제약(bounded constraint)**이 반드시 있어야 한다. 제약이 무한이면 콘텐츠가 "넘친다"는 기준 자체가 없으므로 스크롤이 동작하지 않는다.
   - 세로 스크롤 → 높이 제약 필요: `height(N.dp)`, `Modifier.weight(1f)` (ColumnScope), `fillMaxHeight()` (부모가 유한 높이일 때) 등
   - 가로 스크롤 → 너비 제약 필요: `width(N.dp)`, `Modifier.weight(1f)` (RowScope), `fillMaxWidth()` (부모가 유한 너비일 때) 등

**텍스트 정합 기본값 (Figma 1:1, 필수):** Figma 텍스트는 line-box 안에서 글자가 중앙 배치되고 letterSpacing −0.5%가 전 스타일에 적용된다. Compose 기본 텍스트 렌더링은 폰트 상/하 비대칭 패딩 + baseline 기준 배치 때문에, **lineHeight 값이 Figma와 같아도 세로로 어긋난다**(size에 비례하는 누적 드리프트·행 높이 부족). 디자인 수치(lineHeight·fontSize)는 그대로 두고 **렌더링 설정만** 모든 TextStyle에 전역 기본 적용한다(개별 nudge ❌):

```kotlin
private val figmaTextPlatformStyle = PlatformTextStyle(includeFontPadding = false) // 폰트 상/하 비대칭 패딩 제거(Figma엔 패딩 개념 없음)
private val figmaLineHeightStyle = LineHeightStyle(
    alignment = LineHeightStyle.Alignment.Center, // line-box 중앙 배치(단일 라인도 lineHeight 여백 유지)
    trim = LineHeightStyle.Trim.None,
)
// 각 TextStyle: platformStyle/lineHeightStyle 위 값 + letterSpacing = (-0.005).em  // Figma tracking -0.5%
```

`includeFontPadding=false` + `LineHeightStyle(Center, None)`가 주 효과(세로 드리프트·행 pitch 복원). `letterSpacing`는 정확성용(효과 <1px). 누락 시 "큰 글자가 작은 글자보다 더 밀리는" 증상이 난다.

> ⚠️ **큰 leading**(line-box ≫ fontSize)에선 Center가 box와 불일치할 수 있어 design-qa로 세로 위치를 별도 검증한다.
**가변폰트 weight 등록 (faux-bold 방지, 필수):** 가변폰트는 `Font()`에 `weight = FontWeight.X`와 `variationSettings`(wght 축)를 **둘 다** 준다. `weight=`를 빠뜨리면 Compose가 합성 bold를 덧씌워 글자 폭(advance)이 어긋난다.

```kotlin
@OptIn(ExperimentalTextApi::class)
private val pretendardBold = FontFamily(
    Font(R.font.pretendard_variable,
         weight = FontWeight.Bold,                                           // ← 매처가 700을 정확 매칭(합성 방지)
         variationSettings = FontVariation.Settings(FontVariation.weight(700))), // ← variable wght 축 = 700
)
// Medium=FontWeight.Medium/500, Regular=FontWeight.Normal/400 동일 패턴
```

> **lint (생성 직후 grep):** 가변폰트 `Font`에 `weight=` 없이 `variationSettings`만 + `fontWeight ≠ Normal` 요청이면 faux-bold. 실기기 의심은 design-qa `glyph_probe`(coverage↑)로 확인.

---

## @Preview 자동 생성

코드 변환 완료 후, 화면 단위로 `@Preview` Composable을 생성한다. **플랫폼에 따라 아래 해당 문서를 `Read`로 읽고 그 규칙을 따른다.**

| 플랫폼 | 참조 문서 |
|--------|----------|
| 모바일 | [`compose-preview-mobile.md`](./compose-preview-mobile.md) |
| 차량용(IVI) | [`compose-preview-automobility.md`](./compose-preview-automobility.md) |

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

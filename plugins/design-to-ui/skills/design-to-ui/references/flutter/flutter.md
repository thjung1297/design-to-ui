# Flutter 변환 (Step 6)

## Step 6: React → Flutter 1:1 변환 + 프로젝트 컨벤션 적용

MCP 출력(React+Tailwind)을 Flutter 위젯으로 변환하면서 프로젝트 디자인 시스템을 적용합니다.

**에셋 참조:** Step 4~5 산출물 기반으로 에셋을 참조한다.
- **유형 A:** SVG → `SvgPicture.asset('assets/icons/ic_xxx.svg')`(`flutter_svg` 의존 필요 — pubspec `dependencies`에 없으면 추가), PNG → `Image.asset('assets/images/img_xxx.png')`. PNG 경로는 **main asset 경로**(`2.0x/` 미포함)로 참조한다(width/height 미지정 시 main 기준 논리 크기로 렌더). ⚠️ 다운로드 스크립트의 `png_nodes`는 `scale=2`이지만 **image-fill(IMAGE fill) 노드**는 `/v1/files/.../images`로 받은 **원본 업로드 해상도라 배율이 임의**다 — `download_figma_frame_images.sh`가 그런 파일명을 stderr에 `Image-fill (원본 업로드 해상도, scale=2 아님): …`로 알리면, 그 파일명들을 `scripts/flutter/convert_assets.sh`의 **3번째 인자**(공백 구분)로 넘긴다. 그러면 `2.0x`로 단정되지 않고 main(1x)에 배치된다(아래 pubspec 절 — main 배치는 디렉터리 선언만으로 충분). 더 높은 배율이 필요하면 Figma REST `scale=3`으로 재추출해 `3.0x/`에 둔다.
- **유형 B:** Step 5에서 `Read`로 확인한 SVG 파라미터를 `CustomPaint`/`CustomPainter`에 그대로 반영한다(arc는 `canvas.drawArc`의 시작·스윕 각도, `strokeWidth`, 색상, opacity). 추측 금지. **CustomPainter 작성 완료 후 `/tmp/figma_type_b` 디렉터리를 삭제한다.**
- **유형 C:** 기존 asset 재사용 + design_context에서 확인한 Figma 지정 색을 `SvgPicture.asset(colorFilter: ColorFilter.mode(색, BlendMode.srcIn))` / `Image.asset(color:)`로 적용한다.
- **URL 이미지:** `Image.network` 또는 프로젝트가 쓰는 캐싱 위젯(`CachedNetworkImage` 등).

**pubspec 등록 필수:** `convert_assets.sh`는 에셋을 복사·배치만 하고 pubspec은 수정하지 않는다(YAML 자동 수정은 들여쓰기 파손 위험). 스크립트가 미선언 WARN을 찍으면 `flutter:`→`assets:` 아래에 Edit로 추가한다:
- **SVG**(`assets/icons/`): 파일이 디렉터리 직속이므로 **디렉터리 항목** `- assets/icons/` 하나면 된다.
- **PNG(2.0x, scale=2 확정 — `convert_assets.sh` 기본값)**: `assets/images/2.0x/`만 있고 main 1x가 없으므로 **디렉터리 선언(`- assets/images/`)으로는 번들되지 않는다** — flutter_tools(3.47.0 `_parseAssetsFromFolder`)는 디렉터리의 **직속 파일만** 논리 에셋으로 열거하고 `2.0x/`에만 있는 파일은 등록하지 않는다. 따라서 **각 논리 경로를 개별 선언**한다: `- assets/images/img_xxx.png` (실제 1x 파일이 없어도 variant가 있으면 등록·번들된다).
- **PNG(main, 배율 불명 — `convert_assets.sh` 3번째 인자로 지정한 image-fill 파일)**: `assets/images/`에 직속 파일로 배치되므로 **디렉터리 항목** `- assets/images/` 하나면 된다.

스크립트 WARN이 위 두 카테고리를 구분해 정확한 경로를 출력한다.

`flutter_svg`를 처음 쓰면 `dependencies`에도 추가한다.

**기존 컴포넌트 재사용:** Step 2의 `get_code_connect_map` 결과에 매핑된 위젯은 **새로 만들지 않고 재사용**한다. 매핑의 `snippet` 코드를 참고하여 기존 위젯을 호출한다.

## React+Tailwind → Flutter 매핑

Tailwind 1단위 = 4px = **4lp**(Flutter 논리픽셀). 아래 표로 옮긴다.

| React/Tailwind | Flutter |
|---|---|
| flex row / col | `Row` / `Column` |
| `gap-N` | `spacing:`(Flutter 3.27+) — 프로젝트 SDK가 낮으면 자식 사이 `SizedBox` |
| `justify-*` / `items-*` | `mainAxisAlignment` / `crossAxisAlignment` |
| `justify-between`의 신축 여백 | `Spacer` |
| `p-N` / `px-N` / `py-N` | `Padding(padding: EdgeInsets…)` |
| absolute 배치 | `Stack` + `Positioned` |
| `rounded-N` | `BorderRadius.circular(N*4)` |
| `shadow-*` | `BoxShadow`(Container `decoration`) |
| `flex-1` | `Expanded`(기본) — `Flexible`은 "채우지 않아도 됨"이라 flex-1과 다르다 |
| 고정 `w-[Npx]`/`h-[Npx]` | `SizedBox(width:/height:)` |
| `overflow-hidden` | `ClipRRect` / `ClipRect` |

**제약 원칙(반드시 이해하고 옮긴다):** Flutter 레이아웃은 **"Constraints go down. Sizes go up. Parent sets position."**(docs.flutter.dev/ui/layout/constraints)이다. CSS와 달리 자식이 부모 제약 **밖** 크기를 가질 수 없으므로, Tailwind 고정 크기를 옮길 때 부모가 tight constraint를 주는 자리(예: `Expanded` 내부)에서는 `SizedBox`가 **무시된다**. 이 경우 `Align`/`Center`로 감싸 loose constraint를 만든 뒤 크기를 지정한다.

**화면 루트:** 전체 화면 프레임은 `Scaffold`로 감싸고, 콘텐츠가 상태바·제스처 영역과 겹치는 디자인이 아니면 `SafeArea`를 둔다. Figma 프레임에 상태바 레이어가 포함돼 있으면 그 레이어는 변환하지 않는다 — OS가 그린다.

**텍스트 스케일:** 시스템 폰트 배율을 `textScaler` 하드코딩으로 무력화하지 않는다(1:1 검증의 폰트 배율 freeze는 design-qa가 담당).

## 컴포넌트 트리 검증 (코드 작성 전 필수)

design_context의 메인 export 함수를 보고, 호출되는 모든 자식 컴포넌트를 나열한다. 그런 다음 각 컴포넌트가 Flutter 위젯으로 어떻게 구현되는지 **1:1로 매핑**한다(React 자식 컴포넌트 ↔ 위젯 1:1). 이 매핑에 빈칸이 있으면 — 즉 React에서 호출되지만 대응하는 위젯 구현이 없으면 — 코드를 작성하기 전에 해결한다. 목적은 "React에 있는데 Flutter에 없는 요소"를 코드 작성 전에 잡아내는 것이다. 단순 래퍼(아이콘을 감싸는 컨테이너 등)라도 시각적으로 보이는 요소를 포함하면 반드시 대응이 있어야 한다.

## 레이아웃 overflow

**소스가 실제로 스크롤 가능한 컨테이너/리스트일 때만** `SingleChildScrollView`(짧은 목록)/`ListView`(긴·가상화 목록)로 감싼다. React/CSS에서는 overflow가 암묵적으로 처리되지만, Flutter는 명시 선언이 필요하다. **소스가 의도적으로 클리핑하는 경우**(`overflow-hidden` 캐러셀, 마스크 처리된 일러스트, 데코레이션 스택 등 스크롤 인터랙션이 없는 요소)는 스크롤로 바꾸지 않는다 — 위 매핑표의 `ClipRect`/`ClipRRect`로 그대로 클리핑을 유지한다. 자식 높이 합계가 고정 높이를 넘긴다는 사실만으로 스크롤 여부를 추론하지 말 것 — 실제 스크롤 동작(스와이프 가능한 캐러셀, 무한 리스트 등)이 design_context·스크린샷에서 확인될 때만 스크롤 위젯을 쓴다.

**스크롤 축 bounded 제약 필수:** 스크롤 방향에 **유한한 크기 제약**이 없으면 Flutter는 스크롤이 아니라 **overflow 에러(`RenderFlex overflowed`)** 또는 unbounded-height assertion을 낸다.
- 세로 스크롤 → 높이 제약: `Expanded`(Column/Flex 자식), `SizedBox(height: N)`, 유한 높이 부모.
- 가로 스크롤 → 너비 제약: `Expanded`(Row 자식), `SizedBox(width: N)`, 유한 너비 부모.

## 텍스트 정합 기본값 (Figma 1:1, 필수)

Figma 텍스트는 line-box 안에서 글자가 중앙 배치되고 tracking(letterSpacing)이 전 스타일에 적용된다. Flutter는 `height`를 지정하지 않으면 폰트 고유 메트릭(ascent/descent)으로 줄 높이가 결정돼 **Figma lineHeight와 무관**해지고, 기본 `leadingDistribution`(`proportional`)은 ascent:descent 비율로 leading을 나눠 **glyph가 위로 치우친다**. 그래서 모든 `TextStyle`에 아래를 기본 적용한다(개별 nudge ❌):

```dart
TextStyle(
  fontSize: 16, height: 22 / 16,                      // Figma lineHeight ÷ fontSize (height는 fontSize 배수)
  leadingDistribution: TextLeadingDistribution.even,   // leading 상하 균등 → glyph가 line-box 중앙(TextStyle Configuration 3). Compose includeFontPadding=false + Center 대응
  letterSpacing: 16 * -0.005,                          // Figma tracking -0.5% (논리픽셀 단위라 fontSize 비례 환산)
)
```

**`TextHeightBehavior`의 `applyHeightToFirstAscent`/`applyHeightToLastDescent`는 기본값(true)을 유지한다** — false로 트리밍하면 Figma line-box(트리밍 없음)와 어긋난다(Compose `Trim.None` 대응). `height` + `leadingDistribution.even`이 주 효과(세로 드리프트·행 높이 복원), `letterSpacing`는 정확성용(효과 <1px). 큰 leading(line-box ≫ fontSize)에서 `even`이 box와 미세 불일치할 수 있는데, 이는 design-qa 세로 검증으로 넘긴다.

## 폰트 weight (faux-bold 방지, 필수)

pubspec `fonts:` 섹션에 weight별 `asset`+`weight:`를 등록한다(400/500/700). 가변폰트 단일 파일이면 `TextStyle`에서 `FontVariation('wght', 700)`과 `fontWeight: FontWeight.w700`을 **병기**한다 — `fontWeight`만 요청하고 축을 안 주면 엔진이 합성(faux) bold를 덧씌워 글자 폭(advance)이 어긋난다.

```dart
// 가변폰트 단일 파일
TextStyle(
  fontFamily: 'Pretendard',
  fontWeight: FontWeight.w700,
  fontVariations: const [FontVariation('wght', 700)],
)
```

```yaml
# 정적 weight 파일들 (pubspec fonts:)
fonts:
  - family: Pretendard
    fonts:
      - asset: assets/fonts/Pretendard-Regular.otf
        weight: 400
      - asset: assets/fonts/Pretendard-Medium.otf
        weight: 500
      - asset: assets/fonts/Pretendard-Bold.otf
        weight: 700
```

## 미리보기

Compose의 `@Preview`에 대응하는 표준 수단이 Flutter엔 없다. 프로젝트에 `widgetbook` 등 프리뷰 컨벤션이 있으면 그 컨벤션에 맞춰 등록하고, 없으면 생략한다 — **별도 프리뷰 파일을 새로 만들지 않는다.**

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

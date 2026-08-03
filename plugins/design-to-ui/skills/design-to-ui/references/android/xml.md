# XML Layout 변환 (Step 6)

## Step 6: React → XML Layout 1:1 변환 + 프로젝트 컨벤션 적용

MCP 출력(React+Tailwind)을 Android XML Layout으로 변환하면서 프로젝트 디자인 시스템을 적용합니다.

**에셋 참조:** Step 4~5 산출물 기반으로 에셋을 참조한다.
- **유형 A:** `@drawable/ic_xxx` / `@drawable/img_xxx` — `ImageView`의 `android:src` 또는 `app:srcCompat`
- **유형 B:** Step 5에서 `Read`로 확인한 SVG 파라미터를 그대로 커스텀 View의 `onDraw()`에서 Canvas 코드로 반영한다(예: 270° arc → `Canvas.drawArc(startAngle, sweepAngle=270f, ...)`). 작성한 커스텀 View는 레이아웃에 **풀 패키지 태그**(`<com.example.TempGaugeView .../>`)로 등록한다. 추측 금지. **Canvas 코드 작성 완료 후 `/tmp/figma_type_b` 디렉터리를 삭제한다.**
- **유형 C:** 기존 `@drawable/xxx` 재사용 + `android:tint` 또는 `app:tint`로 Figma 지정 색상 적용
- **URL 이미지:** Glide 또는 Coil `ImageView` 로딩

**기존 컴포넌트 재사용:** Step 2의 `get_code_connect_map` 결과에 매핑된 컴포넌트는 **새로 만들지 않고 재사용**합니다.

**컴포넌트 트리 검증 (코드 작성 전 필수):** design_context의 메인 export 함수를 보고, 호출되는 모든 자식 컴포넌트를 나열한다. 그런 다음 각 컴포넌트가 XML Layout + Kotlin/Java 코드에서 어떻게 구현되는지 1:1로 매핑한다. 이 매핑에 빈칸이 있으면 코드를 작성하기 전에 해결한다.

**레이아웃 overflow:** React/CSS에서는 overflow가 암묵적으로 처리되지만, **XML Layout에서는 스크롤을 명시적으로 선언**해야 한다. 코드 변환 전에 다음을 확인한다:
1. **컨테이너 높이 계산:** design_context에서 고정 높이를 가진 컨테이너(`h-[Npx]`)를 식별
2. **자식 요소 합계 계산:** 항목 높이 × 개수 + gap/divider
3. **overflow 판단:** 자식 합계 > 컨테이너 높이이면 `ScrollView`(단순 스크롤) 또는 `RecyclerView`(목록형, 재활용)를 적용
4. **스크롤 방향의 유한 제약 확보 (필수):** 스크롤이 동작하려면 스크롤 방향에 **유한한 크기 제약(bounded constraint)**이 있어야 한다. 제약이 무한이면 "넘친다"는 기준이 없어 스크롤이 죽거나 콘텐츠가 한 번에 그려진다.
   - `ScrollView`/`NestedScrollView`: 자신은 높이 제약(`0dp`+`layout_weight`, `match_constraint`, 고정 `Ndp`)을 갖고 **직속 자식은 `wrap_content`**로 둔다. ScrollView 자체를 `wrap_content`로 두면 스크롤이 동작하지 않는다.
   - `RecyclerView`: **`wrap_content` 금지** — 24개 같은 다량 항목을 한 번에 그려 재활용이 무력화된다. `0dp`+`layout_weight` 또는 고정 높이로 bounded 제약을 준다.
   - 가로 스크롤은 `HorizontalScrollView` / 가로 `RecyclerView`에 같은 원리(너비 제약)를 적용한다.

**혼합 스타일 텍스트**: 단일 `TextView` + `Spannable`, 분리 금지.

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

# UIKit 변환 (Step 6)

## Step 6: React → UIKit 1:1 변환 + 프로젝트 컨벤션 적용

MCP 출력(React+Tailwind)을 UIKit(코드 기반 Auto Layout 권장)으로 변환하면서 프로젝트 디자인 시스템을 적용합니다.

**에셋 참조:** Step 4~5 산출물 기반으로 에셋을 참조한다.
- **유형 A:** `UIImageView(image: UIImage(named: "ic_xxx"))`. 단색 템플릿 아이콘은 `UIImage(named:)?.withRenderingMode(.alwaysTemplate)` + `tintColor`.
- **유형 A (vector shape):** 단순 사각형/원이 아닌 커스텀 vector shape(곡선·비대칭 외곽 포함)은 사각형으로 근사하거나 통이미지로 뭉개지 말 것. SVG를 받아(`get_design_context`에 path가 안 보이면 노드를 개별 다운로드) ① path를 `UIBezierPath` + `CAShapeLayer`(`fillColor`·동적 리사이즈)로 그리거나 ② 형태·색 고정이면 PNG/PDF 에셋으로 배치한다. path 좌표는 SVG viewBox 기준이므로 뷰 크기에 맞춰 스케일한다.
- **유형 B:** Step 5에서 `Read`로 확인한 SVG 파라미터를 그대로 `CAShapeLayer`/`UIBezierPath`(또는 `draw(_:)`)에 반영한다. 추측 금지. **코드 작성 완료 후 `/tmp/figma_type_b`를 삭제한다.**
- **유형 C:** 기존 asset 또는 `UIImage(systemName:)`(SF Symbol) 재사용 + `tintColor`로 Figma 지정 색상 적용.
- **URL 이미지:** 프로젝트 표준 비동기 이미지 로딩 라이브러리 사용.

**레이아웃 매핑 (Tailwind → UIKit Auto Layout):**
| Tailwind/React | UIKit |
|----------------|-------|
| `flex-row` / `flex-col` | **기본: 명시적 Auto Layout 제약**(leading/trailing/centerY 등; SnapKit 등 DSL) — `UIStackView`는 항목 가변·균등 분배 등 진짜 동적일 때만 |
| `gap-[Npx]` | 인접 뷰 제약 상수 (stack 채택 시에만 `stackView.spacing`) |
| `p-[Npx]` | `layoutMargins` 또는 제약 상수 |
| `w-[Npx]` / `h-[Npx]` | width/height 제약(`widthAnchor`/`heightAnchor`) |
| `flex-1` | `distribution = .fill`/`.fillEqually` 또는 hugging/compression 우선순위 |
| `justify-*` / `items-*` | `alignment`/`distribution` + 제약 |
| `rounded-[Npx]` | `layer.cornerRadius = N` (+ `clipsToBounds`) |
| `absolute` 오버레이 | superview에 addSubview + 제약/`frame` |

> **flex를 무조건 `UIStackView`로 매핑하지 말 것.** figma는 절대 좌표·크기를 모두 주므로 명시적 제약이 1:1 충실도·검증에 유리하다. stack은 항목 가변·균등 분배 등 동적 케이스에서만 쓰되 `distribution`·`alignment`·`isLayoutMarginsRelativeArrangement`·`insetsLayoutMarginsFromSafeArea`를 명시하고 safeArea·회전에서 검증한다.

**효과 매핑 (gradient·blur·shadow — 무시·단색 대체 금지):** design_context의 `*-gradient`/`backdrop-blur`/`shadow`/`inset` 효과는 단색이나 생략으로 뭉개지 말고 그대로 옮긴다.
| design_context 효과 | UIKit |
|----------------|-------|
| `linear-gradient` | `CAGradientLayer` — 값은 아래 gradient 섹션(REST 직독) |
| `conic-gradient` | `CAGradientLayer(type: .conic)` |
| `radial-gradient` | `CAGradientLayer(type: .radial)` |
| `backdrop-blur` | `UIVisualEffectView(effect: UIBlurEffect(...))` (+ 반투명 overlay는 별도 뷰) |
| `box-shadow`(드롭) | `layer.shadowColor/Opacity/Offset/Radius` (+ 성능 위해 `shadowPath`) |
| `inset`(inner) shadow | layer로 직접 안 되므로 역(reverse) path `CAShapeLayer` + shadow, 또는 내부 1px 라인/그라데이션으로 재현 |

`CAGradientLayer`/`CAShapeLayer`의 frame은 `layoutSubviews`에서 `bounds`로 갱신한다(외부에서 `layoutIfNeeded` 강제 호출 금지).

### gradient (fill·stroke) — Figma REST raw paint 직독 (CSS 값 사용 금지)

`get_design_context`의 CSS는 gradient에 한해 손실본이다 — `linear-gradient(Ndeg,…)`의 각도·stop%가 원본과 다르게 재투영된다. gradient 값은 노드 raw paint를 직독한다:

```
GET https://api.figma.com/v1/files/{fileKey}/nodes?ids={nodeId}&geometry=paths
헤더: X-Figma-Token: $FIGMA_ACCESS_TOKEN
```

- 노드의 `fills[]`·`strokes[]`에서 `type == "GRADIENT_LINEAR"`(RADIAL/ANGULAR 포함)를 찾는다.
- **매핑 (Figma → CAGradientLayer, 좌표계 동일 — 정규화·좌상단 원점·y-down → 직매핑):**
  - `gradientStops[].color` → `colors`, `gradientStops[].position` → `locations`
  - `gradientHandlePositions[0]` → `startPoint`, `[1]` → `endPoint` (CGPoint 그대로, [0,1] 벗어나도 그대로 사용)
  - 각도→start/end 수동 환산 금지 — 핸들을 직접 쓴다.

**border/stroke:** `get_design_context`는 gradient stroke를 `border-[#hex]` 단색으로 평탄화하므로 CSS만으로는 단색/그라데이션 구분이 불가능하다. border가 있는 노드는 반드시 REST `strokes[].type`을 확인하고, `GRADIENT_*`면 `CAGradientLayer + CAShapeLayer(stroke) mask`(path = `bounds.insetBy(dx: lineWidth/2, dy: lineWidth/2)`, cornerRadius도 `-inset` 보정)로 구현.

**per-element gradient:** 반복 요소(그래프 막대 등)는 컨테이너 1개 gradient로 근사하지 말고 각 노드 paint를 확인해 요소별로 그린다.

**gradient 텍스트(`bg-clip-text`)**: `UILabel`을 `mask`로 쓰고 그 위에 `CAGradientLayer`. 핸들이 텍스트 bbox 기준 정규화라, gradient frame 폭을 글리프 실제 폭(`min(intrinsicWidth, bounds.width)`)으로 clamp한다.

**검증:** 구현한 `colors`/`locations`/`startPoint`/`endPoint`가 REST paint 값과 일치하는지 그 자리에서 수치 대조한다.

색상·타이포는 하드코딩(hex) 금지 — project-design-system 토큰으로 매핑한다.

**기존 컴포넌트 재사용:** Step 2의 `get_code_connect_map`에 매핑된 컴포넌트는 새로 만들지 않고 재사용한다.

**뷰 파일 분리 (컴포넌트 경계 기준):** Step 4의 컴포넌트 호출 인벤토리에서 반복되거나 재사용 가능한 하위 컴포넌트(리스트 아이템, 그래프/게이지, 뱃지, 페이지 인디케이터 등)는 별도 `UIView` 타입·파일로 추출한다. 분리 단위는 임의로 정하지 말고 **Figma 노드/컴포넌트 경계**를 따른다(design_context에서 하나의 컴포넌트로 호출되는 것 = 하나의 뷰 타입). 단일·소형 컴포넌트는 1파일로 유지한다. ⚠️ 새 `.swift` 파일은 Xcode 타겟 멤버십(`project.pbxproj`)에 등록돼야 빌드에 포함된다 — 프로젝트 방식에 맞춰 처리한다.

**컴포넌트 트리 검증 (코드 작성 전 필수):** design_context의 메인 export 함수에서 호출되는 모든 자식 컴포넌트를 나열하고, 각각이 UIView/UIViewController로 1:1 매핑되는지 확인한다. 빈칸이 있으면 코드 작성 전에 해결한다.

**스크롤(overflow):** 고정 높이 컨테이너의 자식 합계가 넘치면 `UIScrollView`(+ contentLayoutGuide 제약) 또는 목록형은 `UICollectionView`/`UITableView`를 적용한다.

**반복·그리드·목록 (개별 뷰 나열 금지):** design_context에 동일 구조 자식이 반복되면(map 렌더·다수 동형 셀) 개별 뷰로 나열하지 말고 `UICollectionView`(그리드·가로 스크롤 포함)/`UITableView`로 구성한다. 항목 수가 고정 소수(2~4개)이고 비반복이면 개별 뷰 + 제약으로 둔다. 컬렉션 레이아웃·셀 크기 등 세부는 프로젝트 규칙/`project-design-system`을 따르고, `dataSource`·바인딩은 데이터 계층 영역이다(이 스킬은 컨테이너 선택까지).

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

---
description: 피그마 변경을 현재 design/* 브랜치에 반영(커밋·푸시). `/figma-start` 이후에 사용.
license: Apache-2.0
argument-hint: <figma_link>
---

# /figma-apply

디자이너가 피그마에서 수정한 내용을 현재 `design/*` 브랜치에 반영하기 위한 커맨드입니다.
브랜치 생성·체크아웃은 `/figma-start`가 담당하므로, 이 커맨드는 항상 `design/*` 브랜치 위에서만 동작합니다.

## 사용 예시

```
/figma-apply https://figma.com/design/xxx?node-id=1-2
```

## 실행 순서

### 1. 인자 파싱 및 컨텍스트 확인

- `$ARGUMENTS`에서 피그마 URL 추출
- **작업 대상 프로젝트 결정** — 현재 디렉터리가 `design/*` 브랜치의 git 레포면 그대로 쓴다. 아니면 `~/.design-to-ui/current-project`(`/figma-start`가 기록)를 읽어 그 경로에서 진행한다. 이후 모든 명령은 그 경로 기준(`cd`/`git -C`). **디자이너에게 폴더 이동이나 재실행을 요구하지 않는다.**
- 그 경로의 브랜치도 `design/`로 시작하지 않고, 기록도 없으면 에러: "`/figma-start <dev_pr_link>` 를 먼저 실행해주세요."

### 2. 피그마 변경 적용

- **`figma-diff-apply` 스킬에 위임** — 변경점 식별 및 최소 코드 수정 수행

### 3. 커밋 & 푸시

- 커밋 제목(첫 줄)은 짧게: `design: figma-apply {figma_node_id} 반영`
- **커밋 본문 = 디자이너가 입력한 프롬프트 전문 + 빈 줄 + `figma-diff-apply`가 출력한 변경 테이블** (피그마 링크는 프롬프트 안에 있으므로 자연스럽게 포함됨)
- `git push -u origin HEAD`

### 4. 안내 메시지

마지막에 디자이너에게 다음 메시지 출력:

> 푸시 완료. 빌드 돌려서 변경 사항을 확인해주세요.
> 피그마에서 더 수정하시려면 다시 `/figma-apply {figma_link}`를, 개발자에게 전달하시려면 `/handoff`를 실행해주세요.

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

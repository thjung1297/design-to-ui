## Figma MCP 사전 확인

Figma 관련 도구를 호출하기 **전에** Figma Desktop MCP 연결 상태를 확인합니다.

### Figma Desktop 앱 MCP 연결 확인

`figma-desktop` MCP는 Figma Desktop 앱이 실행 중이어야 합니다.

1. **Figma Desktop 앱**이 실행 중인지 확인
2. MCP 도구(`get_design_context` 등) 호출 시 연결 오류가 발생하면:
   - "Figma Desktop 앱이 실행 중인지 확인해주세요."
   - "Figma Desktop 앱에서 Settings > Claude for Figma 플러그인이 활성화되어 있는지 확인해주세요."

### Figma Personal Access Token 확인

에셋 다운로드(`figma-asset-download` 스킬)에는 `FIGMA_ACCESS_TOKEN` 환경 변수가 필요합니다.

```bash
echo $FIGMA_ACCESS_TOKEN
```

- 값이 출력되면 → 에셋 다운로드 진행
- 비어있으면 → 사용자에게 안내:
  1. [Figma Settings](https://www.figma.com/settings)에서 Personal Access Token 발급 (권한: `file_content:read`)
  2. 환경 변수 설정:
     ```bash
     echo 'export FIGMA_ACCESS_TOKEN="figd_xxx"' >> ~/.zshrc && source ~/.zshrc
     ```
  3. Claude Code 재시작

## MCP 인증 오류 처리

### 연결 오류 발생 시

MCP 도구 호출에서 연결 오류가 발생하면:

1. **Figma Desktop 앱 실행 여부** 확인 안내
2. **Claude for Figma 플러그인 활성화** 확인 안내
3. 토큰 관련 오류라면 토큰 재설정 안내

**절대 하지 말 것:**
- `curl`로 Figma API 직접 호출하여 MCP 우회 시도 금지 (에셋 다운로드 스크립트 제외)
- MCP를 우회하는 다른 방법 시도 금지

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

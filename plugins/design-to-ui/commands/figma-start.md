---
description: dev PR 기반 프로젝트 클론 + design/* 브랜치 생성·체크아웃 + 커밋 이력 패널 + 빌드·실행까지. 디자이너 검수 시작용 (커밋 없음).
license: Apache-2.0
argument-hint: <dev_pr_link>
---

# /figma-start

디자이너가 개발자의 원본 PR 위에서 검수를 시작할 때 호출하는 커맨드입니다.
**PR 링크 하나만 주면 프로젝트 클론부터 합니다** — 검수할 프로젝트를 미리 받아둘 필요가 없습니다.
브랜치 생성·체크아웃 후 **빌드해서 기기에 올려 화면까지 띄워줍니다** — 실행할 기기·에뮬레이터가 없으면 검수에 맞는 걸 설치해서 만듭니다.
**그 브랜치의 커밋 이력 패널도 개발툴에 띄워줍니다** — 지금까지 반영한 검수 내용을 검수 내내 옆에 두고 볼 수 있습니다.
**커밋·푸시는 하지 않습니다.** 디자이너가 화면을 먼저 확인한 뒤, 필요하면 `/figma-apply`로 피그마 변경을 반영합니다.

## 사용 예시

```
/figma-start https://github.com/<owner>/<repo>/pull/123
```

## 실행 순서

### 1. dev PR 조회 & 프로젝트 확보

- `$ARGUMENTS`에서 dev PR URL 추출 → API 조회 → dev 브랜치명 확보
- 조회 실패(404 등) 시 에러: "dev PR을 찾을 수 없습니다: {입력 링크}"
- 채팅창에 출력: **"dev PR #{번호} ({제목}) 기반으로 design 브랜치를 준비합니다."**

**프로젝트가 로컬에 없으면 여기서 클론한다.** 초기 환경 준비를 끝낸 디자이너는 개발툴·에뮬레이터만 준비된 상태이고, 검수 대상 프로젝트는 아직 받아둔 적이 없다. PR 링크만으로 진행되게 한다.

- 현재 디렉터리의 `origin`이 PR의 `{owner}/{repo}`와 같으면 그대로 쓴다. 다르면 `~/{repo}`, `~/git/{repo}`, `~/AndroidStudioProjects/{repo}` 에서 **같은 origin인 클론을 먼저 찾고**(중복 클론 방지), 없으면 `~/{repo}` 에 클론한다 — 시간이 걸리니 경로를 먼저 한 줄 알린다. 클론 실패(GitHub 인증 등)면 중단하고 안내한다.
- 확보한 경로를 `PROJECT_DIR`로 두고, **이후 모든 git·빌드 명령은 이 경로 기준**(`cd {PROJECT_DIR} && …` 또는 `git -C {PROJECT_DIR} …`)으로 실행한다. 세션의 시작 폴더가 프로젝트가 아니어도 **디자이너에게 세션 재시작·재실행을 요구하지 않는다** — 경로를 알고 있으면 그대로 진행할 수 있다. 파일 읽기·수정에 접근 권한이 필요하면 `/add-dir {PROJECT_DIR}` 로 확보한다.
- 다음 커맨드가 세션이 바뀌어도 이 프로젝트를 찾을 수 있게 경로를 남긴다: `PROJECT_DIR` 을 `~/.design-to-ui/current-project` 에 기록(디렉터리 없으면 생성, 한 줄 덮어쓰기).
- 프로젝트를 개발툴로도 열어준다 — 디자이너가 코드·프리뷰·Terminal 패널을 쓰고, 2c에서 커밋 이력 패널도 여기에 띄운다. **Flutter 판별은 `PROJECT_DIR` 루트로 한정하지 않는다** — 모노레포(예: `apps/mobile/`에 Flutter 앱)에서는 루트에 `pubspec.yaml`이 없거나 있어도 Flutter SDK 의존이 없을 수 있다. 변환 대상 화면이 속한 파일에서 위로 탐색하며 **Flutter SDK 의존**(`dependencies:`→`flutter:`→`sdk: flutter`)이 있고 `lib/` Dart 코드가 있는 가장 가까운 `pubspec.yaml` 디렉터리를 찾고, 대상 화면이 아직 없으면 저장소 전체에서 그런 디렉터리를 찾는다(`find {PROJECT_DIR} -name pubspec.yaml -not -path '*/build/*'` 후 각각 확인). 찾으면 그 디렉터리를 `FLUTTER_APP_DIR`로 두고 **개발툴 열기·3c 빌드 명령은 `FLUTTER_APP_DIR` 기준**으로 실행한다(`open -a "Android Studio" {FLUTTER_APP_DIR}`) — git·브랜치 관련 명령은 계속 `PROJECT_DIR`(레포 루트) 기준. 못 찾으면 순수 Dart 패키지이므로 이 우선을 적용하지 않고 아래 네이티브 신호로 판정한다. gradle 파일이 있으면 `open -a "Android Studio" {PROJECT_DIR}`, `*.xcworkspace`(우선)/`*.xcodeproj` 가 있으면 `open {해당 경로}`. 둘 다 아니거나 디자이너가 다른 툴을 쓰고 있으면 `open -a "{앱 이름}" {PROJECT_DIR}` 로 그 툴에 연다. **무엇으로 열었는지(앱 이름)를 기억해 둔다** — 2c가 그 툴 기준으로 동작한다. **개발툴 실행 실패는 중단 사유가 아니다** — 빌드는 3단계에서 CLI로 하므로, 경로만 알리고 계속 진행한다.

### 2. 브랜치 준비

- 브랜치명 규약: **`design/{github_id}/{dev_pr_number}`**
  - 예: `https://github.com/my-org/weather-app/pull/1234` 를 `my-id` 가 검수
    → `design/my-id/1234`
  - `design/` prefix는 그대로 유지한다 — `/figma-apply`·`figma-diff-apply`가 이 prefix로 "지금 검수 중인
    브랜치"를 판별한다.
  - **프로젝트명은 넣지 않는다** — 브랜치는 그 프로젝트 레포 안에만 존재하므로 이름에 또 적어도 구분되는 게
    없다. 한 레포 안에서 PR 번호는 유일하고, 사람 구분은 `{github_id}`가 한다.
  - `{dev_pr_number}`는 1단계에서 받은 **PR URL에서 그대로 파싱**한다(추가 조회 불필요).
  - `{github_id}`는 생략 불가. `GH_HOST=<PR 호스트> gh api user --jq .login`으로 얻고, 얻지 못하면 임의로 짓지 말고
    중단하고 `gh auth login`을 안내한다 — 같은 dev PR을 여러 사람이 검수할 수 있어서, 소유자가 브랜치명에 없으면
    남의 검수 브랜치를 덮어쓰거나 남의 것을 자기 것으로 오인한다.

**한 dev PR에 `/figma-start`를 몇 번이든 다시 돌릴 수 있다 — 횟수 제한 없음.** 다만 이미 검수 이력이 있으면
디자이너 의사를 확인해야 한다.

#### 2a. 같은 이름이 없을 때 — 묻지 않는다

로컬(`git branch --list`)·원격(`git ls-remote --heads origin`) 어디에도 없으면 dev 브랜치에서 그대로 분기·
체크아웃하고 3단계로 간다. **이 경우 아무것도 묻지 않는다** — 첫 검수인데 확인을 받으면 그냥 방해다.

#### 2b. 같은 이름이 이미 있을 때 — 디자이너에게 묻는다

이전 검수를 **이어서** 하려는 건지 dev PR 기준으로 **새로 시작**하려는 건지는 디자이너만 안다. 자동으로 이어
붙이면 지난 수정과 이번 검수가 한 PR에 섞이고, 자동으로 새 브랜치를 만들면 어제 하던 작업을 못 찾는다. 그래서
**임의로 정하지 않고 묻는다.**

1. **후보마다 뭐가 들어 있는지 먼저 조사한다** — 이름만 나열하면 디자이너가 고를 수 없다:
   ```bash
   git log origin/{후보} --not origin/{dev_branch} --format='%ad │ %s%n    %b' --date=short
   ```
   dev 브랜치 이후 쌓인 `/figma-apply` 커밋만 뽑힌다. 커밋 **제목은 `design: figma-apply {node_id} 반영`으로
   내용이 없고 본문(`%b`)에 디자이너가 입력한 프롬프트와 변경 테이블이 들어 있으니**, 본문을 읽어 사람이 알아볼
   말로 요약한다(node id 나열 ❌). 원격만 있으면 `git fetch origin {후보}` 후 조회한다.
   **dev 브랜치가 이미 머지·삭제됐으면 `--not origin/{dev_branch}` 가 `fatal: unknown revision` 으로 죽는다** —
   `git rev-parse --verify -q origin/{dev_branch}` 로 먼저 확인하고, 없으면 `--not` 없이 최근 커밋만 뽑는다.
2. 요약과 함께 선택지를 제시하고, **답을 받기 전에는 브랜치를 만들지도 체크아웃하지도 않는다:**

   > `design/my-id/1234` 에 이미 검수 작업이 있습니다 (마지막 2026-07-26, 커밋 3개)
   > - 리스트 항목 ↔ 서브정보 간격 정합
   > - 뒤로 셰브론 크기 정합
   >
   > `design/my-id/1234-2` (마지막 2026-07-27, 커밋 1개)
   > - 상단 탭 색 토큰 교체
   >
   > 어떻게 진행할까요?
   > 1. 위 브랜치 중 하나에서 **이어서** 검수 — 번호(또는 브랜치명)를 알려주세요
   > 2. dev PR #1234 기준으로 **새로 시작** — `design/my-id/1234-3` 을 새로 만듭니다

3. **이어서**를 고르면 그 브랜치를 체크아웃하고 `git pull --ff-only`로 최신화한다.
   **새로 시작**을 고르면 비어 있는 첫 이름(`-2`, `-3` …)으로 dev 브랜치에서 분기한다.

**커밋·푸시는 어느 경로에서도 수행하지 않음** — 첫 푸시는 `/figma-apply` 시점에 `git push -u`로 처리한다.

#### 2c. 커밋 이력 패널을 띄운다 (2a·2b 공통)

브랜치가 확정되면 개발툴의 커밋 이력 뷰를 앞으로 꺼내 검수 내내 보이게 한다. 1단계에서 연 앱 이름을 쓰고,
모르면 frontmost 앱을 조회한다. **표에 없는 툴은 단축키를 지어내지 말고** 바로 아래 폴백으로 간다.

| 개발툴 | 커밋 이력 뷰 | 키 |
|---|---|---|
| Android Studio · IntelliJ 계열 | Git 도구 창의 Log 탭 | ⌘9 |
| Xcode | Source Control navigator | ⌘2 |
| VS Code · Cursor 계열 | Source Control 뷰 | ⌃⇧G |

```bash
osascript -e 'tell application "System Events" to name of first application process whose frontmost is true'
# 접근성 권한이 없으면 keystroke 는 (1002) 로 실패한다 — 반드시 이 형태로 묶어 조건부 실행
[ "$(osascript -e 'tell application "System Events" to get UI elements enabled')" = "true" ] && \
  osascript -e 'tell application "{앱}" to activate' \
            -e 'tell application "System Events" to keystroke "{키}" using {수식키}'
```

**keystroke 가 못 나갔으면(권한 없음·표에 없는 툴) 패널 없이 넘어가지 않는다** — `git log` 를 도는
`.command` 스크립트를 만들어 `open` 으로 띄운다. `open` 은 접근성·자동화 권한이 필요 없고, 창은 Enter 로
새로고침돼 `/figma-apply` 반영분이 그대로 쌓인다.

**패널을 띄웠든 못 띄웠든 커밋 목록은 채팅에 한 번 찍는다.** 어느 경우든 검수를 막지 않는다.

```bash
git -C {PROJECT_DIR} rev-parse --verify -q origin/{dev_branch} >/dev/null \
  && RANGE="--not origin/{dev_branch}" || RANGE="-n 20"   # dev 브랜치 삭제 시 --not 은 fatal
git -C {PROJECT_DIR} log {확정된 브랜치} $RANGE --format='%ad │ %s' --date=short
```

### 3. 빌드 & 실행

검수는 화면을 봐야 시작된다. 체크아웃한 브랜치 **그대로** 빌드해 기기에 올리고 대상 화면까지 띄운다.
디자이너에게 빌드 명령을 떠넘기지 않는다.

**3a. 실행 대상 확보 — 있는 걸 먼저 쓴다.**

- Android: `adb devices` 에 기기·에뮬레이터가 있으면 그걸 쓴다. 없으면 `emulator -list-avds` 로 설치된 AVD를
  찾아 부팅한다.
- iOS: `xcrun simctl list devices booted` 에 있으면 그걸 쓴다. 없으면 `available` 목록에서 골라 boot 한다.

**3b. 하나도 없으면 검수에 맞는 걸 설치해서 만든다.** 실행 대상이 없다고 멈추지 않는다. 다만 시스템 이미지는
수 GB 다운로드라 조용히 하면 디자이너가 왜 멈춰 있는지 모른다 — **무엇을 왜 설치하는지 먼저 한 줄 알리고 진행**한다.

- **Android는 resizable AVD를 우선 만든다.** 하나의 에뮬레이터에서 폰·폴더블·태블릿 폼팩터를 전환해 볼 수 있어
  검수 한 번으로 여러 폼팩터를 덮는다 — 폼팩터마다 AVD를 따로 만드는 것보다 디스크·시간이 훨씬 싸다.
  ```bash
  sdkmanager "system-images;android-35;google_apis;arm64-v8a"   # Apple Silicon (Intel 은 x86_64)
  avdmanager create avd -n figma-qa-resizable \
    -k "system-images;android-35;google_apis;arm64-v8a" --device "resizable"
  emulator -avd figma-qa-resizable &
  ```
  `--device "resizable"` 를 그 SDK가 모르면 `avdmanager list device` 로 대체 폼팩터(예: `pixel_7`)를 고른다.
- **iOS**: `xcrun simctl create` 로 최신 런타임의 표준 아이폰 시뮬레이터를 만들고 boot 한다.
- `sdkmanager`·`avdmanager`·`emulator` 가 PATH에 없으면 Android SDK 경로(`$ANDROID_HOME/cmdline-tools/latest/bin`,
  `$ANDROID_HOME/emulator`)를 먼저 찾는다. SDK 자체가 없으면 그때는 설치를 대신 하지 말고 Android Studio 설치를
  안내한다 — IDE 설치는 디자이너 계정·동의가 필요한 작업이다.

**3c. 빌드·설치·실행.** 프로젝트의 표준 명령을 쓴다 (Android: `./gradlew :{module}:installDebug` → `adb shell am
start`, iOS: `xcodebuild` → `simctl launch`, **Flutter: `flutter run -d <device> --no-resident`**(`FLUTTER_APP_DIR` 기준으로 실행 — 모노레포면 `PROJECT_DIR`와 다를 수 있다)). `--no-resident`를 반드시 붙인다 — `flutter run`은 기본값(`--resident`, `flutter run --help -v`의 `--[no-]resident` 항목 기준 defaults to on)이 hot-reload 입력을 기다리며 상주해 4단계 완료 메시지에 도달하지 못하게 막는다. 모듈·variant·스킴이 불확실할 때만 디자이너에게 묻는다.

빌드가 실패하면 **브랜치는 그대로 두고** 실패 요지와 다음 액션만 알린다 — 2단계는 이미 끝났으니 되돌리지 않는다.

### 4. 안내 메시지

브랜치명이 번호 기반이라 이름만으로는 무슨 작업인지 알 수 없다. **dev PR 제목을 같이 찍어** 디자이너가 자기
브랜치를 알아볼 수 있게 한다.

> design 브랜치 `{확정된 브랜치명}` 준비 완료 (dev PR #{번호} — {제목}).
> `{실행 대상}` 에 빌드를 올렸습니다. 현재 화면을 먼저 확인해주세요.
> 피그마에서 수정이 필요해지면 `/figma-apply <figma_link>` 를 실행해주세요.

1단계에서 프로젝트를 새로 클론했다면 위치만 알린다. **이후 작업은 이 세션에서 그대로 이어서 한다** — 디자이너가 폴더를 옮기거나 클로드를 다시 띄울 필요는 없다.

> (프로젝트를 `{PROJECT_DIR}` 에 받았고, 이후 작업도 이 프로젝트에서 이어서 진행합니다.)

2b를 거쳤다면 어느 쪽을 선택한 결과인지, 2c에서 패널을 띄웠다면 어디에 띄웠는지, 3b에서 에뮬레이터를 새로
만들었다면 그것도 한 줄 덧붙인다.

> (기존 `…/1234` 에서 이어서 진행합니다 — 이전 검수 커밋 3개가 그대로 있습니다.)
> (새로 시작을 선택하셔서 `…/1234-3` 을 만들었습니다.)
> (커밋 이력은 Android Studio 의 Git 도구 창에 띄워 뒀습니다 — `/figma-apply` 로 반영할 때마다 여기 쌓입니다.)
> (실행할 기기가 없어 resizable 에뮬레이터 `figma-qa-resizable` 을 새로 만들었습니다 — 폰·폴더블·태블릿을 이 하나로 전환해 볼 수 있습니다.)

<!--
Design-To-UI
Copyright (c) 2026-present NAVER Corp.
Apache-2.0
-->

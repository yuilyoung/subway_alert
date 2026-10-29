# CI/CD와 정적 분석

## 실행 흐름

PR 생성·수정과 모든 push에서 CI를 실행합니다. main 병합도 push이므로 같은 검사를 다시 실행합니다. 수동 CI도 가능하지만 CD는 성공한 **main push CI**만 승격합니다. 수동 CD와 저장소 opt-in으로 활성화한 승인형 자동 CD를 제공합니다.

| 검사 | 실패 조건 / 보존 산출물 |
| --- | --- |
| JavaScript ESLint | 권장 JS·React·Hooks 규칙 오류와 경고, `--max-warnings 0` |
| JavaScript Prettier | 앱 JS/JSX/JSON 포맷 차이 |
| Java Spotless·PMD | Java 포맷 및 명시한 결함·불필요 코드 규칙 위반, Maven verify에 연결 |
| Python Ruff | 배포·데이터 Python 코드 및 테스트 lint/format 위반 |
| Actions actionlint | workflow 문법·타입·표현식 검사, 다운로드 SHA-256 고정 |
| 앱·데이터 테스트 | Node 테스트, Python unittest, Expo Android JS export |
| 서버 | Maven 테스트, 실행 JAR 인증·제한·등록 복구 smoke, 독립 추적 엔진 검사 |
| PostgreSQL | CI 전용 실제 PostgreSQL에서 재시작·저장 장애 검사 |
| Docker | 동일 이미지로 실행·인증·제한·재시작, 배포 교체 실패·롤백 검사 |
| Android | 네이티브 lintRelease, JS 내장 ARM64 시험 APK 빌드·서명 검사 |
| CI gate | 모든 선행 작업이 success일 때만 성공; 실패·취소·skip이면 실패 |

최종 게이트는 정확한 6개 필수 검사 결과를 검증합니다. 빈 입력·누락·추가 검사·잘못된 형식도 실패하며 Actions Summary에 각 판정을 표시합니다. workflow 의존성과 같은 검사 집합을 유지하는 계약 테스트를 실행합니다.

CI는 포맷을 자동 수정하거나 오류를 무시하지 않습니다. 로컬에서 수정하고 다시 제출합니다. 생성 Android/Expo·node_modules·target 디렉터리는 소스 포맷 대상이 아닙니다. 이 구성은 취약점 전수 검사나 실기기 동작 보장을 뜻하지 않습니다.

읽기 전용 정적 검사 명령은 다음과 같습니다. Node 의존성·Maven·actionlint를 설치하고 Python 도구를 준비한 뒤 실행합니다. 기본 `all`은 static과 server 그룹을 모두 검사합니다.

```sh
npm ci --prefix mobile
python3 -m pip install -r requirements-quality.txt
python3 deploy/check_quality.py --negative-controls
mvn -f server/pom.xml verify
python3 -m unittest discover -s data/tests -v
```

`--group static`은 ESLint·Prettier·Ruff·actionlint, `--group server`는 Spotless·PMD만 검사합니다. `--maven`과 `--actionlint`로 설치한 실행 파일 경로를 지정할 수 있습니다. `--negative-controls`는 stdin·임시 디렉터리에 의도적인 오류를 넣고 정확한 진단과 종료 코드 1을 확인합니다. 실행 파일 누락·설정 오류는 정상 차단으로 간주하지 않습니다. 개발 소스는 바꾸지 않습니다.

포맷을 자동 수정하려는 경우에만 아래 명령을 별도로 실행하고 변경을 검토합니다.

```sh
npm run format --prefix mobile
mvn -f server/pom.xml spotless:apply
python3 -m ruff check --fix deploy data
python3 -m ruff format deploy data
```

## 산출물과 승격

| Artifact | 내용 | 보관 |
| --- | --- | --- |
| backend-release-소스SHA-attempt-회차 | 검증한 image.tar, manifest, 체크섬, staging Compose, 배포 도구 | 30일 |
| backend-jar-소스SHA-attempt-회차 | 실행 JAR | 14일 |
| server-reports-소스SHA-attempt-회차 | 테스트·PMD 결과 | 14일 |
| android-lint-소스SHA-attempt-회차 | 네이티브 Android lint 결과 | 14일 |
| backend-docker-smoke-실행번호-attempt-회차 | 비밀 없는 Docker·배포/롤백 검사 결과 | 14일 |
| subway-alert-test-arm64-실행번호-attempt-회차 | 내부 시험 APK, SHA256SUMS, 시험 빌드 안내 | 14일 |

재실행 산출물은 `github.run_attempt` 접미사로 구분하고 이전 회차를 덮어쓰지 않습니다. CD는 GitHub API로 확인한 최신 실행 회차의 배포 묶음만 선택합니다. 일부 job만 재실행해 최신 회차 배포 묶음이 없으면 이전 회차로 대체하지 않고 실패합니다. 배포를 준비하려면 전체 CI를 재실행하세요.

Docker 이미지는 한 번 빌드한 불변 image ID로 smoke 검사·저장·배포합니다. CD에서 재빌드하지 않습니다. manifest에 source SHA·CI run ID·image ID·파일 해시를 기록하며 다른 출처나 변조를 거절합니다. Artifact 자체의 자동 무결성 경고에 의존하지 않고 파일 해시를 명시적으로 검사합니다. 보관 기한이 지난 run은 다시 선택할 수 없으므로 새 main CI를 실행할 수 있는 변경을 제출해야 합니다. 장기 릴리스 보존은 별도 registry/release 정책이 필요합니다.

APK는 Expo가 생성한 Debug 키로 서명한 **내부 시험 파일**입니다. 정식 서명 AAB 생성·Google Play 업로드·심사는 아직 연결하지 않았습니다. Firebase 설정도 포함하지 않습니다.

## 관리자 설정: 실패한 CI의 병합 차단

workflow에 `CI gate`를 추가하는 것과 GitHub가 병합을 차단하는 것은 별도입니다. 현재 연결의 GitHub App에는 Administration 권한이 없어 보호 규칙을 적용하지 못했습니다. 관리자가 아래 설정을 적용해야 실제 병합 차단이 완성됩니다.

저장소 Settings → Branches → main 보호 규칙에서 PR 필수, 상태 검사 **CI gate** 필수, 최신 base 검사와 관리자 포함 적용을 켭니다. 기존 규칙이 생겼으면 먼저 병합 정책과 충돌 여부를 확인합니다. 현재 보호가 없는 저장소에 적용할 API 본문은 [branch-protection.main.json](../.github/branch-protection.main.json)입니다. 관리자 권한의 GitHub CLI에서 실행합니다.

```sh
gh api --method PUT repos/yuilyoung/subway_alert/branches/main/protection \
  --input .github/branch-protection.main.json
```

이 명령은 기존 보호 설정을 교체합니다. 현재 연결로 실행하거나 적용했다고 주장하지 않습니다. `CI gate`가 한 번 실행되어 검사 이름이 나타난 뒤 필수 검사로 지정하세요.

## staging 실행 환경 준비

실제 운영 서버·Tunnel·도메인은 생성하지 않습니다. 기존 Linux x86-64 호스트에 Docker Engine 28+, Compose v2, Python 3.10+, SSH를 준비합니다. 이 경로는 기본 로컬 daemon(`unix:///var/run/docker.sock`, context `default`)을 명시적으로 사용합니다. rootless 소켓이나 원격 Docker context는 별도 지원하지 않으며 사용자 저장 설정을 변경하지 않습니다. 공개 저장소의 PR 코드를 운영 호스트 자체 runner에서 실행하지 않습니다. GitHub 호스팅 runner가 SSH로 검증한 묶음만 전달합니다.

staging은 **SAMPLE·FCM 비활성·메모리 저장소** 전용입니다. PostgreSQL/Supabase·실제 FCM·서울 실키 배포는 이 경로에 포함되지 않습니다. 서버 교체 시 메모리 TEST 감시와 호출 예산은 초기화됩니다.

GitHub 계정 설정과 Linux 호스트 설정을 분리합니다. 아래 도구를 작성한 것과 실제 외부 설정을 적용한 것은 다릅니다. 현재 연결에는 GitHub Administration 권한이 없고 실제 호스트도 미정이므로 기본 plan만 실행했습니다.

### GitHub staging 환경

운영자 PC에 Python 3과 관리자 권한으로 인증한 GitHub CLI(`gh`)를 준비합니다. 토큰을 저장소나 대화창에 붙여 넣지 않습니다.

```sh
# 기본은 읽기 전용 계획: 인증/네트워크/변경 없음
python3 deploy/github_environment.py plan
# GitHub 관리자 인증 환경에서만 실제 설정 적용
python3 deploy/github_environment.py apply
python3 deploy/github_environment.py check
```

기본 승인자는 인증한 운영자입니다. `--reviewer GitHub로그인`으로 지정할 수 있습니다. 개인 저장소의 승인자가 스스로 배포를 시작하고 승인할 수 있도록 `prevent_self_review=false`를 사용합니다. 팀에서 자기 승인을 막으려면 별도 관리 정책으로 설정해야 하며 도구는 다른 기존 규칙을 덮어쓰지 않습니다. 관리자 설정 중 동시 편집을 피하세요. GitHub environment PUT은 원자적 create-only API가 아닙니다.

도구는 `staging`, main 배포 제한, required reviewer, environment 변수 `STAGING_DEPLOY_ENABLED=false`, **저장소 변수** `STAGING_AUTO_DEPLOY=false`를 준비하고 재검사합니다. 기존 true 값·다른 보호 규칙은 바꾸지 않고 충돌로 보고합니다. 기본은 수동/자동 모두 비활성입니다. `environment_prepared`와 `deployment_ready`를 구분하며 secret 이름이 있어도 실제 SSH 연결을 검증했다고 표시하지 않습니다. 이 도구는 secret 값을 읽거나 업로드하지 않습니다.

### Linux/Docker 호스트

전용 SSH 사용자가 소유하는 `/srv/subway-alert`를 준비합니다. 해당 상위 디렉터리에 쓰기 권한이 없으면 호스트 관리자가 먼저 디렉터리 소유권을 설정해야 합니다. 그 사용자의 계정으로 실행합니다.

```sh
python3 deploy/host_init.py init --root /srv/subway-alert --check-engine
python3 deploy/host_init.py check --root /srv/subway-alert --check-engine
```

도구는 root 디렉터리와 incoming/configs/releases를 0700, 새 .env를 0600으로 만듭니다. .env는 BACKEND_PORT와 단일 SUBWAY_API_TOKENS만 포함하며 키를 출력하지 않습니다. 재실행은 기존 값을 보존하고, 링크·소유자/권한 오류·다른 포트 요청은 거절합니다. 다른 포트는 init/check 모두 `--port 값`을 지정합니다. 패키지 설치·sudo·Docker 그룹·방화벽 변경은 수행하지 않습니다. SSH 계정의 Docker 접근은 호스트의 강한 권한이므로 배포 전용 계정으로 관리합니다.

### 자격 증명과 활성화

아래 다섯 값을 GitHub staging environment secrets에 설정합니다. 개인 키는 예를 들어 `gh secret set STAGING_SSH_PRIVATE_KEY --env staging --repo yuilyoung/subway_alert < 비공개키파일`처럼 표준 입력으로 전달하고 인자·로그에 키를 넣지 않습니다. SSH host key는 운영자가 별도 안전한 경로로 확인해 고정하며, 접속 중 ssh-keyscan으로 자동 신뢰하지 않습니다.

| Secret | 값 |
| --- | --- |
| STAGING_SSH_HOST | DNS 이름 또는 IPv4 |
| STAGING_SSH_PORT | SSH 포트, 보통 22 |
| STAGING_SSH_USER | 전용 Linux 사용자 |
| STAGING_SSH_PRIVATE_KEY | 해당 사용자의 배포 전용 비대화식 개인 키 |
| STAGING_SSH_KNOWN_HOSTS | 검증한 known_hosts 한 줄 이상; 비표준 포트는 `[호스트]:포트` 형식 |

호스트·SSH·승인 규칙을 검증한 후 environment 변수 `STAGING_DEPLOY_ENABLED=true`를 설정합니다. 이 단계는 도구가 자동 수행하지 않습니다.

Actions → **Deploy staging** → Run workflow에서 main을 선택하고 성공한 main push CI run ID를 입력합니다. PR run, 수동 CI run, 실패·취소·미완료 run, 다른 workflow·저장소는 거절합니다. 아직 CI/CD 변경이 main에 병합되지 않았거나 main 성공 산출물이 없으면 실행할 수 없습니다.

자동 배포를 원하면 추가로 **저장소 변수** `STAGING_AUTO_DEPLOY=true`를 설정합니다. environment 변수는 verify-source job의 사전 조건에서 사용할 수 없으므로 자동 배포 스위치를 environment에 두면 안 됩니다. main push CI 성공 → 출처/최신 회차 검사 → staging 승인 → 배포 순서입니다. PR·실패·취소·다른 저장소·다른 workflow는 거절합니다. 자동 배포는 승인 전과 실제 전달 직전에 source가 현재 main HEAD인지 확인해 오래된 CI가 새 버전을 덮어쓰지 않게 합니다. 수동 실행은 운영자가 명시적으로 고른 성공한 main CI를 사용합니다.

SSH 전송은 `deploy/ssh_deploy.py`로 실행하며 bundle·host·사용자·포트·실제 host pin을 먼저 검사합니다. 검증한 다섯 파일만 고정 경로 `/srv/subway-alert/incoming` 아래 임시 디렉터리로 전송합니다. 개인 키 파일은 임시 0600으로 만들고 외부 stdout/stderr는 공개하지 않습니다. 고정 단계·상태만 담는 결과는 CD Artifact로 14일 보관합니다. 네트워크 단절·취소·timeout이면 원격 작업 완료 여부가 불명확할 수 있으므로 호스트 상태/배포 잠금을 확인한 뒤 재시도합니다.

CD는 manifest·체크섬·loaded image ID를 확인하고 이전 릴리스를 보존합니다. 이전 컨테이너를 중지하고 후보를 시작한 뒤 이미지 ID·컨테이너 health·인증·감시 저장소 경로를 검사합니다. 실패하면 이전 이미지와 설정으로 복원하고 복원도 검사합니다. 자동 복구에 성공하더라도 원래 배포 작업은 실패입니다. 첫 배포 실패는 성공 상태로 기록하지 않습니다.

`/api/health`는 프로세스 생존 확인일 뿐입니다. 인증된 `/api/lines`와 임의의 미등록 UUID 감시 조회 404를 추가 검사합니다. 이 조회는 새 감시·FCM 전송·서울 조회를 만들지 않습니다. 실제 기기 수신·도메인·외부 HTTPS 경로는 검증하지 않습니다. 모든 stderr와 컨테이너 로그를 공개하지 않으므로 실패 시 운영자는 호스트의 비공개 상태와 설정을 확인해야 합니다.

## 외부 설정이 필요한 항목

코드와 CI 실행 결과, 관리자 설정 적용, 실제 서버 배포를 구분합니다. main 보호·environment 승인 규칙은 관리자 적용 전이며 SSH 호스트·키도 미설정입니다. 운영용 사용자 인증·분산 쿼터·백업 복구·모니터링·실기기 GPS/Doze/권한·서울 실키·Firebase 수신·정식 Android 서명과 스토어 게시 역시 후속 조건입니다. 설계 PDF는 비공개 이전 버전이며 이 저장소의 Markdown 설계가 최신 구현 기준입니다.

JavaScript 도구는 React lint 플러그인의 지원 범위에 맞춰 ESLint 9를 고정했습니다. 현재 설치 시 upstream EOL 안내가 있으므로 플러그인의 차기 major 지원과 함께 ESLint 업그레이드를 추적해야 합니다. 검사 경고를 통과시키는 옵션으로 숨기지는 않았습니다.

## CI 안에서 실제 SSH 전송 검사

Docker job은 검증한 bundle을 사용해 임시 loopback SSH 서버·키·고정 host pin을 만들고 실제 ssh/scp 전송과 Docker 기동을 검사합니다. SSH 데몬은 loopback만 수신하고 외부 서버·계정에 접속하지 않습니다. `deploy/smoke_ssh.py`는 명시적 `--allow-ci-host-test`와 비어 있는 전용 테스트 root를 요구합니다. 서비스·키·프로젝트 정리를 검사하고 실제 호스팅 배포의 증거로 사용하지 않습니다. 로컬 작업 환경에는 Docker 엔진/SSHD가 없으므로 이 통합 실행은 GitHub Actions에서 검증합니다.

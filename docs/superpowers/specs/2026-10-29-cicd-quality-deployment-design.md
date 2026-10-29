# CI 품질 게이트와 배포 준비 설계

## 목적과 선택

PR과 모든 push에서 formatter, lint, 테스트, Android/Docker 빌드를 검사하고 성공한 동일 Docker 이미지를 배포 가능한 묶음으로 보존한다. main의 성공한 CI만 수동 staging CD 입력으로 허용한다. 기존 Expo/Java 17/Python 표준 라이브러리 구조를 유지한다.

GitHub Actions를 확장한다. 별도 Jenkins는 운영 부담이 크고, 공개 저장소의 자체 호스팅 runner는 PR 코드와 운영 호스트의 격리가 어렵다. 따라서 GitHub 호스팅 runner에서 검증하고 선택된 Linux 호스트에는 SSH로 전달하는 방식을 채택한다. 서버 업체와 비용은 이번 작업에서 선택하거나 생성하지 않는다.

## 품질 검사

- 앱: 고정 버전 ESLint(권장 JavaScript 및 React Hooks 규칙), Prettier. 경고도 실패한다. 생성 Android/Expo 출력과 node_modules는 제외한다.
- Java: Maven verify에 Spotless와 PMD 검사를 연결한다. Java 17을 유지하고 기존 소스에 formatter를 적용한다. 포괄적인 suppress/baseline으로 문제를 숨기지 않는다.
- Python: 고정 버전 Ruff lint/format check, 배포·데이터 코드 및 테스트 포함.
- Actions: actionlint로 workflow 문법·표현식·참조를 검사한다.
- 최종 `CI gate` 작업은 정적 분석과 모든 기존 테스트/산출물 작업의 성공을 요구한다. 실패·취소·건너뛰기를 성공으로 인정하지 않는다.

## 배포 산출물과 CD

배포 묶음에는 source SHA, CI run ID, Docker image ID, 파일별 SHA-256을 기록한 manifest, 검증한 이미지 tar, staging Compose와 실행 도구를 포함한다. CI에서 새 이미지를 한 번 빌드하고 그 이미지를 smoke 검사 및 배포 준비 검사에 사용한다. JAR·테스트 결과·시험 APK도 보존한다. 내부 시험 APK는 debug 서명이며 정식 Play AAB가 아니다.

수동 CD는 입력 run ID가 이 저장소 CI workflow의 성공한 main push인지 API로 확인한다. 임의 PR, 실패한 CI, 다른 저장소·workflow의 산출물은 거절한다. 실행 코드와 다운로드한 묶음의 source SHA 및 해시를 확인한다. staging environment 설정과 호스트 키 고정, SSH 비밀이 없으면 배포하지 않고 실패한다. SSH 대상·경로는 검증하고 비밀을 로그에 출력하지 않는다.

기본 배포 범위는 SAMPLE, FCM 비활성, 단일 인스턴스 staging이다. 기존 PostgreSQL의 singleton lock 때문에 두 백엔드를 동시에 띄우지 않는다. 기존 이미지와 설정을 보존한 후 교체하고, 컨테이너 health 및 인증·감시 저장소 경로를 검사한다. 실패 시 이전 이미지로 복구하고 복구 결과를 검사한다. `/api/health`만으로 DB·FCM·서울 API 준비 완료라고 판단하지 않는다. 실제 서울 API/FCM/운영 DB 연결과 Play 게시에는 별도 검증이 필요하다.

## 외부 설정과 완료 판정

main required status checks와 staging environment 승인 규칙은 관리자 API 권한이 필요하다. 현재 연결에 권한이 없으면 설정 예제와 정확한 절차를 제공하고 미적용임을 표시한다. 운영 호스트·SSH·도메인·Play 서명 키는 미정이므로 코드 완성과 실제 운영 배포를 구분한다. GitHub에 브랜치/PR을 올리고 실제 CI 결과와 테스트 수를 보고한다. 기존 PR #6/#7은 임의 병합하지 않는다.

# Docker 실행 검증 계획

Spec: `docs/superpowers/specs/2026-10-28-docker-runtime-design.md`

1. 배포 도구: JAR smoke HTTP 검사를 재사용 가능한 함수로 추출한다. Compose 런타임의 잘못된 사용자·공개 포트·쓰기 가능한 rootfs·누락 권한 제한·정리 실패를 검출하는 테스트를 먼저 실패시킨 뒤 새 runner를 구현한다. Python 전체 테스트 및 기존 실행 JAR 검사를 통과한다.
2. CI: 기존 서버·앱 검사를 유지하고 Docker 이미지/컨테이너 통합 작업과 안전한 보고서 Artifact를 추가한다. YAML·셸 문법 및 Compose 해석을 검증한다.
3. 문서: 실제 명령, 격리·키·정리 동작, CI #17 성공 기록과 외부 서비스 미완료를 갱신한다. 새 Docker 결과는 검증 전까지 대기 상태로 둔다.
4. 실행: 독립 리뷰·로컬 검증 후 PR #3 기반 별도 PR로 올리고 원격 Docker 작업을 실행한다. 실패는 로그로 원인을 확인해 수정하고 다시 실행한다. 실제 Docker 작업 결과와 한계를 최종 보고한다.

공유 인터페이스는 `deploy/smoke_compose.py --report artifacts/docker-smoke.json`이며 키가 없는 상태와 있는 상태를 모두 검사한다. 보고서는 비밀 없는 판정값만 담고 성공/실패·cleanup 상태를 구분한다. 테스트용 가짜 Docker 응답은 실제 엔진 실행 증거로 취급하지 않는다.

리뷰 중점: 기존 프로젝트에 영향 없는 정리, subprocess 오류의 키 노출, 상속한 환경변수의 간섭, 포트/health 검사 누락, 실패에도 success 보고하는 경로, 실제 CI와 로컬 가짜 응답의 구분.

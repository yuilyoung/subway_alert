# CD Environment Implementation Plan

**Goal:** Linux staging 준비·전송·GitHub 환경 설정을 실행 도구로 제공하고 승인형 CD에 연결한다.

**Spec:** docs/superpowers/specs/2026-10-29-cd-environment-design.md

**Global constraints:** 실제 호스트/계정 미확정, 유료 자원·main merge·공개 Tunnel 생성 금지. 기존 release.py lifecycle 재사용. 비밀·raw 외부 오류 출력 금지. 미적용 외부 설정은 명시한다.

### Task 1 — Host initialization

Files: deploy/host_init.py, data/tests/test_host_init.py.
Interface: `python3 deploy/host_init.py init|check --root PATH [--port 8080] [--check-engine]`.

- [ ] TDD: 새 디렉터리/권한·키 생성, 재실행 비변경, 링크·기존 잘못된 파일/권한·잘못된 포트 거절, 실패 정리.
- [ ] 기존 release.py config/engine 검사 재사용, sudo/설치/기존 설정 변경 없음.
- [ ] 전체 Python 테스트·Ruff 검증.

### Task 2 — SSH transport

Files: deploy/ssh_deploy.py, data/tests/test_ssh_deploy.py.
Interface: `python3 deploy/ssh_deploy.py --bundle DIR --source-sha SHA --run-id ID [--report PATH]`, 기존 SSH_* 환경 사용.

- [ ] TDD: 입력/bundle/host pin 검사 전에는 접속하지 않음, StrictHostKeyChecking, 정상 전송/배포, 단계별 실패·timeout·임시 비밀 정리.
- [ ] 외부 SSH 경계를 대체한 테스트와 실제 파일/인자 검사. 실제 호스트 접속과 구분.
- [ ] 기존 cd.yml inline SSH를 이 도구로 교체.

### Task 3 — GitHub staging settings

Files: deploy/github_environment.py, data/tests/test_github_environment.py.
Interface: `python3 deploy/github_environment.py plan|apply|check [--reviewer LOGIN]` (고정 yuilyoung/subway_alert, staging, main).

- [ ] TDD: plan은 외부 변경 없음; 관리자/리뷰어/main 제한·비활성 상태 검증; 기존 다른 환경 규칙은 변경하지 않음.
- [ ] gh API 입력은 구조화 JSON stdin. 값/토큰·raw 오류 출력 없음. 설정 충돌은 fail-closed.
- [ ] 실제 권한/인증이 없는 환경에서 적용했다고 주장하지 않음.

### Task 4 — CD workflow and docs

Files: .github/workflows/cd.yml, docs/cicd.md, docs/deployment.md, README.md.

- [ ] workflow_run의 성공한 main push + repository opt-in과 수동 실행을 같은 provenance 경로로 연결.
- [ ] env 승인/비활성 기본값·secret 준비·호스트 명령·실제 적용 절차 문서화.
- [ ] actionlint·전체 테스트·독립 리뷰·푸시·실제 CI 검증.
- [ ] 외부 실제 적용에 필요한 서버/호스팅 연결과 GitHub 관리자 설정을 정확히 보고.

# CD 실행 환경 구성

## 목표와 선택

검증한 CI 산출물을 Linux/Docker staging에 전달하는 기존 설계를 완성한다. 새 호스팅을 임의 생성하거나 비용을 발생시키지 않는다. 기존 서버 정보가 없으므로 기본은 기존 Linux/SSH 경로를 유지하며, Render 등 서비스 전환은 계정 연결과 사용 조건 확정 후 별도 진행한다.

기존 release.py의 이미지·manifest 검증, 단일 인스턴스 교체, readiness, rollback을 재사용한다. 이를 다시 구현하지 않는다. 서버 초기화, SSH 전송, GitHub environment 준비를 독립 도구로 만든다. 원격 Linux 주소/계정/키, 관리자 GitHub CLI 인증은 실제 적용 시 필요한 외부 입력이다.

## 요구사항

- 호스트 초기화는 POSIX 일반 사용자 소유의 staging 디렉터리와 0600 .env를 안전하게 생성한다. 기존 파일·링크·잘못된 권한을 덮어쓰거나 chmod하지 않는다. 키는 출력하지 않는다. 패키지 설치·sudo·Docker 그룹 변경·방화벽 변경을 하지 않는다. 기존 환경의 검사도 제공한다.
- SSH 배포는 검증한 bundle만 전송하며 서버 경로는 /srv/subway-alert로 고정한다. DNS/IPv4·사용자·포트·source SHA·run ID를 검증한다. 호스트 키는 별도 검증한 known_hosts를 사용하고 StrictHostKeyChecking을 끄지 않는다. 개인 키는 임시 0600 파일로만 제공하고 항상 정리한다. 외부 프로그램 오류나 원격 stdout의 비밀을 로그에 내보내지 않는다.
- GitHub 환경 도구는 기본 plan/read-only이다. 관리자 권한의 gh로 staging environment·main 배포 제한·승인자·비활성 변수를 준비한다. 기존 환경/보호 규칙을 덮어쓰지 않는다. 비밀 값을 인자나 결과에 출력하지 않는다. 기본은 수동/자동 배포 모두 비활성이다. 설정 적용과 실제 적용 검사를 구분한다.
- CD는 수동 실행과 선택형 자동 실행을 제공한다. 자동 실행은 main push의 CI 성공과 저장소 STAGING_AUTO_DEPLOY=true를 요구한다. PR/실패/다른 출처는 거절하고 default-branch의 신뢰한 코드로 처리한다. staging 승인과 STAGING_DEPLOY_ENABLED=true도 필요하다. 해당 설정이 없다고 자동 활성화하지 않는다.
- SAMPLE·FCM 비활성·메모리 staging, 동일 이미지, 최신 attempt 선택, 체크섬, readiness/rollback 경계는 유지한다.
- 실제 Linux/SSH 배포나 GitHub 관리자 설정을 수행하지 못한 경우, 준비 코드와 CI 검증을 실제 외부 적용으로 표현하지 않는다. main 병합도 임의 수행하지 않는다.

## Docker 대상 일치

Linux SSH 배포, 호스트 engine 검사와 CI loopback smoke는 context default와 unix:///var/run/docker.sock을 명시해 같은 로컬 daemon만 사용한다. 운영자 HOME/currentContext나 DOCKER_CONFIG/TLS 설정으로 대상이 바뀌지 않아야 하며, 검사 뒤 부모 환경을 복원한다. 저장된 Docker 설정 파일은 수정하지 않는다. rootless/원격 Docker context 지원은 범위 밖이다.

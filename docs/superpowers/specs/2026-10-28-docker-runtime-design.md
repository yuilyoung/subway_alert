# Docker 실행 검증

목적은 문법 검사에 그쳤던 Docker 배포 구성을 실제 이미지·컨테이너로 검증하는 것이다. PR #3의 API 보호 구현 위에서 별도 `feat/docker-runtime-check` 브랜치로 진행한다. 공개 서버·Tunnel·Firebase·DB·Play를 생성하지 않는다.

현재 작업 환경에는 Docker/Podman 엔진이 없다. 따라서 로컬에서는 검증 도구의 실패 경로·런타임 설정 판정·구성 해석을 테스트하고, 실제 Docker 실행은 기존 GitHub Actions의 별도 Ubuntu 작업으로 수행한다. 결과를 섞어 보고하지 않는다.

## 구현 계약

- `python3 deploy/smoke_compose.py --report <path>`: 저장소 Dockerfile을 빌드하고 같은 Compose 백엔드를 독립 시험 프로젝트로 시작한다. 무작위 프로젝트·이미지 태그, 비어 있는 루프백 포트와 임시 키만 사용한다. 기존 `.env`, 개발 컨테이너, 기존 이미지 태그를 수정하거나 삭제하지 않는다.
- 키 미설정 상태에서 실제 healthcheck healthy·health 200·보호 API 503을 확인한다. 무작위 키를 적용해 재생성한 후 누락/오류/중복 헤더 401·정상 200·생성/버스트 429를 확인한다. 기존 JAR smoke의 HTTP 검사를 공통 함수로 재사용한다. 서울 API나 FCM 호출은 하지 않는다.
- 실제 컨테이너의 UID 10001, read-only rootfs, cap_drop ALL, no-new-privileges, /tmp tmpfs, 127.0.0.1 포트 바인딩, sample·FCM false와 healthcheck를 확인한다. 재시작 후 health와 인증이 돌아오는지 확인한다. 영속 저장이나 실제 알림을 보장하지 않는다.
- 성공/실패 모두 자신이 만든 프로젝트만 down하고, 정리 실패는 성공으로 보고하지 않는다. 키·환경변수·전체 inspect/config/로그는 공개 출력이나 산출물에 넣지 않는다. 오류는 비밀을 포함하지 않는 단계 이름으로 표시한다. 판정 결과만 JSON 보고서로 저장한다.
- CI는 25분 제한의 별도 Docker 작업에서 이 도구를 실행하고, 비밀 없는 보고서만 Artifact로 14일 보관한다. Docker 도구·이미지 빌드 실패를 건너뛰거나 성공으로 바꾸지 않는다.

실제 CI 결과가 확인될 때까지 Docker 실행 성공이라고 쓰지 않는다. 도메인·제공 업체·실키·Firebase Android 설정이 필요한 단계는 그대로 미완료다. PR #3을 자동 병합하지 않고 그 브랜치를 대상으로 후속 PR을 만든다.

# Docker 실행 검증 기록

기준일: 2026-10-28 (한국 시간). `feat/docker-runtime-check`는 아직 병합되지 않은 접근 보호 PR #3의 `feat/private-api-access`를 기반으로 하며 `main` 배포 완료를 뜻하지 않습니다. Markdown 설계 v1.2가 기준이고 PDF v1.1은 이번 작업에서 갱신하지 않습니다.

## 증거와 현재 상태

| 검증 | 결과 | 범위와 한계 |
| --- | --- | --- |
| 앞선 접근 보호 CI #17 | [전체 3개 작업 성공](https://github.com/yuilyoung/subway_alert/actions/runs/40525199870), 독립 ARM64 시험 APK 생성 성공 | 서버 52개·모바일 35개·Python 12개 및 실행 JAR 검사 기록. 새 Docker 작업은 포함되지 않음 |
| 이번 검사기 로컬 테스트 | Python 전체 26개 통과 (기존 12개 + Docker 검사기 14개) | 가짜 Docker 응답·임시 fixture로 실패 경로와 런타임 설정 판정을 검사. 실제 엔진 실행 증거가 아님 |
| 공유 HTTP 검사 회귀 확인 | 패키징된 JAR에서 health 200·미설정 503·누락/오류/중복 키 401·정상 200·생성/버스트 429 통과 | 실제 Java 프로세스, Docker 아님. 외부 API 호출 없음 |
| 엔진 없는 로컬 실행 | 종료 코드 1, `engine` 실패 보고서와 cleanup not-needed 확인 | 엔진 누락을 성공·건너뜀으로 처리하지 않음 |
| 실제 Docker CI #20 | [Docker 작업 성공](https://github.com/yuilyoung/subway_alert/actions/runs/40530621386/job/122282085504), [JSON Artifact](https://github.com/yuilyoung/subway_alert/actions/runs/40530621386/artifacts/12747270127) 확인 | 검증 소스 a6ad0de, 실제 이미지·컨테이너·인증·호출 제한·재시작·프로젝트/이미지 정리 통과. Android 기기·외부 서비스 검증 아님 |

실제 실행 환경은 GitHub Ubuntu 24.04.5 runner, Docker Engine 28.0.4, Compose 2.38.2, Python 3.12.3입니다. 내려받은 JSON은 status passed, failures 빈 배열, cleanup의 project/image 모두 passed였습니다. 현재 로컬 작업 환경에는 Docker/Podman 엔진이 없어 개발 PC 재현은 별도로 남아 있습니다. 서버·모바일 테스트나 `compose config` 성공을 컨테이너 실행 성공과 합치지 않습니다. 이전 결과의 상세 내역은 [접근 보호·배포 구성 기록](verification-deployment.md)에 있습니다.

독립 리뷰에서 발견한 실패 빌드 후 이미지 조회 오류를 “이미지 없음”으로 잘못 처리하는 경계는 실패 테스트로 재현한 뒤 수정했습니다. Docker image ls의 성공/빈 결과와 조회 실패를 구분하며 조회 오류는 cleanup 실패로 남깁니다. 이 회귀 검사를 포함해 로컬 전체 26개를 통과했습니다. 해당 보완의 최신 원격 CI는 PR에서 확인합니다.

## 재현 명령과 확인 항목

Python 3·POSIX 환경, Docker Engine 28 이상, `up --wait`를 지원하는 Docker Compose v2 이상이 필요합니다. 저장소 루트에서 실행합니다.

```sh
python3 deploy/smoke_compose.py --report artifacts/docker-smoke.json
```

- 저장소 Dockerfile로 고유 태그의 이미지를 빌드하고 고유 Compose 프로젝트를 시작합니다. 기존 `.env`·기본 프로젝트·`subway-alert-backend:local` 태그는 변경하지 않습니다. 임시 키와 비어 있는 `127.0.0.1` IPv4 포트를 사용합니다.
- 키 미설정 상태에서 실제 healthcheck healthy·health 200·보호 API 503을 확인합니다. 임시 키 적용 후 누락/오류/중복 헤더 401·정상 200·생성 및 버스트 한도 429를 검사합니다. 기존 실행 JAR smoke와 HTTP 검사를 공유합니다.
- 이미지 healthcheck와 런타임 UID 10001·read-only rootfs·`cap_drop: ALL`·`no-new-privileges`·`/tmp` tmpfs·IPv4 루프백 게시·sample·FCM false를 검사합니다. 재시작 뒤 health·인증 복구도 확인합니다.
- 성공·실패 모두 자신이 만든 프로젝트만 `down`하고 정리 실패도 실패로 남깁니다. Docker 누락·이미지 빌드·시작 실패를 건너뛰거나 성공으로 바꾸지 않습니다.

JSON에는 비밀 없는 검사 판정과 성공/실패·정리 상태만 담습니다. 키·환경변수·전체 inspect/config·컨테이너 로그는 공개 출력과 보고서에 넣지 않습니다. CI는 25분 제한의 별도 Docker 작업에서 같은 검사를 실행하고 안전한 JSON만 Artifact로 14일 보관합니다.

## 검증하지 않는 범위

공개 Tunnel 연결, Firebase 자격 증명·실제 Android 설치와 FCM 수신, 서울 실키 HTTPS·실제 하차 판단, VPS·DB·Play 생성/배포는 수행하지 않습니다. sample과 FCM 비활성 상태에서 서울 API·FCM을 호출하지 않습니다. 재시작 확인은 메모리 세션과 쿼터의 영속성·운영 복구를 보장하지 않습니다. 일반 사용자 인증·영속/분산 쿼터와 실제 기기 검증은 남아 있습니다.

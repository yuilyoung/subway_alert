# 백엔드 실행과 Android 배포

## 역할과 선택

| 항목 | 이번 개발 기준 | 실제 상태 |
| --- | --- | --- |
| 개발 백엔드 | 개발자 PC의 Docker Compose에서 Spring Boot 실행 | CI #20의 이미지·컨테이너·인증·재시작·정리 통과, 개발 PC 재현 미실시 |
| 개발 HTTPS 진입점 | 같은 PC의 Cloudflare named Tunnel | 비활성 예제만 작성, 계정·도메인·터널 미생성 |
| 베타·운영 백엔드 | 상시 실행 Linux 서버에서 같은 Docker 이미지 실행 | 서버 업체·요금·지역 미선정, 실제 배포 없음 |
| 데이터베이스 | 선택형 로컬 PostgreSQL / 운영 Supabase 목표 | TEST 기록 JDBC 저장, Supabase 프로젝트 미확정·미연결 |
| 알림 | Firebase Cloud Messaging | TEST 전송 코드, 실제 자격 증명·기기 수신 미검증 |
| Android 빌드 | Expo/Gradle로 APK 또는 AAB 생성 | 테스트 APK만 생성·검증 |
| Android 정식 배포 | Google Play Console/Play 스토어 | 계정·서명·테스트 트랙·심사·출시 미완료 |

Cloudflare Tunnel은 외부 HTTPS 요청을 PC 또는 운영 서버의 Spring Boot로 전달하는 연결 수단입니다. Java 서버를 대신 실행하거나 DB를 제공하지 않습니다. PC가 꺼지거나 절전 상태가 되면 해당 PC의 서버와 터널도 사용할 수 없습니다. 운영 서버는 유료 자원 선택과 운영 조건을 확인하기 전까지 자동 생성하지 않습니다.

Android 앱은 웹앱처럼 Cloudflare에 올려 실행하는 것이 아닙니다. 기기에 설치되는 APK는 직접 테스트할 수 있고, 정식 배포는 서명한 AAB를 Google Play Console에 제출하는 방식입니다. 앱과 통신하는 백엔드는 별도로 계속 실행되어야 합니다. CI는 빌드·테스트 자동화이며 앱 스토어나 백엔드 호스팅을 대신하지 않습니다.

## 로컬 백엔드 실행

Docker Engine 28 이상과 `up --wait`를 지원하는 Docker Compose 플러그인(v2 이상)을 준비합니다. 오래된 Docker에는 localhost 게시 포트가 같은 네트워크에서 접근될 수 있는 제약이 있으므로 최신 엔진을 사용합니다. 명령은 저장소 루트에서 실행합니다.

```sh
python3 deploy/generate_api_tokens.py --output .env
docker compose --env-file .env config --quiet
docker compose --env-file .env up --build --wait --wait-timeout 180 backend
docker compose ps
curl --fail http://127.0.0.1:8080/api/health
docker compose down
```

Python 3 생성 도구는 기본 키 1개, `--count 2`처럼 1~20개의 참가자별 키를 지원합니다. 키마다 `secrets.token_urlsafe(32)`로 43자 base64url 값을 생성합니다. 기존 파일이나 심볼릭 링크를 덮어쓰지 않고 `O_EXCL`로 독점 생성하며 파일 권한을 0600으로 설정합니다. 성공 출력은 파일 경로뿐입니다. POSIX 파일 권한을 지원하는 환경에서 실행하고, 운영자는 파일을 비공개 편집기에서 열어 참가자마다 다른 키를 안전하게 전달합니다. 생성된 `.env`는 Git에서 제외되며 `BACKEND_PORT=8080`, `SUBWAY_API_TOKENS=<쉼표 구분 키 목록>`을 담습니다. 예제 파일에는 실제 키가 없고 키 설정은 비어 있습니다.

포트를 바꾸려면 생성한 `.env`의 `BACKEND_PORT`를 변경하고 같은 `--env-file` 경로를 사용합니다. 컨테이너는 내부에서 `0.0.0.0:8080`을 수신하지만 호스트 게시 포트는 `127.0.0.1`에만 연결됩니다. 다른 기기 또는 인터넷에 직접 열지 않습니다. 로컬 healthcheck는 정확히 `GET /api/health` 응답 확인이며 서울 API·Firebase·DB·실제 알림의 정상 동작을 증명하지 않습니다. `docker compose config`의 전체 출력에는 환경변수 비밀이 포함될 수 있으므로 검증은 `config --quiet`로 하고 환경 파일·Authorization 헤더를 로그나 보고서에 남기지 않습니다.

Dockerfile은 Maven에서 테스트와 패키징을 수행한 뒤 JRE 이미지에서 UID 10001의 일반 사용자로 실행합니다. 런타임 파일 시스템은 읽기 전용이고 임시 파일은 제한된 `/tmp`를 사용합니다. 현재 이미지 태그는 주요 런타임 버전을 지정한 태그이며 불변 digest로 고정되지는 않았습니다. 운영 릴리스 전에 실제 빌드 검증과 함께 승인한 이미지 digest 및 취약점 검사를 기록해야 합니다.

로컬 Compose는 공개 `sample` 키만 사용하고 FCM을 끕니다. Firebase 서비스 계정 키나 실제 서울 API 키를 이미지, Git, 앱 또는 `.env.example`에 넣지 않습니다. FCM 시험은 [서버 설정](../server/README.md)의 운영자 설정을 별도로 준비한 뒤 비밀 저장소나 읽기 전용 자격 증명 마운트를 사용하도록 확장해야 합니다. 현재 Compose에 해당 설정은 자동 포함되지 않습니다.

## 독립 Docker 실행 검사

실행 검증은 위의 개발용 `.env`를 만들거나 기본 프로젝트를 시작하지 않고도 수행할 수 있습니다. 같은 Docker 요구 사항과 Python 3·POSIX 환경에서 저장소 루트의 다음 명령을 사용합니다.

```sh
python3 deploy/smoke_compose.py --report artifacts/docker-smoke.json
```

검사기는 저장소 Dockerfile을 고유 이미지 태그로 빌드하고, 고유 Compose 프로젝트·임시 키·비어 있는 IPv4 루프백 포트를 사용합니다. 기존 `.env`, 개발 컨테이너와 기본 `subway-alert-backend:local` 태그는 변경하지 않습니다. 시작 시 Compose의 `--wait`와 실제 healthcheck를 기다립니다.

키 미설정 상태의 health 200·보호 API 503, 키 적용 뒤 누락·오류·중복 헤더 401·정상 요청 200·생성/버스트 제한 429를 확인합니다. 이미지 healthcheck, 런타임 UID 10001, read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, `/tmp` tmpfs, `127.0.0.1` 포트 게시, sample·FCM 비활성 구성도 검사합니다. 재시작 후 health와 인증이 돌아오는지 확인하되 메모리 세션·호출 예산의 영속성을 보장하지 않습니다. 서울 API나 FCM은 호출하지 않습니다.

성공·실패 모두 검사 프로젝트만 `down`하며 정리 실패를 성공으로 처리하지 않습니다. JSON 보고서는 비밀 없는 판정만 담습니다. 키·환경변수·전체 inspect/config·컨테이너 로그는 공개 출력이나 보고서에 넣지 않습니다. Docker가 없거나 빌드·시작·검사에 실패하면 건너뛰지 않고 실패합니다. CI의 별도 Docker 작업도 같은 명령을 실행하며 보고서는 Artifact로 14일 보관합니다. 최신 결과는 [Docker 검증 기록](verification-docker.md)을 확인하세요.

## 개발 기기 접근 키와 호출 예산

`SUBWAY_API_TOKENS`는 최대 20개의 쉼표 구분 키를 받으며 각 키는 32~128자 base64url 문자입니다. 키가 비어 있으면 정확히 `GET /api/health`를 제외한 모든 경로를 503으로 닫고, 잘못된 구성은 비밀값을 포함하지 않는 오류로 서버 시작에 실패합니다. 구성한 뒤에는 모든 보호 요청에 `Authorization: Bearer <key>`가 필요합니다. 키가 없거나 틀리거나 헤더가 중복·잘못되면 401입니다. localhost나 프록시 헤더에 따른 우회는 없습니다. 기존 세션 조회·취소·시험 전송에는 `X-Session-Token`도 필요합니다.

| 범위 | 단일 프로세스 기본 한도 |
| --- | --- |
| 인증 전 전체 보호 요청 | 600회/분 |
| 인증한 기기 키별 요청 | 60회/분 |
| 세션 생성 | 기기 키별 3회/분 |
| 직접 열차 조회 | 모든 키 합계 6회/분, 서울 날짜 하루 240회 |
| TEST 감시 공유 폴링 | 별도 서울 날짜 하루 600회 |

분 한도는 token bucket으로 연속 보충됩니다. 요청 예산 초과는 429와 양의 정수 초 단위 `Retry-After`를 반환합니다. 직접 조회와 감시 폴링은 별도 예산이므로 외부 서울 API 요청은 sample 모드에서 합계 최대 840회/일/프로세스입니다. 예산은 메모리에 있어 서버 재시작 시 초기화됩니다. 세션 기록은 기본 메모리 모드에서 사라지고 선택형 PostgreSQL 모드에서는 종료 상태로 복원됩니다. 인스턴스를 늘리면 예산도 늘어나므로 운영 과금 상한이나 분산 쿼터가 아닙니다.

앱의 연결 화면에서 HTTPS origin과 전달받은 API 키를 입력·저장합니다. 키는 SecureStore에 보관하며 origin 변경 시 키를 비우고 이전 응답을 무효화합니다. 감시에는 등록 당시 origin·API 키·세션 토큰을 함께 저장해 주소가 바뀌어도 기존 비밀을 새 주소에 보내지 않습니다. 취소가 확인되기 전에는 기존 기록을 지우지 않습니다. Metro의 루프백·에뮬레이터 HTTP 개발 예외는 [모바일 안내](../mobile/README.md)에 한정합니다.

이 키는 신뢰한 개발 기기의 접근 수단이며 일반 사용자 로그인이나 FCM 기기 소유 증명이 아닙니다. 공용 키를 APK에 내장하지 않습니다. 회수할 키를 서버 목록에서 제거한 뒤 `docker compose --env-file .env up -d --force-recreate backend`로 새 환경을 적용합니다. 키 파일은 0600 권한을 유지하고, 유출 키는 새로 생성해 교체합니다. 회수 후 기존 감시 취소가 실패할 수 있으며 서버 세션은 최대 2시간 후 만료됩니다. 사용자 계정, 영속·분산 쿼터, JSON 크기·동시 작업 제한, 에지 DDoS 방어, 운영 DB·백업 복구 검증은 운영 전 후속 조건입니다.

직접 조회 240회는 클라이언트 요청의 허용 횟수입니다. 실키 LIVE 조회 한 번은 최대 5페이지의 서울 API 호출을 수행할 수 있어 외부 호출 840회 상한은 sample 모드에만 해당합니다. 실키의 통합 외부 호출 예산은 후속 구현이 필요합니다.

## Cloudflare Tunnel은 아직 활성화하지 않음

`deploy/cloudflared/config.disabled.example.yml`에는 실제 hostname route가 없고 마지막 `http_status:404` 규칙만 있습니다. 자격 증명 경로와 UUID도 예시입니다. Compose에 cloudflared 서비스가 없으며 실행·DNS 생성·계정 변경은 수행하지 않았습니다.

서버에는 이번 개발 기기 Bearer 인증과 프로세스 내 호출 제한이 있지만, 운영용 사용자 인증·Supabase 연결·분산 쿼터·에지 방어는 없습니다. 이번 구현만으로 인터넷 공개용 운영 보안이 완성되지는 않습니다. Quick Tunnel이나 public hostname은 이번 작업에서 실행하지 않습니다. 개발 연결 전에도 실제 인증 동작, 비밀 전달·회수, HTTPS hostname, 기기 접속 정책과 로그 비밀 노출 여부를 확인해야 합니다. Cloudflare 브라우저 로그인 정책만 설정했다고 Android 네이티브 API 인증이 자동 완성되는 것도 아닙니다.

그 조건이 준비된 뒤 운영자가 named Tunnel과 DNS를 별도로 구성하고, 같은 PC에서 실행하는 cloudflared의 origin을 `http://127.0.0.1:8080`으로 설정합니다. 외부 구간은 Cloudflare HTTPS이며 이 로컬 HTTP origin은 같은 PC 내부에 한정됩니다. cloudflared를 별도 컨테이너에 넣는 경우 그 컨테이너의 localhost는 백엔드가 아니므로 전용 네트워크의 서비스 주소로 다시 설계해야 합니다. 비활성 예제는 이 별도 컨테이너 방식을 구성하지 않습니다.

계정과 실제 경로가 준비된 환경에서만 다음 구문으로 ingress 문법을 검사할 수 있습니다. 이는 터널을 실행하거나 외부에서 접속 가능하게 만드는 명령이 아닙니다.

```sh
cloudflared tunnel --config deploy/cloudflared/config.disabled.example.yml ingress validate
```

## 검증 범위와 남은 일

현재 작업 환경에는 Docker/Podman 엔진과 cloudflared가 없습니다. 앞선 접근 보호 변경은 Compose 구성 해석과 실행 JAR 인증 검사를 거쳐 [CI #17](https://github.com/yuilyoung/subway_alert/actions/runs/40525199870)의 3개 작업·시험 APK 생성까지 성공했습니다. 이 실행에는 새 Docker 작업이 없으므로 이미지·컨테이너 검증의 증거로 사용하지 않습니다.

이번 Docker 검사기의 로컬 테스트는 가짜 Docker 응답으로 실패 경로와 판정을 검증하고, 실제 이미지 빌드·healthcheck·재시작·정리는 GitHub Actions의 별도 Docker 작업으로 검증합니다. 실행 결과는 [Docker 검증 기록](verification-docker.md)에 구분해서 남깁니다. [CI #20의 Docker 작업](https://github.com/yuilyoung/subway_alert/actions/runs/40530621386/job/122282085504)은 실제 이미지 빌드·기동·인증·호출 제한·재시작·정리를 통과했습니다. 이전 애플리케이션·키 생성·Compose 정적 검증은 [접근 보호 검증 기록](verification-deployment.md)에 있습니다.

Docker 검증 다음에는 Firebase 설정을 포함해 앱을 다시 빌드하고, 인증된 HTTPS 개발 경로에서 TEST 알림을 실기기로 검증해야 합니다. 실제 하차 알림은 서울 실키 HTTPS·경로·시간대·운행 예외를 확인하기 전까지 차단 상태로 유지합니다. 운영 전에는 Supabase 운영 연결·백업 복구·모니터링·사용자 인증·분산 쿼터·전송 정책·권한 정리가 추가로 필요합니다. 이번 작업은 Tunnel·Firebase·VPS·클라우드 DB·Play 자원을 생성하지 않습니다. 선택형 로컬 DB의 데이터 볼륨 생성은 아래 별도 실행 명령을 수행할 때 일어납니다.

## 공식 참고

- [Docker Compose up과 --wait](https://docs.docker.com/reference/cli/docker/compose/up/)
- [Docker Compose 서비스와 포트](https://docs.docker.com/reference/compose-file/services/)
- [Docker 포트 게시와 localhost](https://docs.docker.com/engine/network/port-publishing/)
- [Dockerfile USER와 HEALTHCHECK](https://docs.docker.com/reference/dockerfile/)
- [Cloudflare Tunnel 설정](https://developers.cloudflare.com/tunnel/get-started/)
- [Cloudflare Tunnel 로컬 설정과 catch-all 규칙](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)

## 선택형 PostgreSQL 등록 기록

기본 Compose는 메모리 모드입니다. `compose.postgres.yaml`을 추가하면 외부 계정 없이 로컬 PostgreSQL 17을 실행하고 TEST 등록·취소 기록을 보존합니다. DB를 호스트 포트로 게시하지 않으며, 볼륨은 일반 `down` 뒤 유지됩니다. `down -v`는 기록을 지우므로 일반 중지 절차에서 사용하지 않습니다. 명령과 비밀 생성·재시작·장애 복구는 [PostgreSQL 안내](durable-receipts.md)를 따릅니다.

## CI 배포 산출물과 staging CD

[CI/CD 안내](cicd.md)에 formatter/lint·최종 게이트·JAR/시험 APK·검증한 Docker 이미지 묶음·출처 검사·SSH·배포 후 검사·롤백 구성을 설명합니다. `deploy/compose.staging.yaml`은 기존 로컬 Compose와 별개이며 `release.py`가 검증한 불변 이미지로 SAMPLE·FCM 비활성·메모리 staging만 실행합니다. 호스트와 키는 생성하지 않았으며 관리자 보호 규칙과 environment 승인도 미적용입니다.

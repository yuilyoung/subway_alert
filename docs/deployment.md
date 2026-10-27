# 백엔드 실행과 Android 배포

## 역할과 선택

| 항목 | 이번 개발 기준 | 실제 상태 |
| --- | --- | --- |
| 개발 백엔드 | 개발자 PC의 Docker Compose에서 Spring Boot 실행 | 설정 파일 작성, 컨테이너 실행 미검증 |
| 개발 HTTPS 진입점 | 같은 PC의 Cloudflare named Tunnel | 비활성 예제만 작성, 계정·도메인·터널 미생성 |
| 베타·운영 백엔드 | 상시 실행 Linux 서버에서 같은 Docker 이미지 실행 | 서버 업체·요금·지역 미선정, 실제 배포 없음 |
| 데이터베이스 | Supabase PostgreSQL 계획 | 스키마 초안, 앱·서버 미연동 |
| 알림 | Firebase Cloud Messaging | TEST 전송 코드, 실제 자격 증명·기기 수신 미검증 |
| Android 빌드 | Expo/Gradle로 APK 또는 AAB 생성 | 테스트 APK만 생성·검증 |
| Android 정식 배포 | Google Play Console/Play 스토어 | 계정·서명·테스트 트랙·심사·출시 미완료 |

Cloudflare Tunnel은 외부 HTTPS 요청을 PC 또는 운영 서버의 Spring Boot로 전달하는 연결 수단입니다. Java 서버를 대신 실행하거나 DB를 제공하지 않습니다. PC가 꺼지거나 절전 상태가 되면 해당 PC의 서버와 터널도 사용할 수 없습니다. 운영 서버는 유료 자원 선택과 운영 조건을 확인하기 전까지 자동 생성하지 않습니다.

Android 앱은 웹앱처럼 Cloudflare에 올려 실행하는 것이 아닙니다. 기기에 설치되는 APK는 직접 테스트할 수 있고, 정식 배포는 서명한 AAB를 Google Play Console에 제출하는 방식입니다. 앱과 통신하는 백엔드는 별도로 계속 실행되어야 합니다. CI는 빌드·테스트 자동화이며 앱 스토어나 백엔드 호스팅을 대신하지 않습니다.

## 로컬 백엔드 실행

Docker Engine 28 이상과 Docker Compose 플러그인(v2 이상)을 준비합니다. 오래된 Docker에는 localhost 게시 포트가 같은 네트워크에서 접근될 수 있는 제약이 있으므로 최신 엔진을 사용합니다. 명령은 저장소 루트에서 실행합니다.

```sh
docker compose --env-file deploy/.env.example config
docker compose --env-file deploy/.env.example up --build -d backend
docker compose ps
curl --fail http://127.0.0.1:8080/api/health
docker compose logs --tail=100 backend
docker compose down
```

포트를 바꾸려면 예제를 비밀값이 없는 개인 `.env` 파일로 복사한 뒤 `BACKEND_PORT`를 변경하고 같은 `--env-file` 경로를 사용합니다. 컨테이너는 내부에서 `0.0.0.0:8080`을 수신하지만 호스트 게시 포트는 `127.0.0.1`에만 연결됩니다. 다른 기기 또는 인터넷에 직접 열지 않습니다. 로컬 healthcheck는 `/api/health`의 HTTP 응답 확인이며 서울 API·Firebase·DB·실제 알림의 정상 동작을 증명하지 않습니다.

Dockerfile은 Maven에서 테스트와 패키징을 수행한 뒤 JRE 이미지에서 UID 10001의 일반 사용자로 실행합니다. 런타임 파일 시스템은 읽기 전용이고 임시 파일은 제한된 `/tmp`를 사용합니다. 현재 이미지 태그는 주요 런타임 버전을 지정한 태그이며 불변 digest로 고정되지는 않았습니다. 운영 릴리스 전에 실제 빌드 검증과 함께 승인한 이미지 digest 및 취약점 검사를 기록해야 합니다.

로컬 Compose는 공개 `sample` 키만 사용하고 FCM을 끕니다. Firebase 서비스 계정 키나 실제 서울 API 키를 이미지, Git, 앱 또는 `.env.example`에 넣지 않습니다. FCM 시험은 [서버 설정](../server/README.md)의 운영자 설정을 별도로 준비한 뒤 비밀 저장소나 읽기 전용 자격 증명 마운트를 사용하도록 확장해야 합니다. 현재 Compose에 해당 설정은 자동 포함되지 않습니다.

## Cloudflare Tunnel은 아직 활성화하지 않음

`deploy/cloudflared/config.disabled.example.yml`에는 실제 hostname route가 없고 마지막 `http_status:404` 규칙만 있습니다. 자격 증명 경로와 UUID도 예시입니다. Compose에 cloudflared 서비스가 없으며 실행·DNS 생성·계정 변경은 수행하지 않았습니다.

현재 서버 API에는 운영용 사용자 인증, 영속 세션, 통합된 요청 제한이 없습니다. 시험 세션 소유권 토큰만으로 등록 API나 열차 조회 API가 보호되는 것은 아닙니다. 따라서 Quick Tunnel이나 public hostname을 지금 실행해서는 안 됩니다. 공개 연결 전에는 API 인증과 요청 예산, 자격 증명, HTTPS hostname, 기기 접속 정책을 구현·확인해야 합니다. Cloudflare 브라우저 로그인 정책만 설정했다고 Android 네이티브 API 인증이 자동 완성되는 것도 아닙니다.

그 조건이 준비된 뒤 운영자가 named Tunnel과 DNS를 별도로 구성하고, 같은 PC에서 실행하는 cloudflared의 origin을 `http://127.0.0.1:8080`으로 설정합니다. 외부 구간은 Cloudflare HTTPS이며 이 로컬 HTTP origin은 같은 PC 내부에 한정됩니다. cloudflared를 별도 컨테이너에 넣는 경우 그 컨테이너의 localhost는 백엔드가 아니므로 전용 네트워크의 서비스 주소로 다시 설계해야 합니다. 비활성 예제는 이 별도 컨테이너 방식을 구성하지 않습니다.

계정과 실제 경로가 준비된 환경에서만 다음 구문으로 ingress 문법을 검사할 수 있습니다. 이는 터널을 실행하거나 외부에서 접속 가능하게 만드는 명령이 아닙니다.

```sh
cloudflared tunnel --config deploy/cloudflared/config.disabled.example.yml ingress validate
```

## 검증 범위와 남은 일

현재 작업 환경에는 Docker/Podman 엔진과 cloudflared가 없습니다. 공식 배포본의 SHA-256을 확인한 standalone Docker Compose v5.6.1로 `config --quiet`를 실행해 구문과 환경변수 치환을 검증했습니다. 해석된 구성의 게시 주소 `127.0.0.1:8080`, 공개 샘플 고정, FCM 비활성화도 확인했습니다. 비활성 ingress와 YAML 파싱은 별도로 정적 확인했습니다. 이미지 빌드, 컨테이너 healthcheck, 종료·재시작, 실제 Tunnel 연결은 수행하지 않았습니다. 서버와 앱의 테스트 성공만으로 이 배포 구성이 실행됐다고 보지 않습니다.

다음 검증은 Docker가 있는 개발 PC에서 위 명령을 실행해 healthcheck를 확인하는 것입니다. 그다음 Firebase 설정을 포함해 앱을 다시 빌드하고, 인증된 HTTPS 개발 경로에서 TEST 알림을 실기기로 검증해야 합니다. 실제 하차 알림은 서울 실키 HTTPS·경로·시간대·운행 예외를 확인하기 전까지 차단 상태로 유지합니다. 운영 전에는 영속 DB·재시작 복구·모니터링·인증·전송 재시도/멱등성·권한 정리가 추가로 필요합니다.

## 공식 참고

- [Docker Compose 서비스와 포트](https://docs.docker.com/reference/compose-file/services/)
- [Docker 포트 게시와 localhost](https://docs.docker.com/engine/network/port-publishing/)
- [Dockerfile USER와 HEALTHCHECK](https://docs.docker.com/reference/dockerfile/)
- [Cloudflare Tunnel 설정](https://developers.cloudflare.com/tunnel/get-started/)
- [Cloudflare Tunnel 로컬 설정과 catch-all 규칙](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)

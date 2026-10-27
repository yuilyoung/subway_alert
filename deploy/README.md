# 배포 설정 파일

실행 절차와 확정·미확정 항목은 [배포 안내](../docs/deployment.md)를 확인하세요.

`compose.yaml`은 저장소 루트에 있으며 로컬 백엔드 하나만 실행합니다. 이 폴더의 `.env.example`은 `SUBWAY_API_TOKENS`가 빈 템플릿이며 실제 키가 없습니다. 빈 상태에서는 정확히 `GET /api/health`만 인증 없이 호출할 수 있고 다른 경로는 503으로 닫힙니다. `cloudflared/config.disabled.example.yml`은 모든 요청에 404를 돌려주는 비활성 예제이며 자동 실행되지 않습니다.

저장소 루트에서 Python 3 표준 라이브러리만으로 시험 참가자용 키 파일을 만듭니다. POSIX 파일 권한을 지원하는 환경에서 실행합니다.

```sh
python3 deploy/generate_api_tokens.py --output .env
docker compose --env-file .env config --quiet
docker compose --env-file .env up --build --wait --wait-timeout 180 backend
```

기본은 키 1개이며 `--count 2`처럼 1~20개를 지정할 수 있습니다. 각 키는 `secrets.token_urlsafe(32)`로 만든 43자의 base64url 값입니다. 파일은 `BACKEND_PORT=8080`과 쉼표로 구분한 `SUBWAY_API_TOKENS`를 포함하며 권한은 0600입니다. 기존 파일·빈 파일·심볼릭 링크를 덮어쓰지 않습니다. 성공 시 파일 경로만 출력하고 키는 출력하지 않습니다. `.env`는 Git에서 제외됩니다. 다른 파일명을 선택하면 저장소 바깥의 비공개 경로를 사용하세요.

운영자가 비공개 편집기에서 파일을 열어 참가자마다 다른 키 하나를 별도 안전한 경로로 전달합니다. 앱의 서버 연결 입력란에 HTTPS origin과 해당 키를 저장합니다. 이 키는 일반 사용자 로그인이나 FCM 기기 소유 증명이 아니며 APK에 공용 키로 넣지 않습니다. 키를 회수하려면 서버 목록에서 제거하고 백엔드를 다시 생성·시작해야 합니다. 기존 파일을 갱신할 때도 0600 권한을 유지하세요. 키가 회수된 기기의 감시 취소는 실패할 수 있고 기존 세션은 최대 2시간 후 만료됩니다.

환경 파일이나 `docker compose config`의 전체 출력을 공유하지 마세요. 검증에는 `config --quiet`를 사용합니다. 키·Authorization 헤더를 URL, 로그, 화면 캡처, Git 또는 대화창에 넣지 않습니다.

## 독립 Docker 실행 검사

POSIX 환경에서 Python 3, Docker Engine 28 이상과 `up --wait`를 지원하는 Docker Compose v2 이상이 필요합니다. 저장소 루트에서 실행합니다.

```sh
python3 deploy/smoke_compose.py --report artifacts/docker-smoke.json
```

검사기는 저장소 Dockerfile로 고유 태그 이미지를 빌드하고 고유 Compose 프로젝트를 사용합니다. 기존 `.env`·기본 프로젝트·`subway-alert-backend:local` 이미지는 변경하지 않습니다. 임시 키와 빈 IPv4 루프백 포트로 미설정 503, 인증 401/200, 호출 제한 429, healthcheck·런타임 제한·재시작을 검사합니다. 서울 API·FCM에는 요청하지 않습니다.

성공·실패 모두 자신이 만든 프로젝트만 정리하고 정리 실패도 실패로 보고합니다. JSON에는 비밀 없는 판정만 남기며 환경변수·전체 inspect/config·컨테이너 로그·키를 기록하지 않습니다. CI는 별도 Docker 작업에서 같은 명령을 실행하고 보고서를 14일 보관합니다. 실행 결과와 한계는 [Docker 검증 기록](../docs/verification-docker.md)을 확인하세요.

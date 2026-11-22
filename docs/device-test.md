# Mac에서 Android TEST 알림과 서울 실키 조회 확인

Mac의 Rancher Desktop에서 `dockerd (moby)` 엔진을 선택합니다. `docker context show`로 Rancher Desktop 연결을, `docker version`과 `docker compose version`으로 Docker Engine 28 이상·Compose 2.24.4 이상을 확인하세요. Python 3와 Google Play 서비스가 있는 Android 실기기가 필요합니다. 아래 명령은 저장소 루트에서 실행합니다.

기존 DEMO는 `127.0.0.1:8080`에서 계속 사용할 수 있습니다. 실기기 백엔드는 고유 프로젝트·이미지 태그와 Mac의 `127.0.0.1:18080`을 사용합니다. `lsof -nP -iTCP:18080 -sTCP:LISTEN` 결과가 비어 있으면 바로 진행하세요. 이미 사용 중이면 다음 명령으로 게시 포트·프로젝트·서비스를 확인합니다.

```sh
docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}'
```

18080 점유자가 본인의 기존 지하철 `backend`일 때만 감시를 종료하고 `demo_project='확인한-프로젝트명'`을 지정한 뒤 `docker compose -p "$demo_project" -f compose.yaml stop backend`로 잠시 멈춥니다. 서버를 멈추면 메모리 세션이 사라집니다. 시험 종료 후 `device_compose down`을 먼저 실행하고 `docker compose -p "$demo_project" -f compose.yaml start backend`로 같은 컨테이너를 재개하세요. 다른 서비스가 18080을 사용하면 해당 운영자와 포트 사용을 조율하세요.

## 1. 서버 자격 증명 준비

서버 서비스 계정에는 시험용 Firebase 프로젝트의 FCM 전송 권한이 필요합니다. Android `google-services.json`은 같은 프로젝트, 패키지 `com.yuilyoung.subwayalert`용이어야 합니다. 키 원문은 비공개 편집기에서만 다루세요. Docker 관리자와 Mac 계정은 서버 비밀에 접근할 수 있으므로 신뢰하는 시험용 Mac을 사용합니다.

```sh
device_dir="$HOME/.config/subway-alert-device"
install -d -m 0700 "$device_dir"
python3 deploy/generate_api_tokens.py --output "$device_dir/device.env"
install -m 0444 '/실제/경로/서버-서비스-계정.json' "$device_dir/firebase-admin.json"
```

생성 명령은 처음 한 번 실행합니다. 기존 `device.env`가 있으면 재사용하세요. `0700` 디렉터리는 Mac의 다른 사용자 접근을 막고, 그 안의 `0444` 복사본은 컨테이너의 UID 10001이 읽을 수 있습니다. 단일 파일만 컨테이너에 읽기 전용으로 연결합니다. `device.env`의 권한은 `0600`으로 유지하고, 생성된 기기 키 옆에 다음 두 줄을 추가해 예시를 실제 값으로 바꿉니다.

```dotenv
DEVICE_FIREBASE_PROJECT_ID=your-firebase-project-id
DEVICE_FIREBASE_CREDENTIALS_FILE='/Users/your-account/.config/subway-alert-device/firebase-admin.json'
```

## 2. 백엔드 기동

```sh
device_compose() {
  docker compose -p subway-device-test --env-file "$device_dir/device.env" \
    -f compose.yaml -f compose.device.yaml "$@"
}
device_compose config --quiet && device_compose build backend && \
  device_compose run --rm --no-deps -T --entrypoint sh backend -ec \
    'test "$(id -u)" = 10001 && test -f "$GOOGLE_APPLICATION_CREDENTIALS" && test -s "$GOOGLE_APPLICATION_CREDENTIALS" && test -r "$GOOGLE_APPLICATION_CREDENTIALS"' && \
  device_compose up --no-build --wait --wait-timeout 180 backend
curl --fail http://127.0.0.1:18080/api/health
```

파일이 없으면 Docker가 마운트를 거부합니다. 읽기 검사에 실패하면 파일이 Mac 홈 디렉터리에 있는지, 지정한 절대 경로와 권한이 맞는지 확인하세요. health 200은 백엔드 기동을 확인합니다. Firebase 초기화·전송 성공은 다음 단계에서 확인합니다. `docker compose config`의 전체 출력과 `docker inspect`에는 키가 포함될 수 있습니다.

## 3. 공개 샘플로 TEST 푸시 수신 확인

**USB·Metro 개발 빌드**는 외부 HTTPS 경로 없이 사용할 수 있습니다. Node 24, JDK 17, Android SDK Platform 36·Build Tools 36.0.0·Platform Tools(`adb`)를 준비하세요. 기기의 개발자 옵션에서 USB 디버깅을 켜고 Mac 연결을 승인합니다. 네이티브 수정을 보관한 새 작업 복사본에서 Android 클라이언트 설정을 적용합니다.

```sh
android_json='/실제/경로/Android/google-services.json'
adb devices
adb reverse tcp:18080 tcp:18080
(cd mobile && export GOOGLE_SERVICES_JSON="$android_json" && npm ci && \
  npx expo prebuild --platform android --no-install && npx expo run:android --device)
```

Metro를 실행해 둔 상태로 앱의 서버 주소에 `http://127.0.0.1:18080`을 입력합니다.

**독립 ARM64 APK**를 쓸 때는 기기가 신뢰하는 인증서가 있는 기존 HTTPS origin을 이 백엔드로 연결해야 합니다. Mac에 GitHub CLI(`gh`)로 로그인한 뒤, 아래 명령으로 Android 클라이언트 파일을 검증해 repository Actions secret에 등록하고 수동 빌드를 실행할 수 있습니다. `main`에 `firebase_android` 입력이 포함된 CI가 있어야 합니다.

```sh
android_json='/실제/경로/Android/google-services.json'
repo='yuilyoung/subway_alert'
gh auth status && python3 -c 'import base64, pathlib, sys; from deploy.prepare_android_firebase import client_config; client_config(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode("ascii"))' "$android_json" && \
  base64 -i "$android_json" | gh secret set FIREBASE_ANDROID_CONFIG_BASE64 --repo "$repo" && \
  gh workflow run ci.yml --repo "$repo" --ref main -f firebase_android=true
```

GitHub Actions의 해당 CI 실행에서 `subway-alert-firebase-test-arm64-<run_number>` Artifact를 내려받아 압축을 풀고 기기에 APK를 설치합니다. 이 secret에는 `com.yuilyoung.subwayalert`용 Android 클라이언트 설정만 올립니다. 서버 서비스 계정과 서울 키는 Mac에 둡니다. [Android 빌드 안내](../mobile/README.md)

1. 앱의 서버 연결 화면에 해당 빌드의 origin과 `device.env`의 참가자용 키 하나를 저장하고 Android 알림 권한을 허용합니다. **2호선 열차 조회**를 눌러 **서울시 공개 샘플** 표시(`SAMPLE`)에서 정보 시각이 최근 60초 이내인 일반 열차를 선택하고 서로 다른 직전역·목적지를 입력해 시험 감시를 시작합니다. 최신 일반 열차가 없으면 잠시 후 조회하세요.
2. **잠금 화면 수신**을 시험하려면 기기에서 이 앱의 잠금 화면 알림을 허용합니다. 앱에 **시험 감시 중**이 표시되면 위에서 `device_compose`를 정의한 Mac 터미널에서 아래 명령을 실행하세요. 전용 시험 백엔드가 일시 정지되면 휴대폰에서 **시험 알림 보내기**를 한 번 누르고 전원 버튼으로 화면을 잠급니다. 화면이 꺼진 것을 확인한 뒤 터미널에서 Enter를 누르면 백엔드가 전송 요청을 처리합니다. 앱 요청 제한 시간은 10초입니다.

   ```sh
   (
     set -e
     device_compose pause backend
     trap 'device_compose unpause backend' EXIT
     echo '시험 알림 보내기를 누르고 휴대폰을 잠근 뒤 Enter를 누르세요.'
     IFS= read -r answer
   )
   ```

   중단 후 백엔드가 일시 정지 상태라면 `device_compose unpause backend`로 재개합니다.
3. 잠금 화면에 **[시험] 지하철 하차 알림**이 실제 표시된 시각을 기록합니다. 잠금을 풀고 **상태 새로고침**을 눌러 `FCM_ACCEPTED`와 서버 수락 시각(UTC)을 확인하고, 기기의 표시 시각에도 시간대를 적습니다. 요청이 시간 초과된 경우에도 먼저 상태를 조회합니다. `UNAVAILABLE`이면 서버의 Firebase 설정을, `FAILED`이면 해당 프로젝트의 발송 권한과 기기 등록 상태를 확인합니다. 시험 중 Android가 앱 프로세스를 종료해 재실행 시 기존 세션이 자동 종료된 경우에는 새 TEST 세션으로 다시 검사합니다.
4. **시험 감시 종료**를 누르고 새 감시 등록 화면으로 돌아오는지 확인합니다. 시험 기록에는 앱·서버 커밋, 기기 모델·Android 버전, 서버 수락 시각, 잠금 화면 표시 시각, 종료 결과를 남깁니다.

## 4. 서울 발급 키로 한 번 조회

`device.env`에 `DEVICE_SEOUL_SUBWAY_KEY`를 추가하고 발급 키를 비공개 편집기에서 입력한 뒤 `device_compose up --no-build --force-recreate --wait backend`를 실행합니다. 컨테이너를 다시 만들면 메모리 세션이 초기화됩니다. 앱에서 2호선을 한 번 조회해 **서울시 실시간 데이터 · 서버 제공** 표시(`LIVE`)와 열차의 정보 시각을 확인하세요. 결과가 비면 **조회된 열차가 없습니다**로 기록합니다. 서버는 서울 API에 실키를 HTTPS로만 전송합니다. `502`이면 실키 연결은 미확인 상태입니다. 직접 조회 1회에 최대 5페이지의 API 호출이 발생할 수 있습니다. TEST 감시는 계속 공개 샘플을 사용하며 LIVE 결과로 실제 하차 알림을 등록할 수 없습니다.

시험을 마치면 `device_compose down`을 실행하고 USB 포워딩을 쓴 경우 `adb reverse --remove tcp:18080`으로 해제합니다. 다음 FCM 시험은 비공개 환경 파일에서 `DEVICE_SEOUL_SUBWAY_KEY`를 지운 뒤 시작합니다. 결과를 공유할 때는 수신 여부·시각·응답 모드·건수만 기록하고 키, FCM 토큰, 인증 헤더는 제외하세요.

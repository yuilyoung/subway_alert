# 지하철 하차알림 · Subway Alert

React Native + Kotlin Android 앱, Spring Boot + PostgreSQL 추적 서버입니다.
첨부된 **지하철 하차알림 앱 설계 문서 v1.0 (2026-10-27, 13쪽)**를 바탕으로 구현했습니다.
기존 저장소의 초기 설명: `subway departure and arrival alert help app`.

> **개발용 MVP**입니다. 실제 열차 API 키·Firebase·실사용 역/시설 데이터 및 실기기 검증이 필요합니다.
> 데모 모드의 역과 열차는 가상 데이터이며 실제 하차 안내에 사용하면 안 됩니다.

## 구현 범위
- 출발/도착역 직접 검색, 방향 선택, 검증된 동일 호선 경로 확인.
- 탑승 열차를 확인한 뒤 목적지 직전역 출발을 감지. 서버는 활성 호선을 10초 주기로 폴링.
- Kotlin FCM 수신 서비스가 JS 실행 여부와 무관하게 알림 채널을 통해 진동/헤드업 알림 표시를 시도.
- 즐겨찾기 최대 5개, 재실행 후 유지, 요일·시간대 편집.
- 동의한 출퇴근 시간대 + 출발역 300m 지오펜스 → 자동 **탑승 확인 준비**. 실제 탑승 확인은 사용자 수행.
- 출발/도착역의 빠른 환승·화장실·편의시설·개찰구·출구 화면과 출처/확인일 표시. 자료 미등록은 명시적으로 표시.
- GPS 근처 역 검색, 지오펜스 복원, 중복 이벤트 억제, 세션 취소/만료, 서버 outbox 재시도.

**지원하지 않는 것:** 환승을 포함한 다중 열차 여정, 급행, GPS만으로 탑승 열차 확정, 오프라인 실제 열차 추적, 알림 도착 시간 보장.

## 구조
```text
mobile/                   React Native UI와 Kotlin 네이티브 모듈
  android/                Firebase 알림·Geofencing·WorkManager·로컬 저장
server/                   Java 21 / Spring Boot / TOPIS / FCM / Flyway
  src/main/resources/db/  PostgreSQL 마이그레이션
infra/                    Cloudflare Tunnel 예시
tools/                    핵심 검사, 카탈로그 검증/적재
data/README.md            실제 역/시설 데이터 계약
docs/                     설계 보완, API, 검증 기록, 인수 체크리스트
```

## 1. 비밀키 없이 로컬 데모 실행
Docker와 Docker Compose가 필요합니다.
```bash
cp .env.example .env
# .env의 POSTGRES_PASSWORD를 개발용 비밀번호로 변경
docker compose up --build
```
서버는 호스트 `127.0.0.1:8080`에만 공개합니다. DB는 `127.0.0.1:5432`.
`GET /api/health`의 mode가 `DEMO`인지 확인하세요.
데모선에는 출발역·중앙역·공원역·도착역·종착역이 있습니다.
탑승 확인 후 10초마다 한 역씩 모의 진행합니다. 서버는 실제 FCM을 보내지 않습니다.
안드로이드 **설정 → 10초 이후 테스트 알림 예약**으로 네이티브 백그라운드 알림을 별도 점검할 수 있습니다.

## 2. Android 빌드
Node 22.11+, JDK 17, Android SDK 36, Build Tools 36.0.0, NDK 27.1.12297006이 필요합니다.
React Native 0.86.3 / React 19.2.3 템플릿 호환 버전을 고정했습니다. 최소 Android API 24.

```bash
cd mobile
npm install
npm run typecheck
cd android
./gradlew :app:assemblePreview -PreactNativeArchitectures=arm64-v8a,x86_64
```
Windows에서는 `gradlew.bat :app:assemblePreview -PreactNativeArchitectures=arm64-v8a,x86_64`.
텍스트 부트스트랩이 공식 Gradle 9.3.1 배포본과 SHA-256을 받아 검증 후 실행합니다.

`app/build/outputs/apk/preview/`의 APK는 JS 번들이 포함된 **테스트 서명 preview**입니다. Metro 없이 실행됩니다.
Google Play 배포용으로 사용하지 마세요. Firebase 설정 없는 CI preview는 데모 전용입니다.
`google-services.json`을 추가한 상태에서 preview를 만들려면 Firebase에 `com.subwayalert.preview` 앱도 등록해야 합니다.

개발 중에는 `npm start`와 별도 터미널의 `npm run android`로 Metro + debug 빌드를 사용할 수 있습니다.
에뮬레이터 기본 서버: `http://10.0.2.2:8080`.
USB 실기기는 다음 실행 후 앱 서버 주소를 `http://127.0.0.1:8080`으로 설정하세요.
```bash
adb reverse tcp:8080 tcp:8080
```

## 3. 실제 서비스 연결
1. Firebase Android 앱 `com.subwayalert`를 등록하고 **Anonymous Authentication**을 활성화합니다.
   `google-services.json`을 `mobile/android/app/`에 로컬로 넣습니다(커밋 금지).
2. 서버에 `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`를 비밀 환경변수/파일로 설정합니다.
   서비스 계정 JSON은 앱이나 저장소에 넣지 않습니다.
3. 서울 열린데이터광장의 실시간 열차 위치 API 키를 `TOPIS_API_KEY`로 설정합니다.
   승인된 호출량에 맞춰 `TOPIS_DAILY_BUDGET`을 조정하세요. 기본값 9000은 제공기관의 보장 할당량이 아닙니다.
4. PostgreSQL 또는 Supabase의 서버 전용 JDBC 연결을 `SUPABASE_DB_URL/USER/PASSWORD`로 설정합니다.
   클라우드 DB에는 TLS 인증서 검증을 사용하세요. PostgreSQL JDBC의 `sslmode=verify-full`은 신뢰할 CA 설정도 필요합니다.
   JDBC 계정은 `app_private` 테이블의 전용 소유자 역할이어야 합니다. anon/authenticated에 접근을 열지 마세요.
5. **demo 프로필 없이** 서버를 실행합니다. 키가 없으면 live 서버는 시작을 거부합니다.
   ```bash
   mvn -f server/pom.xml spring-boot:run
   ```
6. `data/README.md`를 따라 검증된 실제 역·방향 연결·시설 자료를 적재합니다. 초기 live 카탈로그는 비어 있습니다.
7. HTTPS 서버를 앱 설정에 입력하고 데모 모드를 끕니다. 필요하면 `infra/cloudflared.example.yml`을 로컬에서 채웁니다.
   demo 서버를 인터넷으로 노출하지 마세요.
8. 실기기 FCM·권한·잠금화면·위치 감지와 실제 탑승 테스트를 수행합니다 (`docs/ACCEPTANCE.md`).

Spring Boot는 설계서와의 호환을 위해 3.5.16을 사용합니다. 프로덕션 배포 전에 3.x 지원 상태와 보안 업데이트를 검토하고 지원되는 릴리스로 이전해야 합니다.

## 4. 검증
```bash
bash tools/test-core.sh
python -m unittest discover -s tools -p 'test_catalog.py'
# PostgreSQL 실행 및 환경변수 설정 후:
RUN_DB_TESTS=true mvn -f server/pom.xml verify
```
`tools/test-core.sh`는 Java/TypeScript를 실행하고 Kotlin 컴파일러가 있으면 출퇴근 시간대 검사도 실행합니다.
CI는 의존성 설치 후 타입 검사, PostgreSQL 통합 테스트, Android preview 빌드를 실행하도록 구성되어 있습니다.
최초 설치는 lockfile을 생성합니다. CI가 산출한 `package-lock.json`을 검토·커밋한 뒤 재현 가능한 설치를 유지하세요.
현재 수행 결과와 미검증 범위는 `docs/VERIFICATION.md` 및 PR의 실제 CI 상태를 확인하세요.

## 설계서에서 명시적으로 보완한 부분
`docs/superpowers/specs/2026-10-27-subway-alert.md`에 원문 요구와 구현 판단을 구분했습니다.
- 호선의 아무 열차가 아니라 **선택한 열차 번호**를 추적합니다.
- 오래된 데이터에 정거장을 임의로 더하지 않습니다. 지연 경고와 LATE 이벤트를 구분합니다.
- FCM 토큰을 인증 수단으로 쓰지 않습니다. Firebase ID token과 소유권을 검사합니다.
- Kotlin 알림 서비스로 수신 처리하며 전체화면 권한이나 방해금지 우회를 요청하지 않습니다.
- DB private schema와 RLS를 사용하고 앱에 DB 관리 키를 넣지 않습니다.

## 운영 한계와 개인정보
FCM·지오펜스는 실시간 도착을 보장하지 않습니다. 앱 강제 종료, 알림/위치 차단, 배터리 제한, API 지연 시 실패할 수 있습니다.
차내 안내를 함께 확인하세요. TOPIS 캐시는 단일 서버 프로세스 기준이므로 이 MVP는 서버 1개로 운영해야 합니다.
즐겨찾기는 기기에 저장합니다. GPS는 근처 역 조회/기기 내 지오펜스에 사용하며 위치 이력을 서버에 저장하지 않습니다.
서버에는 Firebase UID, 추적 경로, FCM 토큰과 알림 이력이 남고 종료 세션은 7일 뒤 정리합니다.

공식 참고: React Native template (`react-native-community/template`, `0.86-stable`), Android Developers Geofencing,
Firebase Cloud Messaging Android priority, 서울 열린데이터광장. API 키·시설 자료·실기기 검증은 별도로 필요합니다.

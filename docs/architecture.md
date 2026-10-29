# 지하철 하차 알림 설계·아키텍처 v1.7

개정일: 2026-10-29 (한국 시간). CD 호스트 초기화·GitHub 환경 준비·검증한 SSH 전송과 승인형 자동 배포 구성을 추가한 개정본입니다. 이 Markdown이 현재 설계 기준이며 별도 PDF v1.1에는 이번 개정이 아직 반영되지 않았습니다. 원본 첨부 PDF는 공개 저장소에 올리지 않습니다.

## 1. 결정 사항과 실제 상태

개발 백엔드는 개인 PC에서 Docker로 실행합니다. 개발용 HTTPS 연결 수단은 Cloudflare Tunnel로 준비합니다. 운영 형태는 상시 실행 Linux 호스트의 Docker로 정하되 VPS 업체·리전·요금은 예산 확정 전까지 미선정입니다. Android 정식 배포처는 Google Play, 기본 시험 빌드는 GitHub Actions입니다. 이는 설계 기준이며 계정·서버·도메인 생성 완료를 뜻하지 않습니다.

| 구성 | 역할 | 실제 상태 |
| --- | --- | --- |
| 개인 PC + Docker | 개발 API·스케줄러 실행 호스트 | 로컬 Java 검증, 컨테이너 설정 준비 |
| Cloudflare Tunnel | 기존 API의 HTTPS 연결 경로 | 계정·도메인·터널 미구성, 비활성 템플릿 |
| Linux VPS + Docker | 24시간 운영 백엔드 목표 | 업체·리전·요금·도메인 미선정 |
| PostgreSQL / Supabase | 로컬 TEST 기록 저장 / 향후 운영 저장 | 선택형 JDBC 저장 구현, Supabase 프로젝트 미확정·미연결 |
| Firebase FCM | Android 원격 알림 | 코드 구현, 실제 수신 미검증 |
| GitHub Actions | 테스트와 독립 시험 APK 생성 | 이전 CI #13 전체 작업 성공, 이번 변경 CI는 별도 확인 |
| Google Play | 정식 앱 설치·업데이트 유통 | 개발자 등록·심사·게시 미진행 |

Tunnel만으로 백엔드 서버가 생기지 않습니다. 호스트의 전원·네트워크·프로세스가 중단되면 API와 폴링도 중단됩니다. 앱 유통과 API 호스팅은 별개이며 Android 앱을 위해 별도 웹 파일 서버를 필수로 운영할 필요는 없습니다.

## 2. 목표 기능과 사용자 흐름

최종 목표는 출발역·목적지 직접 검색, 목적지 한 정거장 전 Android 백그라운드 알림, 최대 5개 즐겨찾기, 출퇴근 조건 감지, 빠른 환승·화장실·편의시설·개찰구·출구 정보 제공입니다. GPS와 서울 실시간 API를 함께 고려하되 GPS만으로 지하의 탑승 열차를 확정하지 않습니다.

현재 앱은 일부 2호선 5역의 데모, 즐겨찾기별 요일·시간 편집, 야간 출퇴근 확인 알림, 공개 샘플 열차 조회와 TEST 감시를 제공합니다. 역 시설과 전체 노선·환승은 미구현입니다. 사용자 입력 이전역이나 단순 선택은 실제 경로 검증이 아닙니다.

개발 시험 흐름은 운영자가 발급한 기기 키와 HTTPS origin 저장 → 앱의 샘플 열차 선택 → 이전역·목적지 입력 → 네이티브 FCM 토큰 취득 → 서버 TEST 세션 생성 → 공유 샘플 조회 → 일치 사건의 시험 전송 요청 → 상태 조회·취소입니다. Firebase 설정 없는 APK에서는 토큰 취득이 실패합니다. 수동 시험 전송은 실제 열차 이동과 무관합니다.

목표 운영 흐름은 검증된 역·방향·시각과 사용자의 탑승 확인을 갖춘 후에만 활성화합니다. 서버의 LIVE 감시는 현재 거부합니다. FCM 수락과 휴대폰 표시·정시 도착은 별도 상태입니다.

## 3. 기술 구성과 v1.0 변경점

| 항목 | v1.0 목표·가정 | v1.5 현재 구현·정정 |
| --- | --- | --- |
| 백엔드 | Spring Boot / Java 21 | Spring Boot 3.4.5 / Java 17 |
| 앱 | React Native Firebase / Notifee / Kotlin | Expo 54 / React Native 0.81.5 / expo-notifications |
| DB | Supabase PostgreSQL / JPA | 기본 메모리 + 선택형 PostgreSQL JDBC 등록 기록, Supabase 운영 연결 미완료 |
| 열차 조회 | 10초 공유 폴링 | TEST 기본 120초, 활성 세션만 공유 |
| 조회 예산 | 별도 제한 설명 없음 | 직접 조회 6회/분·240회/일 + TEST 폴링 600회/일, 서울 날짜·프로세스 기준 sample 모드에서 합계 최대 840회/일 |
| API 접근 | 일반 사용자 인증 목표 | 개발 기기별 Bearer 키와 메모리 요청 제한, 일반 사용자 로그인 미구현 |
| 지연 보정 | 경과 시간을 역 이동으로 환산 | 고정 시간으로 위치를 추정하지 않음 |
| 알림 | 실제 직전역 출발 FCM | TEST만 허용, 실제 Firebase·기기 미검증 |
| 비용 | 소규모 운영 무료로 서술 | 호스트·도메인·전기·가용성·사용량 별도 고려 |

원래 문서의 확정되지 않은 RLS 비활성화 권장은 폐기합니다. 공개 스키마는 RLS와 최소 권한을 함께 적용하는 것이 목표입니다. 서버 전용 특권과 앱 사용자 권한을 분리하며 비밀 키를 앱에 넣지 않습니다. 사용자 데이터용 Supabase SQL 초안은 미적용입니다. 선택형 로컬 등록 기록은 비공개 스키마와 RLS를 사용하며 운영 사용자 인증 테이블과 분리합니다.

## 4. 서버 API와 데이터·알림 경계

| 경로 | 현재 역할 | 주의점 |
| --- | --- | --- |
| GET /api/health | 개발 서버 상태 | 유일한 인증 예외, mode DEMO, 운영 준비 판정 아님 |
| GET /api/live/trains?line=2 | 서울 열차 조회 | Bearer 키, sample 최대 5건, 전체 운행 아님 |
| POST /api/monitor-sessions | TEST 세션 생성 | Bearer + UUID Idempotency-Key + 클라이언트 세션 비밀, LIVE 거부 |
| GET /api/monitor-sessions/{id} | 상태 확인 | Bearer 키와 X-Session-Token 소유권 필요 |
| DELETE /api/monitor-sessions/{id} | 취소 | 두 토큰 필요, 발송이 시작된 FCM 회수 불가 |
| POST /api/monitor-sessions/{id}/test | 수동 시험 전송 | 두 토큰 필요, 실제 열차 위치와 무관 |

기존 /api/track과 demo-event는 독립 모의 엔진이며 실제 내선·외선과 연결하지 않습니다. TEST 감시는 고정 공개 샘플 제공자를 사용해 실제 API 키를 보내지 않습니다. 조회용 LIVE 키는 HTTPS로만 전송하지만 연결은 미검증입니다.

일치 검사는 노선·열차번호 문자열·방향·직전역·출발 상태·세션 시작 이후 관측·60초 신선도·급행 제외를 확인합니다. 서울 시각 해석은 실측 추정이므로 아직 운영 검증으로 인정하지 않습니다. 샘플 매칭 후 SAMPLE_MATCHED로 끝내 추가 폴링을 중단합니다.

세션은 최대 500개, 2시간 만료와 추가 1시간 보관입니다. 기본 메모리 모드에서는 재시작하면 기록이 사라집니다. 선택형 PostgreSQL 모드는 등록·취소 표식·원래 만료시각을 보존합니다. FCM은 높은 우선순위·30초 TTL·시험 표식을 사용하며 프로세스별 호출 예산은 어느 저장 모드에서도 재시작 시 초기화됩니다. 앱이 미리 만든 UUID·256비트 세션 비밀로 멱등 등록합니다. 같은 ID·비밀·요청은 원래 만료시각과 현재 상태를 반환하고 중복 생성·재활성화하지 않습니다. 취소 선행 표식도 같은 500개 한도와 보관 기간에 포함되며 늦은 등록을 막습니다. PostgreSQL 재시작 복원 시 TRACKING은 CANCELLED(이미 만료했으면 EXPIRED), 미완료 SENDING은 UNKNOWN이 됩니다. FCM 토큰을 복원하거나 감시·전송을 재개하지 않습니다. 같은 DB의 두 번째 백엔드는 시작 시 advisory lock을 얻지 못해 실패합니다. 저장 실패가 관측되면 감시 API는 503으로 닫고 새 폴링·전송을 시작하지 않으며 DB 복구 후 백엔드를 재시작해야 합니다. 보관 기한을 넘긴 기록은 삭제되므로 영구 중복 억제나 분산 exactly-once를 보장하지 않습니다. 상세 계약과 실행은 [등록 기록 저장](durable-receipts.md)을 따릅니다.

`SUBWAY_API_TOKENS`는 쉼표로 구분한 최대 20개의 32~128자 base64url 키입니다. 미설정이면 정확히 `GET /api/health` 외 모든 경로는 503으로 닫히며 잘못된 구성은 비밀값 없는 오류로 서버 시작에 실패합니다. 키가 구성된 뒤 모든 보호 요청에는 `Authorization: Bearer <key>`가 필요하며 없는 키·잘못된 키·중복 또는 잘못된 헤더는 401입니다. localhost·프록시 헤더 예외는 없습니다. 원문 키를 URL·로그·오류에 남기지 않고 서버는 해시를 상수 시간으로 비교합니다.

인증 전 전체 요청은 600회/분, 인증한 키별 60회/분, 모의·TEST 세션 생성은 키별 3회/분입니다. 직접 열차 조회는 모든 키 합계 6회/분·서울 날짜 하루 240회이며 기존 TEST 감시 폴링 600회/일과 별도로 계산합니다. 분 한도는 token bucket으로 연속 보충하고 예산 초과는 429와 양의 정수 `Retry-After` 초를 반환합니다. 동시 요청에도 예산 초과 허용을 막습니다. 외부 서울 API 요청은 sample 모드에서 합계 최대 840회/일/프로세스지만 재시작·복제로 초기화·증가하므로 운영 과금 상한이 아닙니다.

직접 조회 240회는 클라이언트 요청의 허용 횟수입니다. 실키 LIVE 조회 한 번은 최대 5페이지의 서울 API 호출을 수행할 수 있어 외부 호출 840회 상한은 sample 모드에만 해당합니다. 실키의 통합 외부 호출 예산은 후속 구현이 필요합니다.

## 5. 개발 실행·Tunnel·운영 호스트

저장소의 compose.yaml은 백엔드 컨테이너를 호스트의 127.0.0.1:8080에만 연결합니다. 컨테이너 내부에서는 Spring Boot가 0.0.0.0에 바인딩되어야 합니다. Dockerfile은 Maven 빌드 단계와 Java 17 실행 단계를 나누고 비관리자 사용자로 실행합니다. 기본 sample·FCM 비활성 구성을 유지하고 `SUBWAY_API_TOKENS`만 환경에서 전달합니다. Python 생성 도구는 표준 라이브러리의 `secrets.token_urlsafe(32)`로 키를 만들고 파일을 독점 생성해 0600 권한을 설정하며 기존 파일·심볼릭 링크는 거부하고 경로만 출력합니다. `.env.example`의 키는 비어 있고 실제 `.env`는 Git에서 제외됩니다.

Cloudflare Tunnel 설정 예제는 모든 요청을 404로 종료하는 비활성 상태입니다. 실행 중인 별도 cloudflared가 호스트의 localhost API로 연결하는 구조만 문서화하며, 터널 생성·DNS 등록·외부 노출은 수행하지 않습니다. 컨테이너 안의 localhost와 호스트의 localhost를 혼동하지 않습니다.

현재 Bearer 키는 신뢰한 소수 시험 참가자별 접근 보호이며 일반 사용자 로그인이나 FCM 기기 소유 증명이 아닙니다. 공유 서비스 토큰을 APK에 내장하지 않습니다. 개발 터널 연결 전에도 실제 인증·HTTPS·비밀 전달과 회수·기기 접속을 검증해야 합니다. 일반 공개 운영에는 사용자 인증·권한, 영속/분산 쿼터, JSON 크기·동시 작업 제한, 에지 DDoS 방어, 운영 DB 연결·백업·복구 검증이 추가로 필요합니다. 이번 구현은 공개 Tunnel이나 운영 준비 완료를 의미하지 않습니다.

운영은 상시 실행 Linux 호스트에서 컨테이너와 재시작·로그·상태 감시를 관리하는 방향입니다. 스케줄러가 필요한 현재 구조는 유휴 시 중단되는 실행 환경에 그대로 배치하지 않습니다. 공급자·리전·예산·SLA는 사용자 선택 전까지 미확정이며, 유료 자원은 이번 작업에서 만들지 않습니다.

## 6. Android 빌드·앱 유통·비밀 설정

개발 실행은 Metro가 필요한 환경이고, 독립 시험 APK는 JavaScript를 내장한 ARM64 설치 파일입니다. CI는 release 변형으로 빌드하되 Expo 생성 Debug 키로 서명하므로 시험 전용입니다. 워크플로는 APK·체크섬·안내를 Artifact로 14일 보관하며 Play에 자동 게시하지 않습니다.

정식 배포는 업로드 키로 서명한 AAB를 Play Console에 제출하는 경로로 정합니다. 개발자 계정·Firebase 설정·정식 서명·개인정보 처리방침·데이터 안전·위치 권한 설명·스토어 테스트와 심사는 미진행입니다. EAS Build/Submit은 향후 선택 가능한 빌드·제출 도구이며 운영 API 호스팅을 대신하지 않습니다.

| 값 | 위치·용도 | 현재 상태 |
| --- | --- | --- |
| SUBWAY_API_TOKENS | 백엔드 허용 목록·참가자별 키 | 운영자 생성·별도 전달, 일반 사용자 로그인과 별개 |
| GOOGLE_SERVICES_JSON | 앱 빌드의 Firebase Android 설정 경로 | 파일 미제공, 재빌드 필요 |
| FIREBASE_PROJECT_ID / ADC | 백엔드 FCM 인증 | 실제 키·기기 미검증 |
| FCM_ENABLED | 서버 FCM 명시 활성화 | 기본 비활성 |
| SEOUL_SUBWAY_KEY | 서버 조회용 실제 키 | HTTPS 실측 미검증 |
| 터널 자격 증명 / 정식 업로드 키 | 운영자·빌드 비밀 저장소 | 미구성 |

앱은 HTTPS origin과 API 키를 SecureStore에 저장하며 origin 변경 시 키를 비우고 이전 응답을 무효화합니다. 요청은 `expo/fetch`의 redirect 거부와 Authorization 헤더를 사용하고 키가 없거나 잘못되면 전송하지 않습니다. 감시는 등록 당시 origin·API 키·세션 소유 토큰을 함께 보관해 연결 주소 변경 후에도 이전 비밀이 새 주소로 전송되지 않게 합니다. FCM 토큰 갱신·앱 재시작 시 기존 시험 감시 취소를 시도하며 실패하면 정보를 보존합니다. 운영자가 키를 회수하면 취소가 실패할 수 있고 기존 세션은 최대 2시간 후 만료됩니다. 서버 서비스 계정 개인 키를 google-services.json과 혼동하지 않습니다.

## 7. 검증 결과와 출시 차단 조건

기존 검증은 서버 테스트 33개·모바일 테스트 21개 통과, 가짜 제공자·가짜 FCM을 사용한 등록·매칭·상태·취소 통합 검사, 실제 서울 공개 샘플 5건 조회, 독립 ARM64 APK 빌드·JS 포함·서명 검사입니다. [이전 CI #13](https://github.com/yuilyoung/subway_alert/actions/runs/40520333343)의 전체 작업 성공도 과거 기록이며 이번 접근 보호 변경의 원격 CI 결과는 아닙니다. 이는 실제 사용자 하차 알림 검증이 아닙니다.

이번 작업은 서버 접근 필터·요청 예산, 앱 보안 연결 입력·SecureStore·인증 전송, 안전한 키 파일 생성, Compose 환경 전달, Markdown 설계 개정입니다. 실제 결과는 [검증 기록](verification-deployment.md)에 따로 남깁니다. Compose 구성 해석은 Docker 엔진 없이 검증할 수 있지만 이미지 빌드·컨테이너 실행·원격 CI·터널·Play 게시의 성공과 동일하지 않습니다. PDF는 이번 개정 대상에 포함하지 않습니다.

운영 활성화 조건은 실제 HTTPS API와 데이터 시간대·역 순서·운행 방향 검증, 탑승 열차 식별, Firebase 실제 기기 수신, 권한 거부·화면 꺼짐·Doze·강제 종료·재부팅 시험, 일반 사용자 인증·영속/분산 쿼터·운영 DB·백업 복구입니다. 위치·선택한 역·FCM 토큰의 보관·삭제 정책과 로그 최소화도 필요합니다.

시험 알림에서 실제 알림으로 자동 전환하지 않습니다. 취소 전에 전송이 시작된 푸시는 도착할 수 있고, 푸시 전달 지연·누락 가능성은 기기와 네트워크에서 검증해야 합니다. 무조건 하차를 보장한다는 문구는 사용하지 않습니다.

## 8. 실행 순서와 공식 참고 자료

1. 접근 보호 통합 검증 후 개발 PC에서 Docker 백엔드 실행과 로컬 health·보호 API 거부를 재현합니다.
2. Firebase Android 설정을 넣어 앱을 재빌드하고 서버 ADC·신뢰된 HTTPS 접근을 준비합니다.
3. 개발 기기 키·요청 제한·HTTPS·비밀 전달과 회수·접속 정책을 확인한 뒤 개발용 Tunnel을 연결합니다.
4. 서울 실제 키의 HTTPS와 노선·시간·탑승 확인을 검증하고 실기기 수신을 시험합니다.
5. 로컬 PostgreSQL 등록 기록 저장을 재현하고, Supabase 운영 연결·백업·모니터링을 검증한 뒤 VPS 업체·요금·리전을 확정합니다.
6. 정식 서명·스토어 자료·위치 정책·테스트를 완료해 Google Play에 제출합니다.

공식 자료 (확인일 2026-10-27):

- Cloudflare Tunnel: https://developers.cloudflare.com/tunnel/
- 로컬 관리 터널: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/
- Android AAB 업로드: https://developer.android.com/studio/publish/upload-bundle
- Expo APK 빌드: https://docs.expo.dev/build-reference/apk/
- Expo 앱 유통: https://docs.expo.dev/distribution/introduction/
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security

실행 명령·구성 파일은 [배포 안내](deployment.md), API와 FCM은 [서버 안내](../server/README.md), 앱 설정은 [모바일 안내](../mobile/README.md)를 기준으로 합니다. 원본 첨부 PDF는 공개 저장소에 업로드하지 않습니다.

## 등록 복구 개정 (2026-10-28)

앱은 PENDING을 SecureStore에 선저장한 뒤 POST를 보내며 응답 유실·최종 저장 실패 때 같은 ID와 비밀로 조회·재시도·종료합니다. 재시도는 원래 열차 관측 60초 이내에만 POST를 허용하고 복원만으로 생성 요청을 자동 전송하지 않습니다. 기존 기록을 읽지 못하면 새 등록을 차단합니다. 자세한 HTTP 계약과 저장 모드별 보관 범위는 [등록 복구](registration-recovery.md)를 기준으로 합니다. 별도 PDF v1.1은 이 개정을 반영하지 않았습니다.

## PostgreSQL 등록 기록 개정 (2026-10-28)

`MONITOR_STORE=postgres`를 명시하면 전용 JDBC 연결로 `subway_alert_private.monitor_receipts`에 ID·두 해시·만료·감시/전송 상태만 기록합니다. FCM 토큰·역·접근 키·원문 비밀은 저장하지 않습니다. 연결 실패 시 메모리 대체는 없으며 단일 백엔드만 허용합니다. direct/session 연결만 지원하며 transaction pooler는 지원하지 않습니다. 로컬 개발용 스키마 초기화는 Supabase 운영 마이그레이션이 아닙니다. 사용자 즐겨찾기 동기화·로그인·분산 예산은 포함하지 않습니다. [운영 구분과 검증 범위](durable-receipts.md)를 참고하세요.

## 출퇴근 조건 개정 (v1.5, 2026-10-28)

즐겨찾기별 월~일 선택과 기존 요일·시간 편집을 제공합니다. 기본 평일 07:00–09:00과 기존 저장 형식을 보존하며, 최대 5개가 차도 ID·사용 여부를 유지해 수정할 수 있습니다. 시간은 기기 현지 시간이고 야간 조건은 시작 요일 기준, 종료 시각 제외입니다. 알림 마커는 시작 날짜와 시간대로 구분해 자정 중복을 억제하고, 이미 제안한 항목 때문에 다음 적격 항목이 차단되지 않게 합니다.

제안 처리 함수는 최신 상태를 마커 저장 전과 알림 직전에 다시 확인하고 JS 실행 환경 안에서 요청을 직렬화합니다. 완료된 경로의 별도 진행 기록을 반영해 다음 출퇴근 제안을 허용합니다. 마커 저장 실패 시 알리지 않고, 알림 요청 실패 후에는 같은 시간대에 자동 재시도하지 않습니다. native/OS 수신 보장이나 실제 자동 탑승·하차 판단은 아닙니다. 상세 사용법·검증·한계는 [출퇴근 조건](commute-schedules.md)에 설명합니다.

출퇴근 마커는 같은 키의 버전 이력으로 보관해 시간 조건을 바꿨다가 되돌려도 이전 소비 기록을 잊지 않습니다. 현재·전일 시작 날짜와 미래 기록을 보수적으로 남기고 오래된 과거 기록만 정리하며, 최대128개/즐겨찾기 한도나 손상 기록에는 그 항목의 새 제안을 보류합니다. 완료 진행 기록 조회 뒤에는 설정을 다시 읽어 I/O 중의 감지 중지·새 경로 시작·조건 수정을 반영합니다.

## CI/CD 개정 (v1.6, 2026-10-29)

PR·push에서 formatter/lint와 기존 테스트를 실행하고 모든 선행 성공을 요구하는 `CI gate`를 제공합니다. JavaScript는 ESLint·Prettier, Java는 Maven verify의 Spotless·PMD, Python은 Ruff, workflow는 actionlint로 검사합니다. Android는 native lintRelease와 독립 시험 APK를 빌드합니다.

동일 Docker image ID를 실행 검사한 뒤 source SHA·CI run ID·체크섬과 함께 배포 묶음으로 보관합니다. CI의 임시 Docker 환경에서 staging 배포·후보 기동 실패·자동 롤백을 검사합니다. 수동 staging CD는 성공한 main push CI 출처를 확인하고 SSH 호스트 키를 고정한 뒤 같은 이미지를 승격합니다. SAMPLE·FCM 비활성·메모리 저장소만 포함하며 실제 운영 DB·FCM·서울 실키 배포는 아닙니다.

main 병합 차단과 environment 승인 규칙은 저장소 관리자 권한이 필요하며 현재 연결로 적용되지 않았습니다. 호스트·SSH·승인·정식 Android 서명도 미설정입니다. 상세 설정과 검증 범위는 [CI/CD 안내](cicd.md)를 따릅니다. PDF v1.1은 변경하지 않았습니다.

## CD 실행 환경 개정 (v1.7, 2026-10-29)

Linux/Docker staging 준비 도구는 private 디렉터리/.env를 만들고 기존 설정을 덮어쓰지 않습니다. GitHub environment 도구는 읽기 전용 plan을 기본으로 하고, 운영자의 관리자 gh 인증에서만 main 제한·승인자·배포 비활성 기본값을 준비합니다. SSH 전송은 별도 검증한 host pin·임시 개인 키·고정 경로를 사용하고 release.py의 이미지/배포/롤백 검증을 재사용합니다.

CD는 수동과 opt-in workflow_run 자동 실행을 지원합니다. 자동은 성공한 main push CI와 저장소 스위치, staging 활성화·승인을 요구하며 source가 현재 main인지 두 번 확인합니다. 실제 호스트/SSH·관리자 설정과 main 병합은 아직 수행하지 않았습니다. Render는 대안으로만 확인했고 계정/서비스를 생성하지 않았습니다. 최신 실행 절차와 실제 검증 범위는 [CI/CD 안내](cicd.md)를 따릅니다. 비공개 PDF v1.1은 변경하지 않았습니다.

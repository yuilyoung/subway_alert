# 지하철 하차 알림 설계·아키텍처 v1.1

개정일: 2026-10-27 (한국 시간). v1.0의 목표와 현재 구현을 분리하고 배포 책임을 구체화한 개정본입니다. 이 문서는 저장소에서 관리하는 설계 기준이며, 별도 제공 PDF도 같은 기준으로 개정합니다.

## 1. 결정 사항과 실제 상태

개발 백엔드는 개인 PC에서 Docker로 실행합니다. 개발용 HTTPS 연결 수단은 Cloudflare Tunnel로 준비합니다. 운영 형태는 상시 실행 Linux 호스트의 Docker로 정하되 VPS 업체·리전·요금은 예산 확정 전까지 미선정입니다. Android 정식 배포처는 Google Play, 기본 시험 빌드는 GitHub Actions입니다. 이는 설계 기준이며 계정·서버·도메인 생성 완료를 뜻하지 않습니다.

| 구성 | 역할 | 실제 상태 |
| --- | --- | --- |
| 개인 PC + Docker | 개발 API·스케줄러 실행 호스트 | 로컬 Java 검증, 컨테이너 설정 준비 |
| Cloudflare Tunnel | 기존 API의 HTTPS 연결 경로 | 계정·도메인·터널 미구성, 비활성 템플릿 |
| Linux VPS + Docker | 24시간 운영 백엔드 목표 | 업체·리전·요금·도메인 미선정 |
| Supabase PostgreSQL | 향후 영속 저장 | 앱 전용 프로젝트 미확정, 코드 미연동 |
| Firebase FCM | Android 원격 알림 | 코드 구현, 실제 수신 미검증 |
| GitHub Actions | 테스트와 독립 시험 APK 생성 | Artifact 작업 추가, 원격 실행 미확인 |
| Google Play | 정식 앱 설치·업데이트 유통 | 개발자 등록·심사·게시 미진행 |

Tunnel만으로 백엔드 서버가 생기지 않습니다. 호스트의 전원·네트워크·프로세스가 중단되면 API와 폴링도 중단됩니다. 앱 유통과 API 호스팅은 별개이며 Android 앱을 위해 별도 웹 파일 서버를 필수로 운영할 필요는 없습니다.

## 2. 목표 기능과 사용자 흐름

최종 목표는 출발역·목적지 직접 검색, 목적지 한 정거장 전 Android 백그라운드 알림, 최대 5개 즐겨찾기, 출퇴근 조건 감지, 빠른 환승·화장실·편의시설·개찰구·출구 정보 제공입니다. GPS와 서울 실시간 API를 함께 고려하되 GPS만으로 지하의 탑승 열차를 확정하지 않습니다.

현재 앱은 일부 2호선 5역의 데모, 즐겨찾기, 출퇴근 확인 알림, 공개 샘플 열차 조회와 TEST 감시를 제공합니다. 역 시설과 전체 노선·환승은 미구현입니다. 사용자 입력 이전역이나 단순 선택은 실제 경로 검증이 아닙니다.

개발 시험 흐름은 앱의 샘플 열차 선택 → 이전역·목적지 입력 → 네이티브 FCM 토큰 취득 → 서버 TEST 세션 생성 → 공유 샘플 조회 → 일치 사건의 시험 전송 요청 → 상태 조회·취소입니다. Firebase 설정 없는 APK에서는 토큰 취득이 실패합니다. 수동 시험 전송은 실제 열차 이동과 무관합니다.

목표 운영 흐름은 검증된 역·방향·시각과 사용자의 탑승 확인을 갖춘 후에만 활성화합니다. 서버의 LIVE 감시는 현재 거부합니다. FCM 수락과 휴대폰 표시·정시 도착은 별도 상태입니다.

## 3. 기술 구성과 v1.0 변경점

| 항목 | v1.0 목표·가정 | v1.1 현재 구현·정정 |
| --- | --- | --- |
| 백엔드 | Spring Boot / Java 21 | Spring Boot 3.4.5 / Java 17 |
| 앱 | React Native Firebase / Notifee / Kotlin | Expo 54 / React Native 0.81.5 / expo-notifications |
| DB | Supabase PostgreSQL / JPA | 서버 메모리, SQL 초안만 존재 |
| 열차 조회 | 10초 공유 폴링 | TEST 기본 120초, 활성 세션만 공유 |
| 조회 예산 | 별도 제한 설명 없음 | 프로세스당 서울 날짜 하루 600회, 조회 API는 별도 |
| 지연 보정 | 경과 시간을 역 이동으로 환산 | 고정 시간으로 위치를 추정하지 않음 |
| 알림 | 실제 직전역 출발 FCM | TEST만 허용, 실제 Firebase·기기 미검증 |
| 비용 | 소규모 운영 무료로 서술 | 호스트·도메인·전기·가용성·사용량 별도 고려 |

원래 문서의 확정되지 않은 RLS 비활성화 권장은 폐기합니다. 공개 스키마는 RLS와 최소 권한을 함께 적용하는 것이 목표입니다. 서버 전용 특권과 앱 사용자 권한을 분리하며 비밀 키를 앱에 넣지 않습니다. DB 적용·RLS 동작 테스트는 아직 없습니다.

## 4. 서버 API와 데이터·알림 경계

| 경로 | 현재 역할 | 주의점 |
| --- | --- | --- |
| GET /api/health | 개발 서버 상태 | mode DEMO, 운영 준비 판정 아님 |
| GET /api/live/trains?line=2 | 서울 열차 조회 | sample 최대 5건, 전체 운행 아님 |
| POST /api/monitor-sessions | TEST 세션 생성 | LIVE 거부, 앱 사용자 인증과 별개 |
| GET /api/monitor-sessions/{id} | 상태 확인 | X-Session-Token 소유권 필요 |
| DELETE /api/monitor-sessions/{id} | 취소 | 발송이 시작된 FCM 회수 불가 |
| POST /api/monitor-sessions/{id}/test | 수동 시험 전송 | 실제 열차 위치와 무관 |

기존 /api/track과 demo-event는 독립 모의 엔진이며 실제 내선·외선과 연결하지 않습니다. TEST 감시는 고정 공개 샘플 제공자를 사용해 실제 API 키를 보내지 않습니다. 조회용 LIVE 키는 HTTPS로만 전송하지만 연결은 미검증입니다.

일치 검사는 노선·열차번호 문자열·방향·직전역·출발 상태·세션 시작 이후 관측·60초 신선도·급행 제외를 확인합니다. 서울 시각 해석은 실측 추정이므로 아직 운영 검증으로 인정하지 않습니다. 샘플 매칭 후 SAMPLE_MATCHED로 끝내 추가 폴링을 중단합니다.

세션은 최대 500개, 2시간 만료이며 메모리에만 있습니다. FCM은 높은 우선순위·30초 TTL·시험 표식을 사용합니다. 재시작하면 세션·프로세스별 예산이 초기화됩니다. 등록 응답 유실 시 멱등성이 없어 중복 TEST 세션이 남을 수 있습니다.

## 5. 개발 실행·Tunnel·운영 호스트

저장소의 compose.yaml은 백엔드 컨테이너를 호스트의 127.0.0.1:8080에만 연결합니다. 컨테이너 내부에서는 Spring Boot가 0.0.0.0에 바인딩되어야 합니다. Dockerfile은 Maven 빌드 단계와 Java 17 실행 단계를 나누고 비관리자 사용자로 실행합니다. 기본 sample·FCM 비활성 구성을 유지합니다.

Cloudflare Tunnel 설정 예제는 모든 요청을 404로 종료하는 비활성 상태입니다. 실행 중인 별도 cloudflared가 호스트의 localhost API로 연결하는 구조만 문서화하며, 터널 생성·DNS 등록·외부 노출은 수행하지 않습니다. 컨테이너 안의 localhost와 호스트의 localhost를 혼동하지 않습니다.

터널 공개 전에는 사용자 인증·등록 권한·통합 호출 제한·비밀 관리·신뢰된 기기 접근을 구현해야 합니다. 세션 토큰은 생성 이후 소유권만 확인하므로 현재 무인증 등록·조회 API를 인터넷에 공개해서는 안 됩니다. 공유 서비스 토큰을 APK에 내장하는 방식도 사용하지 않습니다.

운영은 상시 실행 Linux 호스트에서 컨테이너와 재시작·로그·상태 감시를 관리하는 방향입니다. 스케줄러가 필요한 현재 구조는 유휴 시 중단되는 실행 환경에 그대로 배치하지 않습니다. 공급자·리전·예산·SLA는 사용자 선택 전까지 미확정이며, 유료 자원은 이번 작업에서 만들지 않습니다.

## 6. Android 빌드·앱 유통·비밀 설정

개발 실행은 Metro가 필요한 환경이고, 독립 시험 APK는 JavaScript를 내장한 ARM64 설치 파일입니다. CI는 release 변형으로 빌드하되 Expo 생성 Debug 키로 서명하므로 시험 전용입니다. 워크플로는 APK·체크섬·안내를 Artifact로 14일 보관하며 Play에 자동 게시하지 않습니다.

정식 배포는 업로드 키로 서명한 AAB를 Play Console에 제출하는 경로로 정합니다. 개발자 계정·Firebase 설정·정식 서명·개인정보 처리방침·데이터 안전·위치 권한 설명·스토어 테스트와 심사는 미진행입니다. EAS Build/Submit은 향후 선택 가능한 빌드·제출 도구이며 운영 API 호스팅을 대신하지 않습니다.

| 값 | 위치·용도 | 현재 상태 |
| --- | --- | --- |
| GOOGLE_SERVICES_JSON | 앱 빌드의 Firebase Android 설정 경로 | 파일 미제공, 재빌드 필요 |
| FIREBASE_PROJECT_ID / ADC | 백엔드 FCM 인증 | 실제 키·기기 미검증 |
| FCM_ENABLED | 서버 FCM 명시 활성화 | 기본 비활성 |
| SEOUL_SUBWAY_KEY | 서버 조회용 실제 키 | HTTPS 실측 미검증 |
| 터널 자격 증명 / 정식 업로드 키 | 운영자·빌드 비밀 저장소 | 미구성 |

앱 세션 토큰은 SecureStore에 보관합니다. FCM 토큰 갱신·앱 재시작 시 기존 시험 감시 취소를 시도하며 실패하면 정보를 보존합니다. 서버 서비스 계정 개인 키를 google-services.json과 혼동하지 않습니다.

## 7. 검증 결과와 출시 차단 조건

기존 검증은 서버 테스트 33개·모바일 테스트 21개 통과, 가짜 제공자·가짜 FCM을 사용한 등록·매칭·상태·취소 통합 검사, 실제 서울 공개 샘플 5건 조회, 독립 ARM64 APK 빌드·JS 포함·서명 검사입니다. 이는 실제 사용자 하차 알림 검증이 아닙니다.

이번 작업은 README·설계 개정, Docker/Compose 로컬 실행 구성, 비활성 Tunnel 예제, CI 시험 APK Artifact 추가입니다. Compose 구성 해석은 Docker 엔진 없이 검증할 수 있지만 이미지 빌드·컨테이너 실행·원격 CI·터널·Play 게시의 성공과 동일하지 않습니다. 최종 작업 보고에서 실행 여부를 별도로 기록합니다.

운영 활성화 조건은 실제 HTTPS API와 데이터 시간대·역 순서·운행 방향 검증, 탑승 열차 식별, Firebase 실제 기기 수신, 권한 거부·화면 꺼짐·Doze·강제 종료·재부팅 시험, 인증·쿼터·영속 저장·복구입니다. 위치·선택한 역·FCM 토큰의 보관·삭제 정책과 로그 최소화도 필요합니다.

시험 알림에서 실제 알림으로 자동 전환하지 않습니다. 취소 전에 전송이 시작된 푸시는 도착할 수 있고, 푸시 전달 지연·누락 가능성은 기기와 네트워크에서 검증해야 합니다. 무조건 하차를 보장한다는 문구는 사용하지 않습니다.

## 8. 실행 순서와 공식 참고 자료

1. 개발 PC에서 Docker 백엔드 실행과 로컬 health 응답을 재현합니다.
2. Firebase Android 설정을 넣어 앱을 재빌드하고 서버 ADC·신뢰된 HTTPS 접근을 준비합니다.
3. API 인증·요청 제한·기기 접근 정책을 갖춘 뒤 개발용 Tunnel을 연결합니다.
4. 서울 실제 키의 HTTPS와 노선·시간·탑승 확인을 검증하고 실기기 수신을 시험합니다.
5. DB 영속 저장·중복 등록 방지·재시작 복구·모니터링 후 VPS 업체·요금·리전을 확정합니다.
6. 정식 서명·스토어 자료·위치 정책·테스트를 완료해 Google Play에 제출합니다.

공식 자료 (확인일 2026-10-27):

- Cloudflare Tunnel: https://developers.cloudflare.com/tunnel/
- 로컬 관리 터널: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/
- Android AAB 업로드: https://developer.android.com/studio/publish/upload-bundle
- Expo APK 빌드: https://docs.expo.dev/build-reference/apk/
- Expo 앱 유통: https://docs.expo.dev/distribution/introduction/
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security

실행 명령·구성 파일은 [배포 안내](deployment.md), API와 FCM은 [서버 안내](../server/README.md), 앱 설정은 [모바일 안내](../mobile/README.md)를 기준으로 합니다. 원본 첨부 PDF는 공개 저장소에 업로드하지 않습니다.

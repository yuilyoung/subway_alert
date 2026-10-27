# 서버: 개발용 데모

Spring Boot 3 / Java 17. PDF의 Java 21과 달리 현재 개발 환경에서 사용할 수 있는 Java 17을 사용한다. Maven이 설치된 환경에서 `mvn -f server/pom.xml test` 및 `mvn -f server/pom.xml spring-boot:run`으로 실행한다. 기본 바인딩은 `127.0.0.1:8080`이다.

이 서버는 **실제 위치 추적이나 알림 서버가 아니다.** 서울 API의 공개 샘플 조회 기능은 있지만 실키 HTTPS 통신은 검증되지 않았다. 시험용 샘플 폴링과 FCM 발송 경로는 구현됐으나 실제 자격 증명과 기기로 검증되지 않았다. Supabase/Postgres, 지속 저장 및 사용자 계정은 연동되지 않았다. 재시작 시 모든 세션이 사라진다. 2호선의 강남·역삼·선릉·삼성 네 역과 UP/DOWN 방향은 프로그램 검증용 샘플이며 순환선 전체, 환승, 급행, 실제 운행 방향을 나타내지 않는다. 실기기 앱과 서버의 엔드투엔드 연결도 확인되지 않았다.

서울 열린데이터광장 [실시간 열차 위치 API](https://data.seoul.go.kr/dataList/datasetView.do?infId=OA-12601&serviceKind=1&srvType=A)는 인증키가 필요하다. 공식 예시에는 평문 HTTP가 기재돼 있다. 공개 샘플키만 HTTP로 보내며 실제 발급 키는 HTTPS로만 전송하도록 구현했다. 이 개발 환경에서는 HTTPS 연결이 검증되지 않아 실제 키 연동은 미검증이다. 실제 연동 시 TLS 및 데이터 시각·시간대·방향·열차 식별을 실측으로 검증해야 한다. 열차번호 선택만으로 사용자의 탑승 여부가 증명되지는 않는다.

## 모의 API

- `GET /api/health`, `GET /api/lines`, `GET /api/stations/2`: 상태 및 샘플 목록
- `POST /api/track`: `{ "lineId":"2", "direction":"UP", "boardingStation":"강남", "destinationStation":"삼성", "trainId":"1234" }` → `id`, `status`, `previousStation`, `sessionToken`, `dataMode`. UP은 위 순서이며 DOWN은 역순이다.
- `GET /api/track/{id}/status`, `DELETE /api/track/{id}`: `X-Session-Token` 헤더가 필요하다.
- `POST /api/track/{id}/demo-event`: 같은 헤더와 `{ "lineId":"2", "direction":"UP", "trainId":"1234", "station":"선릉", "state":"DEPARTED", "observedAt":"현재 ISO-8601 UTC 시각" }`를 보내 매칭을 시뮬레이션한다. 상태 변경만 되며 휴대폰 알림은 발생하지 않는다. 세션 시작 이전, 60초를 초과한 과거, 5초를 초과한 미래 이벤트, 다른 열차·방향, 중복 이벤트는 거부한다.

세션 토큰은 임시 랜덤 소유권 검증 수단이며 로그인이나 프로덕션 보안 설계를 대체하지 않는다. 이 모의 서버를 인터넷에 공개하지 말 것. 정식 운영 전 사용자 인증, 접근 제어·속도 제한, 신뢰할 수 있는 저장소와 보안 설정, 추적 실패 복구, FCM 전송 확인 및 실제 기기 테스트가 필요하다.

## 서울시 열차 위치 조회 (연동 개발 단계)

`GET /api/live/trains?line=2`는 서울시 `realtimePosition`을 서버에서 읽습니다. 환경 변수 `SEOUL_SUBWAY_KEY`가 없으면 서울시 공개 `sample` 키를 사용하며 공식 HTTP 예제 주소로 최대 **5행만** 조회합니다. 샘플은 전체 운행 목록이 아닙니다. `SAMPLE` / `LIVE`가 응답에 표시됩니다. 실제 키를 설정하면 고정된 서울시 호스트의 HTTPS로만 전송하며 키는 앱·로그·응답에 포함되지 않습니다. 이 실행 환경에서 서울시 HTTPS 연결이 타임아웃되어 **실제 키의 연결과 응답은 검증하지 못했습니다**. 오류 시 HTTP로 자동 전환하지 않습니다.

응답에는 열차번호, 역, 방향(서울 원본의 내선/외선), 상태, 수신시각, 급행 여부, 60초 이내 데이터인지 나타내는 `fresh`가 있습니다. 시각은 실측으로 서울 시간대라고 추정해 변환한 것으로 공식 명세상의 시간대 보증이 확인되지 않았습니다. API 데이터만으로 사용자가 실제 그 열차를 탔는지 확인할 수 없으며, 목록은 실제 하차 추적에 사용되지 않습니다. 별도 TEST 세션은 공개 샘플과 시험 알림으로만 연결됩니다. 열차 위치의 신선도나 도착 알림의 정확성을 보장하지 않습니다.

서버는 기본 `127.0.0.1`에만 바인딩되며, 이 조회 API에 사용자 인증·요청 제한·공유 캐시가 없습니다. 운영용으로 인터넷에 공개하면 API 할당량이 소진될 수 있으므로 인증, 속도 제한, 캐싱, 안전한 HTTPS 배포가 구현되기 전에는 공개하지 마세요. 인증키는 Git이나 모바일 앱에 저장하지 마세요.

## TEST 세션과 FCM 시험 알림

이 경로는 실제 열차 탑승 여부와 실제 하차역을 판정하지 않습니다. 서버는 `mode=TEST`만 받아들이며 `LIVE` 세션을 거부합니다. 서울시 샘플은 일부 5건뿐이고 이전역·방향·시각은 검증되지 않았습니다. 시험 알림에는 `[시험]`과 실제 열차 위치와 무관하다는 문구가 들어갑니다.

- `POST /api/monitor-sessions`: JSON에 `lineId` (`2`), `trainId` (문자열), `direction` (`INNER` 또는 `OUTER`), `previousStation`, `destinationStation`, `fcmToken`, `mode` (`TEST`)를 포함합니다. 응답은 `id`, 일회 확인용 `sessionToken`, `status`, `mode`, `expiresAt`입니다.
- `GET /api/monitor-sessions/{id}`, `DELETE /api/monitor-sessions/{id}`: `X-Session-Token` 헤더로 소유 세션만 조회·취소합니다. 조회 응답에 토큰은 없습니다.
- `POST /api/monitor-sessions/{id}/test`: 위 헤더로 명시적 시험 알림을 보냅니다. 세션당 30초, 프로세스 전체 분당 30회로 제한하며 자동 매칭과 별도입니다.
- 세션 `status`는 `TRACKING`, `SAMPLE_MATCHED`, `CANCELLED`, `EXPIRED`입니다. 샘플 매칭 후 해당 세션의 폴링은 중지됩니다. `deliveryStatus`는 `NONE`, `SENDING`, `FCM_ACCEPTED`, `UNAVAILABLE`, `FAILED`이며 전송 실패를 자동 재시도하지 않습니다. `FCM_ACCEPTED`는 Firebase의 요청 수락만 뜻하며 기기 도착·표시를 보장하지 않습니다.
- 앱에서 생성 요청이 서버에 도착했으나 응답을 잃으면 토큰을 복구할 수 없습니다. 요청 재시도는 중복 세션을 만들 수 있으며 기존 세션은 최대 2시간 후 만료됩니다. 멱등성 및 중복 방지는 미구현입니다.

스케줄러는 활성 TEST 세션이 있을 때만 서울시 공개 `sample`을 공유해 기본 120초 간격으로 조회하고, 이 프로세스 기준 서울 날짜 하루에 최대 600회 요청합니다. 한 폴링당 전송 시도는 최대 10건입니다. 한도는 프로세스 메모리에만 존재해 재시작하면 초기화되며 `/api/live/trains` 등 다른 API 호출은 계산하지 않습니다. 다중 인스턴스·장애 재시작을 포함한 운영 쿼터 제어가 아니므로 외부에 공개해서는 안 됩니다. 모든 세션은 메모리에만 있고 서버 재시작 시 사라집니다.

FCM 사용을 위해 `FCM_ENABLED=true`, `FIREBASE_PROJECT_ID`, 서버 ADC 자격 증명을 설정해야 합니다. 예를 들어 서비스 계정의 비밀 JSON을 서버에 안전하게 저장하고 `GOOGLE_APPLICATION_CREDENTIALS`에 파일 경로만 지정할 수 있습니다. 앱에 필요한 `google-services.json`은 별개이며 비밀 서비스 계정 키를 앱이나 저장소에 넣지 마세요. 설정이 없거나 초기화가 실패하면 시험 요청은 `UNAVAILABLE`로 표시합니다. 이 개발 환경에서는 실제 Firebase 프로젝트·기기 자격 증명이 없어 FCM 발송·기기 수신을 검증하지 않았습니다.

취소 시 이미 네트워크 전송 중인 FCM 요청은 회수할 수 없습니다. 응답에서 `CANCELLED`와 `SENDING`이 함께 보이거나, 취소한 뒤 시험 알림이 도착할 수 있습니다. FCM 메시지는 30초 TTL로 전송하지만 지연이나 수신 보장을 의미하지 않습니다. 실제 제품에는 검증된 경로 데이터, 신뢰할 수 있는 발송·복구 정책, 영속 저장 및 기기 테스트가 필요합니다.

# 서버: 개발용 데모

Spring Boot 3 / Java 17. PDF의 Java 21과 달리 현재 개발 환경에서 사용할 수 있는 Java 17을 사용한다. Maven이 설치된 환경에서 `mvn -f server/pom.xml test` 및 `mvn -f server/pom.xml spring-boot:run`으로 실행한다. 기본 바인딩은 `127.0.0.1:8080`이다.

이 서버는 **실제 위치 추적이나 알림 서버가 아니다.** 서울 API의 공개 샘플 조회 기능은 있지만 실키 HTTPS 통신은 검증되지 않았다. FCM, Supabase/Postgres, 스케줄러, 지속 저장 및 사용자 계정은 연동되지 않았다. 재시작 시 모든 세션이 사라진다. 2호선의 강남·역삼·선릉·삼성 네 역과 UP/DOWN 방향은 프로그램 검증용 샘플이며 순환선 전체, 환승, 급행, 실제 운행 방향을 나타내지 않는다. 실기기 앱과 서버의 엔드투엔드 연결도 확인되지 않았다.

서울 열린데이터광장 [실시간 열차 위치 API](https://data.seoul.go.kr/dataList/datasetView.do?infId=OA-12601&serviceKind=1&srvType=A)는 인증키가 필요하다. 공식 예시에는 평문 HTTP가 기재돼 있다. 공개 샘플키만 HTTP로 보내며 실제 발급 키는 HTTPS로만 전송하도록 구현했다. 이 개발 환경에서는 HTTPS 연결이 검증되지 않아 실제 키 연동은 미검증이다. 실제 연동 시 TLS 및 데이터 시각·시간대·방향·열차 식별을 실측으로 검증해야 한다. 열차번호 선택만으로 사용자의 탑승 여부가 증명되지는 않는다.

## 모의 API

- `GET /api/health`, `GET /api/lines`, `GET /api/stations/2`: 상태 및 샘플 목록
- `POST /api/track`: `{ "lineId":"2", "direction":"UP", "boardingStation":"강남", "destinationStation":"삼성", "trainId":"1234" }` → `id`, `status`, `previousStation`, `sessionToken`, `dataMode`. UP은 위 순서이며 DOWN은 역순이다.
- `GET /api/track/{id}/status`, `DELETE /api/track/{id}`: `X-Session-Token` 헤더가 필요하다.
- `POST /api/track/{id}/demo-event`: 같은 헤더와 `{ "lineId":"2", "direction":"UP", "trainId":"1234", "station":"선릉", "state":"DEPARTED", "observedAt":"현재 ISO-8601 UTC 시각" }`를 보내 매칭을 시뮬레이션한다. 상태 변경만 되며 휴대폰 알림은 발생하지 않는다. 세션 시작 이전, 60초를 초과한 과거, 5초를 초과한 미래 이벤트, 다른 열차·방향, 중복 이벤트는 거부한다.

세션 토큰은 임시 랜덤 소유권 검증 수단이며 로그인이나 프로덕션 보안 설계를 대체하지 않는다. 이 모의 서버를 인터넷에 공개하지 말 것. 정식 운영 전 사용자 인증, 접근 제어·속도 제한, 신뢰할 수 있는 저장소와 보안 설정, 추적 실패 복구, FCM 전송 확인 및 실제 기기 테스트가 필요하다.

## 서울시 열차 위치 조회 (연동 개발 단계)

`GET /api/live/trains?line=2`는 서울시 `realtimePosition`을 서버에서 읽습니다. 환경 변수 `SEOUL_SUBWAY_KEY`가 없으면 서울시 공개 `sample` 키를 사용하며 공식 HTTP 예제 주소로 최대 **5행만** 조회합니다. 샘플은 전체 운행 목록이 아닙니다. `SAMPLE` / `LIVE`가 응답에 표시됩니다. 실제 키를 설정하면 고정된 서울시 호스트의 HTTPS로만 전송하며 키는 앱·로그·응답에 포함되지 않습니다. 이 실행 환경에서 서울시 HTTPS 연결이 타임아웃되어 **실제 키의 연결과 응답은 검증하지 못했습니다**. 오류 시 HTTP로 자동 전환하지 않습니다.

응답에는 열차번호, 역, 방향(서울 원본의 내선/외선), 상태, 수신시각, 급행 여부, 60초 이내 데이터인지 나타내는 `fresh`가 있습니다. 시각은 실측으로 서울 시간대라고 추정해 변환한 것으로 공식 명세상의 시간대 보증이 확인되지 않았습니다. API 데이터만으로 사용자가 실제 그 열차를 탔는지 확인할 수 없으며, 목록은 데모 추적 세션이나 FCM 발송과 연결되지 않습니다. 열차 위치의 신선도나 도착 알림의 정확성을 보장하지 않습니다.

서버는 기본 `127.0.0.1`에만 바인딩되며, 이 조회 API에 사용자 인증·요청 제한·공유 캐시가 없습니다. 운영용으로 인터넷에 공개하면 API 할당량이 소진될 수 있으므로 인증, 속도 제한, 캐싱, 안전한 HTTPS 배포가 구현되기 전에는 공개하지 마세요. 인증키는 Git이나 모바일 앱에 저장하지 마세요.

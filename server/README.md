# 서버: 개발용 데모

Spring Boot 3 / Java 17. PDF의 Java 21과 달리 현재 개발 환경에서 사용할 수 있는 Java 17을 사용한다. Maven이 설치된 환경에서 `mvn -f server/pom.xml test` 및 `mvn -f server/pom.xml spring-boot:run`으로 실행한다. 기본 바인딩은 `127.0.0.1:8080`이다.

이 서버는 **실제 위치 추적이나 알림 서버가 아니다.** 서울 API, FCM, Supabase/Postgres, 스케줄러, 지속 저장 및 사용자 계정은 연동되지 않았다. 재시작 시 모든 세션이 사라진다. 2호선의 강남·역삼·선릉·삼성 네 역과 UP/DOWN 방향은 프로그램 검증용 샘플이며 순환선 전체, 환승, 급행, 실제 운행 방향을 나타내지 않는다. 실기기 앱과 서버의 엔드투엔드 연결도 확인되지 않았다.

서울 열린데이터광장 [실시간 열차 위치 API](https://data.seoul.go.kr/dataList/datasetView.do?infId=OA-12601&serviceKind=1&srvType=A)는 인증키가 필요하다. 공식 예시에는 평문 HTTP가 기재돼 있고 이 개발 환경에서 HTTPS 지원을 확인하지 못했으므로 키를 전송하는 호출은 구현하지 않았다. 실제 연동 시 TLS 및 데이터 시각·시간대·방향·열차 식별을 실측으로 검증해야 한다. 열차번호 선택만으로 사용자의 탑승 여부가 증명되지는 않는다.

## 모의 API

- `GET /api/health`, `GET /api/lines`, `GET /api/stations/2`: 상태 및 샘플 목록
- `POST /api/track`: `{ "lineId":"2", "direction":"UP", "boardingStation":"강남", "destinationStation":"삼성", "trainId":"1234" }` → `id`, `status`, `previousStation`, `sessionToken`, `dataMode`. UP은 위 순서이며 DOWN은 역순이다.
- `GET /api/track/{id}/status`, `DELETE /api/track/{id}`: `X-Session-Token` 헤더가 필요하다.
- `POST /api/track/{id}/demo-event`: 같은 헤더와 `{ "lineId":"2", "direction":"UP", "trainId":"1234", "station":"선릉", "state":"DEPARTED", "observedAt":"현재 ISO-8601 UTC 시각" }`를 보내 매칭을 시뮬레이션한다. 상태 변경만 되며 휴대폰 알림은 발생하지 않는다. 세션 시작 이전, 60초를 초과한 과거, 5초를 초과한 미래 이벤트, 다른 열차·방향, 중복 이벤트는 거부한다.

세션 토큰은 임시 랜덤 소유권 검증 수단이며 로그인이나 프로덕션 보안 설계를 대체하지 않는다. 이 모의 서버를 인터넷에 공개하지 말 것. 정식 운영 전 사용자 인증, 접근 제어·속도 제한, 신뢰할 수 있는 저장소와 보안 설정, 추적 실패 복구, FCM 전송 확인 및 실제 기기 테스트가 필요하다.

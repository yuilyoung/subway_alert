# API contract

기본 경로 `/api`. JSON 요청/응답. 공개 조회: health, lines, stations, station, routes.
`/api/track*`는 live에서 `Authorization: Bearer <Firebase ID token>`을 요구합니다.
FCM token은 인증 자격증명이 아닙니다. demo 프로필에서만 `X-Demo-User: <install UUID>`를 받습니다.

| Method | Path | 동작 |
|---|---|---|
| GET | /health | mode(DEMO/LIVE), catalogReady |
| GET | /lines | 호선과 방향 코드/표시명 |
| GET | /stations/search?q=…&lineId=… | 역명 부분 검색, 최대 100개 |
| GET | /stations/{lineId} | 호선 역 조회, 최대 100개 (검색으로 범위 축소) |
| GET | /stations/nearby?latitude=…&longitude=… | 1km 이내 최대 10개 역 |
| GET | /station/{id} | 역, 출처가 있는 시설 배열, 정보 공백 안내 |
| GET | /routes?lineId=…&direction=…&from=…&to=… | 검증된 동일 호선 방향 그래프 경로 |
| POST | /track | WAITING_BOARDING 생성; Idempotency-Key 대신 body.idempotencyKey 사용 |
| GET | /track/active | {session: 객체 또는 null} |
| GET | /track/{id}/status | 소유자의 세션 상태/현재 관측/남은 역 |
| GET | /track/{id}/candidates | 출발역·방향·최신성·일반열차·종착역 검증을 통과한 열차 |
| POST | /track/{id}/board | {trainNo} 명시적 탑승 확인 |
| DELETE | /track/{id} | 취소 및 미발송 outbox 취소 |
| PUT | /track/device-token | {fcmToken} 활성 세션의 토큰 갱신 |

## 시작 요청 (로컬 데모)
```json
{
  "lineId": "DEMO",
  "direction": "0",
  "boardingStationId": "demo-a",
  "destinationStationId": "demo-d",
  "fcmToken": "DEMO",
  "idempotencyKey": "manual-example-1"
}
```

다른 소유자의 세션은 404. 다른 경로로 idempotencyKey를 재사용하거나 활성 추적이 있으면 409.
입력 오류는 400, 인증 오류는 401, 호출 제한은 429, 실시간 원본 장애는 503.
사용자당 활성 세션 1개, 시간당 새 생성 20개. 탑승 대기 15분, 추적 4시간, 완료 이력 7일.

## 상태와 전달 보장
WAITING_BOARDING → TRACKING → ALERT_PENDING → ALERTED.
취소/시간 초과/영구 발송 실패는 CANCELLED/EXPIRED/FAILED.
ALERTED는 **서버의 FCM 전송 승인**이지 기기 수신 확인이 아닙니다.
DEMO에서는 Firebase를 호출하지 않고 `DEMO_ACCEPTED_NOT_DELIVERED`로 기록합니다.
직전역을 놓치고 목적지 관측부터 확인되면 `alertKind=LATE`로 구분합니다.

## 관측 규칙
동일 trainNo+lineId+direction만 사용. 90초 초과 자료, 10초 초과 미래 자료, 역행/중복 시각을 무시합니다.
일반열차만 지원하고 종착역 경로가 목적지를 통과해야 선택할 수 있습니다.
TOPIS 필드: subwayId, trainNo, updnLine, statnId, statnTid, trainSttus, recptnDt, directAt.
`trainSttus` 0/1/2를 진입/도착/출발로 처리하고 그 외 값은 추정하지 않습니다.
키가 제공되지 않아 실제 응답 계약은 아직 실서비스에서 검증하지 않았습니다.

## 멀티 인스턴스 운영 주의
세션 생성/진행과 outbox 임대는 DB로 보호합니다. TOPIS 캐시/일일 호출 예산은 프로세스 로컬입니다.
따라서 이 MVP는 서버 1개 인스턴스로 운영해야 합니다. 수평 확장 전 분산 폴링 리더/공유 호출 예산을 추가하세요.

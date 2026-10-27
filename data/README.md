# 실사용 역·시설 데이터

데모선은 `DemoData.java`에서만 생성됩니다. 실제 서울 역/시설로 위장한 샘플은 포함하지 않습니다.
실사용에는 서울 열린데이터광장 등 사용 허가된 자료를 정규화한 JSON이 필요합니다.

## 출처 후보 (자동 연동 완료를 의미하지 않음)
- 실시간 열차 위치: https://www.data.go.kr/data/15058569/openapi.do
- 역사명·좌표: https://data.seoul.go.kr/dataList/OA-21232/A/1/datasetView.do
- 화장실·개찰구·출구·빠른환승은 운영기관별 별도 자료가 필요합니다. TOPIS 실시간 위치 API가 모든 시설 정보를 제공한다고 가정하지 않습니다.

## JSON 계약
루트: `{ "version": 1, "lines": [], "stations": [], "edges": [], "facilities": [] }`

| 배열 | 필수 필드 |
|---|---|
| lines | id(TOPIS 4자리 호선 ID), name, topisName, upLabel(방향 0), downLabel(방향 1) |
| stations | id(앱 ID), lineId, topisId(실시간 위치 API의 statnId), name, latitude, longitude, source, sourceUrl, verifiedAt |
| edges | lineId, direction("0" 또는 "1"), from(앱 역 ID), to(앱 역 ID) |
| facilities | stationId, kind, title, location, sourceUrl, verifiedAt |

좌표를 모르면 두 값 모두 null로 둡니다. 해당 역의 지오펜스 자동 시작은 허용되지 않습니다.
시설 종류는 `TRANSFER`, `TOILET`, `AMENITY`, `GATE`, `EXIT`입니다.
빠른 환승에는 `carDoor`(예: 3-2), `direction`, `transferLine`을 함께 넣어야 합니다.
`gateSide`는 검증된 개찰구 안/밖 설명을 담는 선택 필드입니다.
`verifiedAt`은 시간대가 있는 ISO 8601 시각, `sourceUrl`은 HTTPS 출처여야 합니다.

**역 이름·운영기관 역 코드·TOPIS statnId를 동일한 식별자라고 가정하지 마세요.**
분기와 순환선의 연결은 명시적인 방향 그래프입니다. 역 번호 정렬로 경로를 만들지 않습니다.
급행은 이번 구현에서 제외합니다. 데이터의 유효성 검사는 출처의 사실 검증을 대신하지 않습니다.

## 검증과 적재
```bash
python tools/import_catalog.py /private/path/catalog.json --validate-only
python -m pip install 'psycopg[binary]>=3.2,<4'
# DATABASE_URL은 비밀 환경변수로 설정 (JDBC URL이 아닌 postgresql:// URL)
python tools/import_catalog.py /private/path/catalog.json --apply
```

Flyway 마이그레이션을 먼저 실행하세요. `--apply`는 한 트랜잭션으로 적용합니다.
**제공한 호선의 연결 그래프와 제공한 역의 시설 목록을 교체**하므로 완전한 스냅샷만 적용하세요.
다른 호선은 변경하지 않습니다. 초기 운영에서는 서버를 중지하고 적재·검증한 뒤 재시작하세요.
실제 API 응답의 노선·방향·역 ID·종착역·급행 구분을 대조한 후 사용자 추적을 허용해야 합니다.

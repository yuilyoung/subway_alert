# TEST 감시 등록 기록 영속 저장

PR #5의 응답 유실 복구는 서버 메모리 안에서만 유효하다. 이번 변경은 외부 계정 없이 실행하는 선택형 PostgreSQL 저장으로 서버 재시작 후에도 ID·취소 표식·원래 만료시각을 보존한다. 기본 실행은 기존 메모리 모드다. 실제 Supabase 프로젝트·Tunnel·FCM·LIVE 감시를 활성화하지 않는다.

## 동작과 범위

- `MONITOR_STORE=memory`(기본) 또는 `postgres`. postgres는 `MONITOR_DB_URL`, `MONITOR_DB_USER`, `MONITOR_DB_PASSWORD`가 모두 필요하며 오설정·연결 실패 시 메모리로 대체하지 않고 시작에 실패한다.
- 별도 비공개 `subway_alert_private.monitor_receipts` 테이블에 UUID, 세션 비밀 SHA-256, 요청 fingerprint SHA-256, 원래 만료시각, 감시 상태, 전송 상태만 저장한다. FCM 토큰·역·API 키·원문 세션 비밀을 저장하지 않는다. RLS와 PUBLIC 권한 회수를 적용한다. Supabase 사용자 데이터 초안과 분리한다.
- 최대 500개, 세션 2시간 + 만료 후 1시간 보관 정책을 유지한다. 저장 성공 뒤에만 등록·취소 성공을 응답하고 전송 전에 SENDING 기록을 저장한다.
- 시작 시 단일 DB 세션의 advisory lock으로 단일 백엔드를 강제한다. 같은 DB의 두 번째 백엔드는 시작에 실패한다. direct 또는 session 연결만 지원하며 transaction pooler는 지원하지 않는다. 분산 감시 구현으로 설명하지 않는다.
- 복원 시 TRACKING은 CANCELLED(이미 만료했다면 EXPIRED), SENDING은 UNKNOWN으로 바꾼다. 감시·FCM 토큰을 복원하거나 자동 재전송하지 않는다. 같은 등록 재시도는 현재 종료 상태와 원래 만료시각을 반환한다.
- 저장 실패가 관측되면 프로세스의 감시 API는 503으로 닫고 이후 폴링·전송을 시작하지 않는다. 자동 재접속하지 않으며 DB 복구 후 백엔드를 다시 시작해야 한다. 이미 시작한 FCM은 회수할 수 없다. health는 기존 liveness이며 저장 준비 판정이 아니다.
- 쿼터·즐겨찾기·사용자 인증·기존 독립 demo 엔진은 이번 DB 저장 범위가 아니다. 보관 기한을 넘으면 중복 억제 기록도 삭제된다. 로컬 볼륨은 백업이 아니다.

## 검증

기존 전체 테스트에 복원·취소 선행·원래 만료·비밀 불일치·저장 실패·전송 전 저장·불확실 전송 상태 검사를 추가한다. 실제 PostgreSQL과 패키징 JAR의 HTTP 테스트로 재시작, 단일 실행 잠금, 장애 후 503, 비밀 미저장, RLS를 확인한다. 로컬 실행 결과와 CI 결과를 구분해서 보고한다.

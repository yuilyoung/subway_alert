# TEST 등록 기록 저장과 서버 재시작

선택형 PostgreSQL 저장은 등록 응답 유실 복구를 서버 재시작 뒤에도 유지합니다. 진행 중인 감시는 재시작 시 종료하며 자동 재개하거나 알림을 재전송하지 않습니다. 실제 하차 알림·Firebase 수신·Supabase 운영 연결을 완료했다는 의미는 아닙니다.

## 저장 모드

| 설정 | 기록 위치 | 재시작 후 | 필요한 외부 계정 |
| --- | --- | --- | --- |
| MONITOR_STORE=memory 또는 미설정 | 서버 메모리 | 기록 소실 | 없음 |
| MONITOR_STORE=postgres | 지정 PostgreSQL | 원래 ID·만료·취소 기록 복원, 진행 중 감시 종료 | 로컬 Compose는 없음 |
| Supabase 운영 DB | 향후 운영 연결 대상 | 운영 마이그레이션·권한·백업 검증 필요 | 프로젝트와 서버 전용 DB 자격 증명, 아직 미확정 |

PostgreSQL 모드에서 연결 실패나 잘못된 설정을 메모리 모드로 대체하지 않습니다. 앱은 DB에 직접 연결하지 않으며 서버의 API 접근 키와 세션 비밀을 계속 사용합니다. 일반 사용자 로그인과 즐겨찾기 클라우드 동기화는 포함하지 않습니다.

## 로컬 Compose 실행

저장소 루트에서 Docker Engine 28 이상, Compose v2 이상과 Python 3을 사용합니다. 기존 `.env`와 구분한 새 비공개 파일을 생성합니다.

```sh
python3 deploy/generate_api_tokens.py --postgres --output .env.postgres
docker compose --env-file .env.postgres -f compose.yaml -f compose.postgres.yaml config --quiet
docker compose --env-file .env.postgres -f compose.yaml -f compose.postgres.yaml up --build --wait --wait-timeout 180
curl --fail http://127.0.0.1:8080/api/health
# 일반 중지: DB 볼륨을 보존
docker compose --env-file .env.postgres -f compose.yaml -f compose.postgres.yaml down
```

생성 파일에는 참가자별 API 키와 임의의 DB 비밀번호가 들어 있습니다. 도구는 0600 권한으로 새 파일만 만들며 비밀을 출력하지 않습니다. `.env.postgres`는 Git에서 제외됩니다. 전체 Compose config 출력에는 비밀이 포함될 수 있으므로 `--quiet`로 검사합니다. DB 비밀번호를 APK·URL·로그·Git에 넣지 않습니다.

API는 호스트의 `127.0.0.1`에만 연결되고 DB에는 호스트 게시 포트가 없습니다. 로컬 DB는 `subway_alert` 사용자·데이터베이스와 프로젝트 범위의 `monitor-db` 볼륨을 사용합니다. sample 데이터와 FCM 비활성 설정은 유지됩니다. `down -v` 또는 볼륨 삭제는 취소 표식도 지우므로 평상시 중지 명령에 사용하지 않습니다. 볼륨은 백업이 아닙니다. 기존 볼륨을 두고 환경 파일의 비밀번호만 바꾸면 DB 비밀번호가 변경되지 않아 연결이 실패할 수 있습니다.

## 서버 직접 실행 환경

| 변수 | 의미 |
| --- | --- |
| MONITOR_STORE | memory 또는 postgres, 기본 memory |
| MONITOR_DB_URL | 서버 전용 JDBC PostgreSQL 연결 주소 |
| MONITOR_DB_USER | 서버 전용 DB 사용자 |
| MONITOR_DB_PASSWORD | 서버 전용 DB 비밀번호 |

URL은 `jdbc:postgresql://host[:port]/database` 형식이며 선택적인 `?sslmode=...`만 허용합니다. 사용자·비밀번호는 URL에 넣지 않고 위의 별도 환경변수를 사용합니다. 타임아웃·애플리케이션 이름·임의 JDBC 옵션의 URL 덮어쓰기는 허용하지 않습니다. 연결은 하나의 DB 세션을 유지하고 advisory lock을 보유합니다. **같은 DB에 이 백엔드는 하나만 실행합니다.** 두 번째 프로세스는 시작에 실패합니다. direct 연결 또는 session 연결만 지원하며 transaction pooler와 자동 연결 교체는 지원하지 않습니다. 외부 DB 연결은 운영자 CA·인증서 호스트 검증을 갖춘 TLS 설정을 별도로 준비해야 합니다. 이 로컬 예제를 Supabase 운영 연결 설정으로 그대로 사용하지 않습니다.

처음 실행할 때 비공개 스키마와 테이블을 초기화하므로 해당 DB 사용자는 스키마 생성과 소유 권한이 필요합니다. 이는 개발용 bootstrap이며 운영용 마이그레이션·런타임 최소 권한 분리·변경 승인 절차를 대신하지 않습니다. `supabase/migrations/drafts/schema.sql`은 사용자 인증·즐겨찾기의 별도 미적용 초안입니다.

## 기록과 상태

`subway_alert_private.monitor_receipts`에는 ID, 세션 비밀 SHA-256, 요청 SHA-256, 원래 만료시각, 감시 상태, 전송 상태만 저장합니다. FCM 토큰·역 이름·원문 세션 비밀·API 키는 저장하지 않습니다. 테이블에 RLS를 켜고 PUBLIC 접근 권한을 회수합니다. 앱용 Data API에 이 스키마를 노출하지 않습니다. 로컬 DB 소유 사용자는 RLS를 우회할 수 있으므로 이것만으로 운영 역할 분리가 완료되지는 않습니다.

| 재시작 전 기록 | 복원 결과 |
| --- | --- |
| TRACKING, 만료 전 | CANCELLED, 자동 감시 재개 없음 |
| TRACKING, 만료 후 | EXPIRED |
| CANCELLED / EXPIRED / SAMPLE_MATCHED | 종료 상태 유지 |
| 전송 상태 SENDING | UNKNOWN, 이전 전송 결과 미확인·자동 재전송 없음 |
| 이미 확정된 전송 상태 | 기존 결과 유지; FCM_ACCEPTED도 기기 수신 확인은 아님 |

새 등록·취소 성공 응답 전에 DB 기록이 성공해야 하며 전송 전에 SENDING을 기록합니다. 같은 ID·비밀·본문 재시도는 원래 만료와 현재 상태를 반환합니다. 등록보다 먼저 도착한 취소도 재시작 뒤 늦은 등록을 막습니다. 최대 500개와 2시간 만료 + 추가 1시간 보관 정책은 유지됩니다. 보관 기한을 넘으면 표식도 삭제되며 영구 중복 억제를 제공하지 않습니다.

## DB 장애 복구

저장 실패를 관측하면 해당 프로세스의 감시 API는 503으로 닫히고 새 폴링·전송을 시작하지 않습니다. 취소 저장 실패를 취소 성공으로 표시하지 않습니다. DB 연결을 자동 복구하거나 메모리로 계속 실행하지 않습니다. DB가 복구된 뒤 백엔드를 다시 시작해 확정된 기록을 읽어야 합니다. 이미 발송이 시작된 FCM은 취소·장애·재시작으로 회수할 수 없습니다.

`GET /api/health`는 기존 liveness로, DB 장애 뒤에도 200일 수 있습니다. 운영자는 감시 API 오류와 로그의 비밀 없는 저장소 오류를 함께 관찰해야 합니다. 현재 스토어는 단일 인스턴스이며 분산 감시·분산 쿼터·자동 장애 조치·DB 백업/복원 도구를 제공하지 않습니다. 호출 예산과 기존 독립 demo 엔진은 메모리에 남습니다.

## 실행 검증

통합 검사기는 명시적인 시험 opt-in과 정확히 `subway_alert_test`라는 새 빈 DB만 허용합니다. 기존 사용자 DB·기본 Compose 프로젝트를 검사 대상으로 지정하지 않습니다. DB URL·비밀번호를 명령행 인수로 넘기거나 출력하지 않습니다. `psql`, JDK 17, Maven과 독립 PostgreSQL 17이 필요하며, CI가 이 시험 환경을 생성합니다.

```sh
mvn -f server/pom.xml --batch-mode verify
# 전용 시험 환경에 MONITOR_DB_URL, MONITOR_DB_USER, MONITOR_DB_PASSWORD를 안전하게 설정한 뒤
SUBWAY_POSTGRES_TEST_ONLY=1 python3 deploy/smoke_postgres.py --jar server/target/subway-alert-server-0.1.0.jar
```

실제 실행한 결과와 로컬·CI의 구분은 [영속 저장 검증 기록](verification-durability.md)에 남깁니다. 실제 서울 API 키·FCM·휴대폰·Tunnel·Supabase 프로젝트는 이 검사에 필요하지 않습니다.

공식 참고: [Supabase 연결 방식](https://supabase.com/docs/guides/database/connecting-to-postgres), [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [PostgreSQL advisory lock](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS), [pgJDBC](https://jdbc.postgresql.org/documentation/). 이번 작업에서 클라우드 프로젝트에 SQL을 적용하지 않았습니다.

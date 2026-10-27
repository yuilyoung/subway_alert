# 등록 기록 영속 저장 검증 기록

작성일: 2026-10-28 (한국 시간). PR #5를 `acee162c3fde75ed5966b3d95c42bf7fe3151549`로 main에 병합한 뒤 별도 `feat/durable-monitor-receipts` 브랜치에서 작업했습니다. 아래 로컬 결과와 원격 PostgreSQL 결과를 구분합니다.

## 실제 실행한 로컬 검사

| 검사 | 결과 | 범위 |
| --- | --- | --- |
| Java 17 Maven verify | 85개, 실패·오류·건너뜀 0, JAR 패키징 성공 | 기존 68개 + 영속 복구 12개 + 저장 모드 설정 5개 |
| npm test | 55개 통과 | UNKNOWN 전송 결과 처리 포함 |
| Expo Android export | 성공, 746모듈 | Android용 JS/Hermes 번들, 설치·FCM 수신 아님 |
| Python unittest 전체 | 37개 통과 | 키 생성·Compose 검사기·DB 시험 실행 환경 및 안전 경계 |
| 패키징 JAR 접근 보호·복구 smoke | 통과 | 강제 memory, 인증·호출 제한·취소 선행·응답 유실·재생 |
| PostgreSQL Compose config --quiet | 성공 | 생성한 비공개 임시 환경 파일 사용, 엔진 실행 아님 |
| git diff --check | 성공 | 공백·패치 검사 |

테스트를 먼저 실행해 복구 API 부재·만료시각 정밀도·잘못된 JDBC URL·UNKNOWN 파싱 등의 실패를 확인한 뒤 구현했습니다. 서버 테스트는 취소 선행, 원래 만료 유지, 재시작 시 감시 중지, 미완료 전송 UNKNOWN, 쓰기 실패 시 503, 전송 전에 SENDING 저장, 저장 실패 후 새 폴링·푸시 중단, 보관 만료와 손상 기록 거부를 검증합니다. 이 단위 테스트의 저장소·알림 의존성은 시험 대역이며 실제 PostgreSQL 검증을 대신하지 않습니다.

검토에서 시험 JVM이 상위 우선순위의 Spring 환경 설정을 상속하면 검증한 시험 DB와 다른 곳에 연결할 수 있는 문제를 발견했습니다. 별도 회귀 테스트와 실행 환경 제한으로 수정하고, 기존 접근 보호 smoke는 명시적으로 memory 모드를 사용하도록 했습니다.

## 원격 CI에서 실행하는 실제 PostgreSQL 검사

워크플로의 `Real PostgreSQL durable receipt integration`은 새 PostgreSQL 17 서비스와 새 `subway_alert_test` DB에서 패키징 JAR을 여러 번 실행합니다. 이 파일 작성 시점에는 원격 실행 전이며, **해당 브랜치 최신 커밋의 PR / Actions 결과가 실제 원격 판정**입니다. 새 CI 결과는 PR 본문에서 실행 링크와 함께 갱신합니다.

- 등록·취소·취소 선행 표식의 재시작 복구, 같은 ID·원래 만료·현재 종료 상태 유지.
- 잘못된 capability의 404/409, 복원한 종료 감시의 시험 전송 거부.
- 같은 DB의 두 번째 백엔드 시작 실패, 첫 백엔드는 계속 동작.
- 승인된 6개 열과 SHA-256만 저장, FCM·API·세션 원문 미저장, RLS와 PUBLIC 권한 회수·비소유 역할 조회 거부.
- 정확히 이 시험 백엔드의 단일 JDBC 연결만 종료한 뒤 감시 API 503, 새 기록·자동 재접속 없음. health는 liveness 200 유지.
- 명시적인 프로세스 재시작 후 기존 취소 기록 복구. 서울 API·FCM 호출은 필요하지 않음.

명시적인 시험 opt-in·정확한 DB 이름·빈 사용자 스키마를 확인하기 전에는 JVM을 실행하지 않습니다. 비밀과 DB URL·전체 JVM 출력은 공개 로그로 내보내지 않습니다. JVM에는 필요한 OS 환경과 명시적인 시험 설정만 전달합니다. CI 서비스의 고정 비밀번호는 폐기되는 시험 fixture이며 운영 비밀이 아닙니다.

## 미검증·후속 항목

현재 로컬 도구 환경에는 Docker 엔진이 없고, uid 0에서 일반 사용자 전환도 허용하지 않아 PostgreSQL 서버를 실행하지 않았습니다. PostgreSQL의 root 실행 제한을 우회하지 않았습니다. 결합 Compose 프로파일의 개발 PC 실행은 config 검사와 CI의 JAR+실제 DB 검사와 구분해야 합니다.

Supabase 프로젝트·운영 마이그레이션·런타임 최소 권한 분리·TLS CA·백업 복원·분산 쿼터·로그인·즐겨찾기 동기화는 미완료입니다. Firebase 실제 기기 알림, 화면 꺼짐·Doze·재부팅, 실키 HTTPS·노선/시간 검증, Tunnel·VPS·Google Play 배포도 미완료입니다. 기본 memory 모드의 재시작 기록 소실과 어떤 모드에서도 프로세스 호출 예산 초기화는 유지됩니다. 저장 모드와 복구 절차는 [실행 안내](durable-receipts.md)를 기준으로 합니다.

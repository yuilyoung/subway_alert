# subway_alert 코드 리뷰와 검증

2026-11-21, GitHub 기준 커밋 `acee162`에 적용한 작업 사본에서 검증했다. 대상은 Expo 54 Android 앱, Spring Boot API, Docker·CI, PostgreSQL 스키마 초안이다.

| 범위 | 실행한 검사와 결과 |
| --- | --- |
| 모바일 단위·모듈 | Node 24에서 72개 통과. 깨끗한 설치 후 경로·시간·위치 배치 처리, 등록 복구, 키 교체, 저장 오류, 중복 작업을 검사했다. |
| 서버 단위·모듈·HTTP 통합 | JDK 17에서 `mvn clean verify` 77개 통과. 감시 등록·취소 경쟁, 중복 방지, 보관 기한, 인증·호출 한도, 한국어 JSON의 64 KiB 경계와 청크 전송, 응답·로그에 입력값이 노출되지 않는지 검사했다. 독립 TrackingEngine 검사는 14개다. |
| 모바일 ↔ 서버 | 패키징한 JAR을 루프백에서 기동하고 앱의 등록 코드를 실제 HTTP로 호출했다. 등록 응답 유실 후 같은 ID로 재시도, 조회, FCM 비활성 응답, 취소, 구버전 앱의 세션 정리를 확인했다. 이 검사에서 SecureStore는 메모리 저장소로 대체했다. |
| Docker·배포 | 리뷰 시점의 Python 검사 28개가 통과했다. Linux AMD64 Docker에서 빌드, 초기 설정과 인증, 재시작까지 7개 단계와 자원 정리를 확인했다. GitHub CI에서도 AMD64·ARM64 러너가 각각 이미지를 빌드하고 같은 검사를 통과했다. |
| 데이터베이스 | 격리된 PostgreSQL 17에서 테스트 3개 통과. 모의 Supabase 역할로 소유자만 즐겨찾기를 수정·삭제하고 알림을 읽는지, 동시 슬롯 생성 시 한 요청만 성공하는지, 사용자 삭제 시 자식 행을 지우는지 검사했다. |
| Android | 클라우드에서 Android SDK·NDK로 Expo prebuild와 Gradle 릴리스 Hermes 번들을 확인했다. 이 환경의 APK 조립은 `repo.reactnative.dev`에서 AAR 다운로드 시 HTTP 403으로 중단됐다. GitHub CI에서는 같은 커밋의 ARM64 독립 APK를 빌드하고 서명과 내장 JS 번들을 확인했다. [CI #45](https://github.com/yuilyoung/subway_alert/actions/runs/44915386326) |

## 수정과 재검토

- 알림을 예약하기 전에 경로를 완료 처리하거나 한 배치의 앞선 GPS 관측을 잃는 문제를 수정했다. 겹치는 위치 콜백과 사용자의 감시 전환을 순서대로 처리하고 마지막 출퇴근 즐겨찾기를 껐을 때 불필요한 위치 서비스를 중지한다.
- 등록 응답을 잃거나 서버 키를 교체한 경우의 복구와 구버전 앱의 저장 기록 정리를 검사했다. 서버는 취소가 등록보다 먼저 도착해 새 기록을 차지하는 경우에도 생성 한도를 적용하고, 기존 세션 소유자의 취소는 허용한다.
- 데모 세션의 개수와 보관 시간을 제한하고, 서울 API 응답을 수신 중에 크기 제한을 적용하도록 변경했다. 잘못된 역·열차 식별자와 요청 본문을 조기에 거부한다.
- 서버를 Spring Boot 4.1.3·Firebase Admin 9.12.0으로 갱신하고 Jackson과 테스트를 이전했다. Expo SDK 54와 React Native 0.81.5를 유지하면서 모바일 빌드 도구의 의존성을 조정했다.
- 서버의 동시 등록·중복 전송·요청 한도 관련 테스트 6개를 3회, 모바일의 겹치는 GPS 업데이트·동시 등록 관련 테스트 3개를 5회 반복해 모두 통과했다.
- 독립 리뷰에서 추가로 발견한 구버전 복구와 마지막 즐겨찾기 문제를 수정한 뒤 각 회귀 테스트를 재실행했다.

## 보안 검사의 범위

이 작업 사본의 모바일 `npm audit`는 수정 전 15개(높음 2개), 수정 후 0개였다. Maven 검사는 실제 런타임 의존성의 패키지명·버전을 해당 날짜의 GitHub 검토 완료 Maven 보안 공지와 대조했다. 서버는 수정 전 137개 의존성에서 106개 공지가 버전 범위에 일치했고, 수정 후 148개에서 일치하는 공지가 없었다. Android 릴리스 런타임의 Maven 의존성도 같은 방법으로 검사했다. Commons IO와 Okio에서 3개 공지와 일치해 Expo prebuild에서 각각 2.14.0과 3.4.0 이상을 선택하도록 설정했다. 최종 의존성 144개에서 일치 건수는 0개였다. 깨끗한 prebuild와 연속 prebuild가 생성한 앱 Gradle 파일은 동일했다. 이 수치는 알려진 버전 범위와의 일치 건수다. 실제 취약 코드 도달 가능성, 컨테이너 OS와 빌드 플러그인은 별도 범위다. 대조한 공지 아카이브의 SHA-256은 `fe69f9c6c60c175a0d761390d83eb6e8d45e8d0d9924f1522d51c0c7b3c56c3a`이다.

## 재실행

저장소 루트에서 다음 명령을 실행한다. 등록 통합 검사는 JDK 17과 Node 24가 필요하며, Docker 검사는 로컬 Docker 엔진을 사용한다.

```sh
(cd mobile && npm ci && npm test && npm audit && npx expo export --platform android)
mvn -f server/pom.xml clean verify
python3 deploy/smoke_api_access.py --mobile-client --jar server/target/subway-alert-server-0.1.0.jar
python3 -m unittest discover -s data/tests
python3 supabase/tests/test_schema.py -v
python3 deploy/smoke_compose.py --report artifacts/docker-smoke.json
```

실기기의 화면 꺼짐·재부팅·푸시 도착, 실키 서울 API, 운영 Supabase Auth는 추가 검증이 필요하다. Android가 알림 예약을 수락하고 앱이 완료 상태를 저장하기 전에 프로세스가 종료되면 중복 알림이 가능하다. 서버의 세션·한도는 프로세스 메모리에 있어 서버 재시작과 여러 인스턴스에 걸친 복구를 보장하지 않는다. [Mac·Android 실기기 시험 절차](device-test.md)

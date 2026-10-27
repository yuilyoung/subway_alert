# 배포 문서·구성 검증 기록

검증일: 2026-10-27. 이 기록은 로컬 설정과 애플리케이션 검증이며 운영 배포 완료 보고가 아닙니다.

## 이번 개발 기기 접근 보호 변경

| 검증 | 실행 결과 | 한계 |
| --- | --- | --- |
| 키 생성 도구 TDD | 구현 전 생성·동시 생성 관련 4개 실패 확인, 구현 후 생성 도구 8개 테스트 통과 | 테스트 임시 디렉터리만 사용, 생성 키는 출력하지 않음 |
| Python 전체 discovery | `python3 -m unittest discover -s data/tests -v`: 12개 통과 (생성 도구 8개·역 데이터 4개) | 외부 자격 증명·기기 미사용 |
| 빈 키 템플릿 Compose | standalone CLI v5.6.1, `--env-file deploy/.env.example config --quiet` 성공 | 구문 검사이며 서버의 503 동작 증거는 아님 |
| 생성한 키 파일 Compose | 임시 2키 파일의 `config --quiet` 성공, 키 전달·127.0.0.1:8080·sample·FCM false 확인 | 해석값은 메모리에서 비교, 비밀 출력 없음, 엔진 미사용 |
| 서버 Maven verify | JUnit 52개, 실패·오류·건너뜀 0, BUILD SUCCESS | 실제 외부 제공자·Firebase 미사용 |
| 모바일 npm test | 35개 통과, 실패 0 | 네이티브 SecureStore·기기 화면 실행 미검증 |
| Android JS 번들 | `npx expo export --platform android` 성공, 742모듈·Hermes 번들 생성 | 새 APK·실기기 설치 완료를 뜻하지 않음 |
| 실행 JAR 인증·호출 제한 | 새 smoke 도구: health 200, 미설정 503, 누락/잘못된/중복 키 401, 정상 키 200, 생성·동시 요청 한도 429 | 루프백·임시 무작위 키, 외부 API 호출 없음 |
| smoke 도구 회귀 증거 | 접근 보호 전 JAR에서는 미설정 API가 200으로 열려 테스트 실패, 새 JAR에서는 통과 | 이전 JAR와 새 JAR 비교, 실제 Tunnel 미사용 |

`deploy/smoke_api_access.py`는 패키징된 JAR를 키 미설정/설정 상태로 각각 실행하고 종료합니다. 생성 키와 서버 로그를 출력하지 않으며 기존 CI 서버 작업에도 같은 검사를 추가했습니다. 아직 이번 변경의 원격 CI나 새 APK 성공을 주장하지 않습니다. `git diff --check`는 문서·구성 변경 뒤 오류 없이 통과했습니다.

키 생성 테스트는 기본·최대 개수, 키 형식과 개별 생성, 권한 0600, 기존 파일·빈 파일·심볼릭 링크 보존, 동시 생성 중 한 작성자만 성공, 잘못된 count·없는 상위 디렉터리 거부, 비밀 출력 방지를 확인합니다. 기존 CI의 `data/tests` discovery가 이 테스트를 함께 실행하므로 워크플로 수정은 필요하지 않습니다.

독립 검토에서 확인한 실키 LIVE 페이지별 호출과 직접 요청 수의 차이는 문서에 구분했습니다. 같은 origin의 기본 포트 표기 차이로 새 키를 적용하지 못하는 복구 문제와, 확인창을 띄운 후 연결을 바꾼 상태에서 등록하는 문제는 회귀 테스트의 실패를 확인한 뒤 수정했습니다. 기본 포트 정규화·권한 대기 전후 연결 일치·정상 등록 테스트가 전체 35개에 포함됩니다. 화면·Doze·기기 수신은 자동 테스트 범위가 아닙니다.

## 접근 보호 변경 이전 기록

아래는 이전 버전의 검사 결과로 현재 변경의 회귀 검증과 구분합니다. [이전 CI #13](https://github.com/yuilyoung/subway_alert/actions/runs/40520333343)의 전체 작업 성공도 이 변경 이전 기록입니다.

| 검증 | 실행 결과 | 한계 |
| --- | --- | --- |
| Maven offline verify | BUILD SUCCESS, JUnit 33개, 실패·오류 0, 실행 JAR 생성 | 실제 Firebase·DB 미사용 |
| 패키징된 JAR 실행 | localhost health HTTP 200, mode DEMO, pushEnabled false | 컨테이너 안에서 실행한 것은 아님 |
| npm test | 21개 통과, 실패 0 | Android 기기·FCM 미사용 |
| Docker Compose config | 공식 standalone CLI v5.6.1, config --quiet 성공 | Docker 엔진 미설치 |
| Compose 해석값 | 127.0.0.1:8080, sample 고정, FCM false 확인 | 실제 이미지·컨테이너 실행 미확인 |
| 배포·CI 코드 리뷰 | 외부 공개 없는 구성, 시험 APK와 Play 출시 구분 확인 | 이번 변경의 원격 GitHub Actions 결과는 별도 확인 필요 |
| PDF v1.1 | 9페이지 렌더링·한글·표·페이지 번호 시각 확인 | 실제 서비스 가동 증거가 아님 |

Docker 이미지 빌드·컨테이너 healthcheck, Cloudflare 로그인·도메인·Tunnel 연결, VPS 생성, Supabase 적용, Google Play 제출은 실행하지 않았습니다. 로컬 health 응답은 서울 API·FCM·DB의 정상 동작을 증명하지 않습니다.

이번 구현은 개발 기기 Bearer 키와 프로세스 메모리 예산입니다. 일반 사용자 로그인·영속/분산 쿼터·운영 과금 제어를 대신하지 않습니다. 배포 준비 다음 단계는 접근 보호 통합 검증과 개발 PC의 Docker 실행 재현입니다. 공개 Tunnel은 여전히 비활성이며 운영 호스팅 업체·리전·예산은 아직 미선정입니다. 별도 PDF v1.1은 이번 접근 보호 개정 내용을 반영하지 않았고 원본 첨부 PDF는 공개 저장소에 올리지 않습니다.

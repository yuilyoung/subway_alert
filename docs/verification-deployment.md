# 배포 문서·구성 검증 기록

검증일: 2026-10-27. 이 기록은 로컬 설정과 애플리케이션 검증이며 운영 배포 완료 보고가 아닙니다.

| 검증 | 실행 결과 | 한계 |
| --- | --- | --- |
| Maven offline verify | BUILD SUCCESS, JUnit 33개, 실패·오류 0, 실행 JAR 생성 | 실제 Firebase·DB 미사용 |
| 패키징된 JAR 실행 | localhost health HTTP 200, mode DEMO, pushEnabled false | 컨테이너 안에서 실행한 것은 아님 |
| npm test | 21개 통과, 실패 0 | Android 기기·FCM 미사용 |
| Docker Compose config | 공식 standalone CLI v5.6.1, config --quiet 성공 | Docker 엔진 미설치 |
| Compose 해석값 | 127.0.0.1:8080, sample 고정, FCM false 확인 | 실제 이미지·컨테이너 실행 미확인 |
| 배포·CI 코드 리뷰 | 외부 공개 없는 구성, 시험 APK와 Play 출시 구분 확인 | 원격 GitHub Actions 결과 미확인 |
| PDF v1.1 | 9페이지 렌더링·한글·표·페이지 번호 시각 확인 | 실제 서비스 가동 증거가 아님 |

Docker 이미지 빌드·컨테이너 healthcheck, Cloudflare 로그인·도메인·Tunnel 연결, VPS 생성, Supabase 적용, Google Play 제출은 실행하지 않았습니다. 로컬 health 응답은 서울 API·FCM·DB의 정상 동작을 증명하지 않습니다.

배포 준비 다음 단계는 개발 PC의 Docker 실행 재현과 API 인증·요청 제한입니다. 현재 무인증 API를 공개 터널로 노출하지 않습니다. 운영 호스팅 업체·리전·예산은 아직 미선정입니다.

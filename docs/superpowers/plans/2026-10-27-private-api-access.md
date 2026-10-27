# API 접근 보호 구현 계획

Spec: `docs/superpowers/specs/2026-10-27-private-api-access-design.md`

기존 Java 17/Expo 코드에 보호 경계를 추가한다. 외부 배포·실키·LIVE 활성화는 하지 않는다. main을 보존하고 `feat/private-api-access`에서 작업한다.

1. 서버: 실제 HTTP 필터를 대상으로 미설정 503/인증 401/health 예외/세션 이중 토큰/전체·키별·생성·조회·서울 날짜 예산·동시성 테스트를 먼저 실패시킨다. 필터와 제한기를 최소 구현하고 Maven 전체 검사를 통과한다. 기존 MVC 테스트는 인증한 실제 경계를 통과하도록 갱신한다.
2. 모바일: 키 검증·origin 전환·안전 저장·인증 헤더·redirect 거부·401/429·취소 실패 보존 테스트를 먼저 실패시킨다. 공통 인증 전송과 연결 저장을 구현하고 화면을 연결한다. 기존 도메인과 전체 Node 테스트 및 Android JS 번들을 검증한다.
3. 실행 안내: 키 파일 생성 도구의 무덮어쓰기/권한/형식 테스트를 먼저 실패시킨다. Compose 환경변수와 문서·설계의 실제 상태를 갱신한다. 비활성 Tunnel과 sample/FCM off를 유지한다.
4. 통합: 실제 실행 JAR로 health/무인증/정상키/잘못된키/429를 검사한다. Maven·Node·Python·Compose config 및 diff 검사를 실행하고 독립 리뷰 후 수정·검증한다. 별도 PR로 보관한다.

공유 인터페이스: `SUBWAY_API_TOKENS`, 32~128 base64url 키, Authorization Bearer, 401/503/429 및 Retry-After, 분당 600/60/3/6과 하루 240. 서버·모바일·문서는 이 계약을 공유한다.

리뷰 중점: 필터 경로·중복 헤더 우회, 프록시 헤더 신뢰, 병렬 제한 경쟁, 세션 토큰과 API 키 분리, 이전 origin 비밀 유출, SecureStore 실패·취소 실패 보존, 샘플 API 총 호출 예산과 재시작 한계.

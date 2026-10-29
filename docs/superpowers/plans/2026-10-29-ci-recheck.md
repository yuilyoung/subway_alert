# CI 재실행과 품질 게이트 보완 계획

**Goal:** 기존 formatter/lint·빌드 파이프라인을 보존하고 재실행과 실패 판정을 검증한다.

**Spec:** 기존 CI/CD 설계와 사용자의 CI 재구축·푸시 요청. main 병합과 관리자 설정은 별도이며 임의 적용하지 않는다.

## 제약과 인터페이스

- `CI gate`는 정확히 6개 필수 검사 결과를 받고 모두 success인 경우만 통과한다. 빈 결과·누락·추가·잘못된 형식도 실패한다.
- 산출물 이름은 `-attempt-${{ github.run_attempt }}` 접미사를 사용한다. 기존 회차를 덮어쓰지 않는다. CD는 검증한 main CI의 최신 회차 배포 묶음만 선택하며 이전 회차로 대체하지 않는다.
- 실제 분석기 실패 증거는 누락된 실행 파일이나 문법 오류가 아닌 의도한 규칙/포맷 위반으로 확인한다. 소스는 수정하지 않고 stdin·임시 디렉터리만 사용한다.
- 비용 자원·main merge·SSH 배포·Play 게시를 수행하지 않는다.

## Task 1 — 게이트 판정

- [ ] 실패·취소·skip·빈 결과·누락·추가·잘못된 형식의 RED 테스트 작성.
- [ ] `deploy/check_ci_gate.py` 구현, CLI JSON 입력과 Actions summary 출력.
- [ ] CI workflow가 같은 필수 검사 집합을 사용하는지 계약 검사.

## Task 2 — 로컬/CI 정적 검사 실행

- [ ] `deploy/check_quality.py`에 static/server 그룹의 읽기 전용 검사와 선택형 negative controls 추가.
- [ ] 실제 ESLint·Prettier·Ruff·actionlint·Spotless·PMD를 실행해 위반이 차단되는지 확인.
- [ ] tools가 없거나 실행 오류가 나는 경우 성공으로 간주하지 않는다. CI에서 같은 명령 사용.

## Task 3 — 재실행과 출처

- [ ] workflow 산출물 이름에 실행 회차 추가, provenance에 run_attempt 검증·선택 테스트.
- [ ] 문서의 검사/자동 수정 명령 분리 및 재실행·main 미적용 범위 설명.
- [ ] 전체 테스트·독립 리뷰 후 기존 PR #8에 추가 커밋 푸시.
- [ ] 새 전체 CI와 실제 job 재실행을 확인해 산출물 충돌이 없는지 보고.

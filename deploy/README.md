# 배포 설정 파일

실행 절차와 확정·미확정 항목은 [배포 안내](../docs/deployment.md)를 확인하세요.

`compose.yaml`은 저장소 루트에 있으며 로컬 백엔드 하나만 실행합니다. 이 폴더의 `.env.example`에는 로컬 포트만 있고 API·Firebase·Cloudflare 비밀값은 없습니다. `cloudflared/config.disabled.example.yml`은 모든 요청에 404를 돌려주는 비활성 예제이며 자동 실행되지 않습니다.

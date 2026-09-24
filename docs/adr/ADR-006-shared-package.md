# ADR-006 api·collector 코드 공유 (단일 패키지 atlas)

- 상태: 채택
- 결정: `atlas/` 하나의 패키지에 core·domain·collector·calc·api 를 두고 Docker 이미지 진입점만 다르게 한다.
  관리 API 의 수집·계산 트리거는 같은 함수를 백그라운드 스레드로 호출한다.

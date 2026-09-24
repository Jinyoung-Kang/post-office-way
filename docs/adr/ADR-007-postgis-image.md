# ADR-007 PostGIS 이미지: arm64 테스트 이미지로 개발

- 상태: 채택
- 맥락: 공식 postgis/postgis 는 amd64 만 제공. Apple Silicon 에서는 에뮬레이션.
- 결정: 로컬은 `imresamu/postgis:16-3.6-bookworm`(arm64 네이티브, "testing only" 표기)을 쓰고 127.0.0.1 에만 바인딩.
  compose 에 공식 이미지(A안)를 주석으로 유지. CI(amd64)는 공식 `postgis/postgis:16-3.5` 사용 — SQL 은 동일.
- 확인: 2026-09-24 로컬에서 `POSTGIS="3.6.1"`, GEOS 3.11.1, PROJ 9.1.1.

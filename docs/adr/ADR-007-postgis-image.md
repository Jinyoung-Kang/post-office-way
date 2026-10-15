# ADR-007 PostGIS 이미지: 공식 postgres 이미지 + PGDG PostGIS 를 직접 빌드

- 상태: 채택 (2026-09-24), 개정 (2026-10-15) — `imresamu/postgis` 에서 `db/Dockerfile` 로. 과정과 비교는 [DB 이미지 교체](../db-image-2026-10.md)
- 맥락: 공식 `postgis/postgis` 는 amd64 만 제공해 Apple Silicon 에서는 에뮬레이션. 처음에는 arm64 네이티브인
  `imresamu/postgis:16-3.6-bookworm`("testing only" 표기)을 썼는데, 이 저장소의 Debian 태그가 2026-02-09 빌드(PG 16.11·Debian 12)에서
  멈춰 `docker compose pull` 로는 PG 마이너 보안판을 받을 수 없게 됐다. CI 의 공식 `postgis/postgis:16-3.5` 도 PG 16.9·Debian 11 이고
  로케일(`en_US.utf8`)이 로컬(`C.UTF-8`)과 달랐다.
- 결정:
  1. `db/Dockerfile` — 공식 `postgres:16-trixie`(arm64·amd64) 위에 PostgreSQL apt 저장소(PGDG)의 `postgresql-16-postgis-3=3.6.*`.
     upstream `postgis/docker-postgis` 의 Debian 이미지와 같은 방식. PG 마이너·Debian 보안판은 Docker 공식 이미지가, PostGIS 패치는 PGDG 가 따라간다.
  2. 보안판은 `make db-update` — 기반 이미지를 새로 받고 캐시 없이 다시 빌드(apt 층이 캐시되면 새 패치를 못 받음) → db 재시작 →
     postgis 가 있는 DB 마다 `postgis_extensions_upgrade()`. 같은 메이저라 데이터 디렉터리는 그대로.
  3. PostGIS 마이너(3.6)는 고정 — 올릴 때는 계산 결과 비교를 함께 한다. 초기화 스크립트는 넣지 않음(확장은 마이그레이션 V1·V6·V13 이 만듦).
  4. CI 도 같은 Dockerfile 을 빌드해 `LANG=C.UTF-8` 로 띄운다(서비스 컨테이너는 미리 만든 이미지만 받음).
- 대안: 공식 `postgis/postgis:16-3.5`(에뮬레이션, PG 16.9, 16-3.6 태그 없음, 3.6→3.5 로 확장을 내릴 수 없음),
  `imresamu/postgis:16-3.6-alpine`(최근 빌드지만 libc 가 musl 로 바뀌고 여전히 testing 표기), `imresamu/postgis:16-3.6-trixie`(같이 멈춤).
- 결과 (2026-10-15): PostgreSQL 16.15 · PostGIS 3.6.4 · GEOS 3.14.1 · PROJ 9.8.1 · Debian 13.7(glibc 2.41).
  - 같은 데이터 디렉터리를 그대로 씀. DB 로케일 `C.UTF-8` 은 glibc 2.36·2.41 모두 바이트 순 정렬이라 인덱스를 다시 만들 필요가 없었고
    amcheck 로 btree 355개 확인, 문자 분류에 기대는 trigram GIN 1개만 다시 만듦.
  - 같은 데이터·코드로 계산을 교체 전후 두 번 돌려 표 9개(736,765행)가 한 행도 다르지 않음.
  - 달라지는 것: `ST_SimplifyPreserveTopology`(GEOS 3.12~3.14 수정)가 남기는 꼭짓점이 일부 다름 — 차이는 허용 오차 안,
    이전 GEOS 가 만들던 잘못된 다각형은 없어짐. 화면 지도는 수집 때 저장한 단순화 경계를 쓰므로 다음 `make sgis` 때 반영.
- 이전 확인: 2026-09-24 `POSTGIS="3.6.1"`, GEOS 3.11.1, PROJ 9.1.1.

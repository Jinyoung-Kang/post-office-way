# DB 이미지 — 공식 postgres(arm64·amd64) 위에 PostgreSQL apt 저장소(PGDG)의 PostGIS (ADR-007)
# PG 마이너·Debian 보안판은 기반 이미지가, PostGIS 패치는 PGDG 가 따라감 → 받으려면 make db-update (build --pull --no-cache)
FROM postgres:16-trixie

# PostGIS 마이너는 고정(올리면 확장 갱신·결과 비교가 필요), 패치(3.6.x)는 빌드 때 최신. 확장은 마이그레이션이 만듦(V1·V6·V13)
ARG POSTGIS_MINOR=3.6
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "postgresql-$PG_MAJOR-postgis-3=$POSTGIS_MINOR.*" \
        "postgresql-$PG_MAJOR-postgis-3-scripts=$POSTGIS_MINOR.*"; \
    rm -rf /var/lib/apt/lists/*

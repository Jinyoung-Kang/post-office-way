# =============================================================================
# Makefile — 우체국 가는 길 원커맨드 (FR-701)
#
#   make up        스택 기동 (db·redis·migrate·api·worker·web) → http://localhost:3100
#   make migrate   스키마 마이그레이션 + API 최소 권한 역할 비밀번호 설정
#   make smoke     키 동작 확인 — 우체국·SGIS·(선택)KOSIS (응답을 fixtures/ 에 저장)
#   make discover  우편 지역코드 seed 생성 (최초 1회, 약 5분)
#   make collect   전국 우체국 시설 수집         (RESUME=<collect_run_id> 로 재개, SCOPE=100,101 로 일부만)
#   make sgis      SGIS 인구·경계 적재
#   make kosis     KOSIS 주민등록인구(65세 이상) 적재 — KOSIS_API_KEY 없으면 건너뜀
#   make oa        ① SGIS 집계구 인구·경계 (약 15분, 끊기면 다시 실행해 이어받기)
#   make banks     ④ 카카오 은행·금고 지점 (약 15분)
#   make road      ② 카카오모빌리티 도로 거리 (MAX=8000 호출 예산, 다시 실행하면 이어서)
#   make geocheck  ③ 카카오 주소 검색으로 시설 좌표 검증 (DQ)
#   make extras    oa → banks → road → geocheck → care → holidays → calc
#   make weather   ⑥ 방문 여건 — 기상청 단기예보·에어코리아 예보 (약 2분, 하루 1~3회. DATA_GO_KR_KEY 없으면 건너뜀)
#   make care      ⑦ 약국·병의원 전체 자료 (약 2분) → 생활 거점 지표는 make calc 뒤 반영
#   make holidays  ⑦ 공휴일(특일 정보) — 창구 휴무일·연휴 모드
#   make jobs      작업 큐 최근 기록   make schedule 워커 스케줄   make enqueue KIND=calc 워커에 작업 요청
#   make bench     API 부하 측정 (p50/p95·처리량) + 느린 SQL 상위
#   make calc      지표 계산 (calc_run)
#   make all-data  discover(필요 시) → collect → sgis → kosis → extras(oa·banks·road·geocheck·care·holidays) → calc → weather
#   make test      단위·계약·SQL 테스트 (PostGIS 테스트 DB 사용)
#   make status    수집·계산 현황   make logs / make psql / make down
#   make prune     오래된 원문·스냅샷·계산 결과 정리 (KEEP=3 수집 run, KEEP_CALC=5 계산 run)
# =============================================================================

SHELL := /bin/bash
COMPOSE := docker compose
RUN := $(COMPOSE) --profile batch run --rm collector

.DEFAULT_GOAL := help
.PHONY: help env up down restart logs ps build migrate smoke discover collect sgis sgis-pop sgis-bnd kosis oa banks road geocheck \
        extras weather care holidays calc all-data prune jobs schedule enqueue bench \
        status test test-unit psql web-dev api-dev reset

help:
	@grep -E '^#   make' Makefile | sed 's/^#   //'

# .env 가 없으면 만들고, ADMIN_TOKEN·API_DB_PASSWORD 가 비어 있으면 무작위 값으로 채웁니다(값은 출력하지 않음).
env:
	@test -f .env || (cp .env.example .env && echo "→ .env 를 만들었습니다. 키 값을 채워 주세요.")
	@for k in ADMIN_TOKEN API_DB_PASSWORD; do \
	  if ! grep -qE "^$$k=[^[:space:]#]+" .env; then \
	    tok=$$(openssl rand -hex 24); \
	    if grep -qE "^$$k=" .env; then sed -i.bak -E "s|^$$k=.*|$$k=$$tok|" .env && rm -f .env.bak; \
	    else [ -z "$$(tail -c1 .env)" ] || echo >> .env; printf '%s=%s\n' "$$k" "$$tok" >> .env; fi; \
	    echo "→ $$k 를 생성했습니다."; fi; done

up: env
	$(COMPOSE) up -d --build
	@echo ""
	@echo "  화면  http://localhost:3100"
	@echo "  API   http://localhost:8100/docs"
	@echo "  데이터가 비어 있으면: make all-data"

build: env
	$(COMPOSE) --profile batch build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart api worker web

migrate: env
	$(RUN) migrate

logs:
	$(COMPOSE) logs -f --tail=100 api worker web

ps:
	$(COMPOSE) ps

smoke: env
	$(RUN) smoke

discover: env
	$(RUN) discover post $(if $(RANGE),--range $(RANGE),)

collect: env
	$(RUN) collect post $(if $(SCOPE),--scope $(SCOPE),) $(if $(RESUME),--resume $(RESUME),)

sgis: env
	$(RUN) collect sgis

sgis-pop: env
	$(RUN) collect sgis-pop

sgis-bnd: env
	$(RUN) collect sgis-bnd

kosis: env
	$(RUN) collect kosis

oa: env
	$(RUN) collect oa $(if $(REFRESH),--refresh,)

banks: env
	$(RUN) collect banks

road: env
	$(RUN) collect road $(if $(MAX),--max-calls $(MAX),)

geocheck: env
	$(RUN) collect geocheck $(if $(MAX),--max-calls $(MAX),)

weather: env
	$(RUN) collect weather

care: env
	$(RUN) collect care

holidays: env
	$(RUN) collect holidays

jobs:
	@$(RUN) jobs

schedule:
	@$(RUN) schedule

enqueue: env
	$(RUN) enqueue $(KIND)

# 측정 동안만 속도 제한을 끄고(api 재기동) 끝나면 되돌림 — 제한이 켜져 있으면 429 가 지연 시간을 왜곡
bench:
	RATE_LIMIT_ENABLED=false $(COMPOSE) up -d --wait api
	-$(RUN) bench $(if $(N),--requests $(N),) $(if $(C),--concurrency $(C),)
	$(COMPOSE) up -d --wait api

extras: env
	$(MAKE) oa
	$(MAKE) banks
	$(MAKE) road
	$(MAKE) geocheck
	$(MAKE) care
	$(MAKE) holidays
	$(MAKE) calc

calc: env
	$(RUN) calc $(if $(LEVELS),--levels $(LEVELS),)

all-data: env
	@if [ $$(grep -cE '^[0-9cC]' seed/area_codes.csv) -eq 0 ]; then $(MAKE) discover; fi
	$(MAKE) collect
	$(MAKE) sgis
	$(MAKE) kosis
	$(MAKE) extras
	$(MAKE) weather

status:
	@$(RUN) status

prune: env
	$(RUN) prune --keep $(or $(KEEP),3) --keep-calc $(or $(KEEP_CALC),5)

# 테스트 DB(atlas_test)는 운영 DB 와 분리 — 테스트가 스키마를 지우고 다시 만듭니다.
test: env
	$(COMPOSE) up -d db redis
	@$(COMPOSE) exec -T db psql -U atlas -d atlas -tc "SELECT 1 FROM pg_database WHERE datname='atlas_test'" | grep -q 1 \
	  || $(COMPOSE) exec -T db psql -U atlas -d atlas -c "CREATE DATABASE atlas_test"
	$(COMPOSE) --profile batch run --rm --build --entrypoint pytest \
	  -e TEST_DATABASE_URL=postgresql+psycopg://atlas:atlas@db:5432/atlas_test collector -q -p no:cacheprovider

test-unit:
	cd atlas && python3.11 -m pytest -q tests/unit tests/contract

psql:
	$(COMPOSE) exec db psql -U atlas -d atlas

# 호스트에서 직접 개발 (db·redis 는 compose 로)
api-dev:
	$(COMPOSE) up -d db redis
	cd atlas && MIGRATE_ON_START=true python3.11 -m uvicorn atlas.api.main:app --port 8100 --reload

web-dev:
	cd web && npm install && npm run dev

reset:
	@read -p "DB 볼륨을 지우고 처음부터 시작합니다. 계속할까요? [y/N] " a && [ "$$a" = y ]
	$(COMPOSE) down -v

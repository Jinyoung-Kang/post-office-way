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
#   make extras    oa → banks-full → road → geocheck → care → holidays → osm → calc(+도보)
#   make weather   ⑥ 방문 여건 — 기상청 단기예보·에어코리아 예보 (약 2분, 하루 1~3회. DATA_GO_KR_KEY 없으면 건너뜀)
#   make banks-full ④ 은행·금고 지점 전수 (사분할 격자, 약 9분) → 은행 지점 폐쇄 영향평가의 기준 목록
#   make osm       ② OSM 한국 도로망(약 275MiB, 바뀌었을 때만) + 도보 그래프   make walk  최신 계산에 도보 거리
#   make care      ⑦ 약국·병의원 전체 자료 (약 2분) → 생활 거점 지표는 make calc 뒤 반영
#   make holidays  ⑦ 공휴일(특일 정보) — 창구 휴무일·연휴 모드
#   make jobs      작업 큐 최근 기록   make schedule 워커 스케줄   make enqueue KIND=calc 워커에 작업 요청
#   make bench     API 부하 측정 (p50/p95·처리량) + 느린 SQL 상위
#   make calc      지표 계산 (calc_run) + 도보 거리(OSM 그래프가 있으면)
#   make all-data  discover(필요 시) → collect → sgis → kosis → extras(oa·banks·road·geocheck·care·holidays) → calc → weather
#   make test      단위·계약·SQL 테스트 (PostGIS 테스트 DB 사용)
#   make qa        띄운 서비스 전수 점검 — API 퍼징 · 11개 화면 크롤링 · 네트워크(중복·평문·CSP) · 접근성 · 설명 줄바꿈 (약 5분)
#   make qa-lh     Lighthouse 모바일 9개 화면 × 3회 중앙값 표 (약 15분)
#   make status    수집·계산 현황   make logs / make psql / make down
#   make prune     오래된 원문·스냅샷·계산 결과 정리 (KEEP=3 수집 run, KEEP_CALC=5 계산 run)
#   make backup    DB 백업 → backups/*.dump (LITE=1 이면 원본 응답 raw 데이터 제외)
#   make restore   FILE=backups/….dump 로 DB 되돌리기 (임시 DB 에 복원·검증 뒤 교체, 이전 DB 는 atlas_prev — make restore-undo)
# =============================================================================

SHELL := /bin/bash
COMPOSE := docker compose
RUN := $(COMPOSE) --profile batch run --rm collector

.DEFAULT_GOAL := help
.PHONY: help env up down restart logs ps build migrate smoke discover collect sgis sgis-pop sgis-bnd kosis oa banks road geocheck \
        extras banks-full osm walk weather care holidays calc all-data prune backup restore jobs schedule enqueue bench \
        status test test-unit qa qa-lh psql web-dev api-dev reset restore-undo

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

banks-full: env
	$(RUN) collect banks-full

osm: env
	$(RUN) collect osm

walk: env
	$(RUN) collect walk

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
	$(MAKE) banks-full
	$(MAKE) road
	$(MAKE) geocheck
	$(MAKE) care
	$(MAKE) holidays
	$(MAKE) osm
	$(MAKE) calc

calc: env
	$(RUN) calc $(if $(LEVELS),--levels $(LEVELS),)
	$(RUN) collect walk     # 도보 거리(그래프가 없으면 건너뜀) — 워커로 돌린 계산은 자동으로 이어짐

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

# pg_dump 사용자 지정 형식(-Fc, 압축) — 역할(atlas_api)은 클러스터 전역이라 덤프에 없고 migrate 가 다시 설정합니다.
backup:
	@mkdir -p backups
	@f=backups/atlas-$$(date +%Y%m%d-%H%M)$(if $(LITE),-lite).dump; \
	  $(COMPOSE) exec -T db pg_dump -U atlas -d atlas -Fc $(if $(LITE),--exclude-table-data='raw.*') > $$f.part \
	  && mv $$f.part $$f && echo "백업: $$f ($$(du -h $$f | cut -f1))" || { rm -f $$f.part; exit 1; }

# 복원은 지금 DB 를 건드리기 전에 끝까지 검증 — 덤프 목차 확인 → 임시 DB(<DB>_restore)에 복원 → 성공하면 이름을 바꿔 교체.
# 이전 DB 는 <DB>_prev 로 남김(되돌리기: make restore-undo). 복원이 중간에 실패하면 지금 DB 는 그대로.
# 이름 바꾸기 두 번은 한 트랜잭션(psql -1) — 두 번째가 실패하면 첫 번째도 되돌려져 <DB> 가 사라진 채 멈추지 않음
# (DROP DATABASE 는 트랜잭션 안에서 못 써서 따로). 실패하면 멈춘 서비스를 다시 띄움
RESTORE_DB ?= atlas
PSQL_ADMIN := $(COMPOSE) exec -T db psql -U atlas -d postgres -v ON_ERROR_STOP=1 -q
DB_EXISTS = $(COMPOSE) exec -T db psql -U atlas -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$(1)'" < /dev/null | grep -q 1
restore:
	@test -f "$(FILE)" || { echo "FILE=backups/<파일>.dump 를 지정하세요"; ls backups/*.dump 2>/dev/null; exit 2; }
	@$(COMPOSE) exec -T db pg_restore --list < $(FILE) > /dev/null || { echo "덤프를 읽을 수 없습니다: $(FILE)"; exit 1; }
	@read -p "$(RESTORE_DB) DB 를 $(FILE) 내용으로 바꿉니다(지금 DB 는 $(RESTORE_DB)_prev 로 남기고, 이전에 남긴 $(RESTORE_DB)_prev 는 지웁니다). 계속할까요? [y/N] " a && [ "$$a" = y ]
	@$(PSQL_ADMIN) -c "DROP DATABASE IF EXISTS $(RESTORE_DB)_restore WITH (FORCE)" -c "CREATE DATABASE $(RESTORE_DB)_restore"
	@$(COMPOSE) exec -T db pg_restore -U atlas -d $(RESTORE_DB)_restore --exit-on-error < $(FILE) \
	  || { $(PSQL_ADMIN) -c "DROP DATABASE IF EXISTS $(RESTORE_DB)_restore WITH (FORCE)"; \
	       echo "복원 실패 — $(RESTORE_DB) DB 는 바뀌지 않았습니다"; exit 1; }
	$(COMPOSE) stop api worker web
	@$(PSQL_ADMIN) -c "DROP DATABASE IF EXISTS $(RESTORE_DB)_prev WITH (FORCE)"
	@$(PSQL_ADMIN) -1 -c "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = '$(RESTORE_DB)'" \
	  -c "ALTER DATABASE $(RESTORE_DB) RENAME TO $(RESTORE_DB)_prev" \
	  -c "ALTER DATABASE $(RESTORE_DB)_restore RENAME TO $(RESTORE_DB)" \
	  || { $(COMPOSE) up -d; echo "이름 교체 실패 — $(RESTORE_DB) DB 는 바뀌지 않았습니다(복원본은 $(RESTORE_DB)_restore)"; exit 1; }
	$(COMPOSE) up -d
	@echo "복원 완료 — 이전 DB 는 $(RESTORE_DB)_prev 로 남겼습니다 (되돌리기: make restore-undo)"

# 되돌릴 DB(<DB>_prev)가 없으면 서비스를 멈추기 전에 끝냄 — 예전에는 지금 DB 이름부터 바꾼 뒤 실패해 <DB> 가 사라진 채 멈췄음
restore-undo:
	@$(call DB_EXISTS,$(RESTORE_DB)_prev) || { echo "$(RESTORE_DB)_prev 가 없습니다 — 되돌릴 복원이 없습니다."; exit 2; }
	@read -p "$(RESTORE_DB) 를 $(RESTORE_DB)_prev(복원 전 DB)로 되돌립니다. 계속할까요? [y/N] " a && [ "$$a" = y ]
	$(COMPOSE) stop api worker web
	@$(PSQL_ADMIN) -1 -c "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = '$(RESTORE_DB)'" \
	  -c "ALTER DATABASE $(RESTORE_DB) RENAME TO $(RESTORE_DB)_undone" \
	  -c "ALTER DATABASE $(RESTORE_DB)_prev RENAME TO $(RESTORE_DB)" \
	  || { $(COMPOSE) up -d; echo "되돌리기 실패 — $(RESTORE_DB) DB 는 그대로입니다"; exit 1; }
	@$(PSQL_ADMIN) -c "DROP DATABASE $(RESTORE_DB)_undone WITH (FORCE)"
	$(COMPOSE) up -d

# 테스트 DB(atlas_test)는 운영 DB 와 분리 — 테스트가 스키마를 지우고 다시 만듭니다.
test: env
	$(COMPOSE) up -d --wait db redis     # healthy 까지 기다림 — 차가운 상태에서 바로 psql 이 붙다 실패했음
	@$(COMPOSE) exec -T db psql -U atlas -d atlas -tc "SELECT 1 FROM pg_database WHERE datname='atlas_test'" | grep -q 1 \
	  || $(COMPOSE) exec -T db psql -U atlas -d atlas -c "CREATE DATABASE atlas_test"
	$(COMPOSE) --profile batch run --rm --build --entrypoint pytest \
	  -e TEST_DATABASE_URL=postgresql+psycopg://atlas:atlas@db:5432/atlas_test -e TEST_REDIS_URL=redis://redis:6379/15 \
	  collector -q -p no:cacheprovider

# 서비스 점검 (scripts/qa) — 결과는 .qa/*.json. 설치된 Google Chrome 사용(브라우저 내려받기 없음)
QA_PY := .qa-venv/bin/python
$(QA_PY): scripts/qa/requirements.txt
	python3 -m venv .qa-venv && .qa-venv/bin/pip install -q -r scripts/qa/requirements.txt && touch $(QA_PY)

qa: $(QA_PY)
	@test -f web/node_modules/axe-core/axe.min.js || (cd web && npm ci --silent)
	@# 퍼징은 요청이 많아 같은 컴퓨터의 다른 점검과 속도 제한 버킷을 나눠 쓰므로 마지막에 (429 는 기다렸다 다시 보냄)
	@status=0; for s in crawl requests_check a11y sentences failures fuzz; do $(QA_PY) scripts/qa/$$s.py || status=1; done; exit $$status

qa-lh: $(QA_PY)
	$(QA_PY) scripts/qa/lighthouse.py $(or $(N),3)

test-unit:
	cd atlas && python3.13 -m pytest -q tests/unit tests/contract

psql:
	$(COMPOSE) exec db psql -U atlas -d atlas

# 호스트에서 직접 개발 (db·redis 는 compose 로)
api-dev:
	$(COMPOSE) up -d --wait db redis
	cd atlas && MIGRATE_ON_START=true python3.13 -m uvicorn atlas.api.main:app --port 8100 --reload

web-dev:
	cd web && npm install && npm run dev

reset:
	@read -p "DB 볼륨을 지우고 처음부터 시작합니다. 계속할까요? [y/N] " a && [ "$$a" = y ]
	$(COMPOSE) down -v

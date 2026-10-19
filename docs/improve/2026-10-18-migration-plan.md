# 계획 · 설계 — 행정안전부 '지역별 인구이동 현황' 연동 (2026-10-18)

상태: **구현 완료 (2026-10-19)** — 결정·실호출로 확인한 사실·설계에서 바꾼 것은 [ADR-028](../adr/ADR-028-population-migration.md).
작성 기준 `main` `a44f1ba`, 작업 트리 깨끗함.

> 구현하며 바꾼 것(요약): 시군구마다 두 번 부르는 대신 **한 달 전국 행렬**(전입·전출 코드가 둘 다 필수) · 원천이 일반구를 시로 묶어
> **원천 단위 표 + SGIS 대응표**(`KOSIS_CD`·`NAME`·`CITY`) · 65세 이상 지표를 **천 명당**(`AGED65_NET_IN_12M_PER_1K`) ·
> 최신 2개 달 매번 대신 **공표 직후 받은 달만 한 달 뒤 한 번 더**. §4 결정은 모두 권장안((b)·(a)·(a)·13개월)으로.

2026-10 에 새로 발급받은 공공데이터포털 API 10개 가운데 이 프로젝트에 맞는 것은 **행정안전부_지역별 인구이동 현황**
(`https://apis.data.go.kr/1741000/ppltnDataStus`) 하나입니다. 지금 인구는 KOSIS 주민등록인구(연 1회 기준월)와 SGIS 인구로 **시점**만 봅니다.
인구이동을 붙이면 **추세**(최근 12개월 순유출 · 65세 이상 순유입)가 생겨,
- 지역 카드 · 지역 순위 · 지역 보고서에 "사람이 빠지는 곳인가" 를 한 지표로 보여 주고,
- 배치 제안(닫을 곳 · 열 곳)에 "순유출 지역" 경고를 붙일 수 있습니다(가중치는 바꾸지 않음).

같은 API 묶음의 다른 것(기상특보 · 병원정보 · CCTV 도로날씨 등)은 이 프로젝트에 넣지 않습니다(§5).

---

## 0. 설계를 묶는 지금 구조의 사실 (코드로 확인)

| 사실 | 근거 | 설계에 주는 영향 |
|---|---|---|
| data.go.kr 호출은 `collector/datago/client.py` `call()` 로 — `response.header/body` 봉투만 이해하고, 코드 22(일 한도)·20·30~33 은 `DataGoStop` | `client.py` `_error_of`, `STOP_CODES` | 1741000 응답 봉투가 다르면 모든 호출이 실패로 보인다 → 0단계에서 실응답 1건을 받아 확인하고, 다르면 `_error_of` 를 일반화 |
| 모든 원본 응답은 키를 가려 `raw.api_response` 에 gzip 저장, `source` 는 CHECK 목록(V10) | `collector/http.py` `Fetcher._store` | 새 source 코드를 CHECK 에 추가(V25) |
| 수집 실행은 `ops.collect_run(kind CHECK, status RUNNING/DONE/PARTIAL/FAILED)` + `DQRecorder`; `kind` CHECK 목록은 V18 | `ops/runs.py`, `ops/dq.py`, V18 | 새 kind 를 CHECK 에 추가, DQ 규칙은 `dq.RULES` 에 등록 |
| 행안부 10자리 행정기관코드 ↔ SGIS 코드 대응은 **KOSIS 수집기가 이미 푼다**: `collector/kosis/matching.py`(`norm`·`KosisTree`·`match`, NAME/SINGLE/CHILD_SUM) · 결과가 `mart.area_resident_pop.kosis_cd`(시군구 5자리) | `kosis/matching.py`, V6 | 인구이동 코드 대응에 같은 함수를 쓰고, 같은 해 시군구는 `kosis_cd` 로 바로 잇는다. SGIS 시도 코드(21 부산 · 31 경기 …)와 행안부 코드를 **접두어로 잇지 않는다**(ADR-009) |
| 지역 지표는 모두 `mart.access_metric(calc_run_id, adm_cd, metric_code, level, value, rnk, pct)` 한 표 + 정의는 `mart.metric_def`(DB 가 유일한 등록처) | V5~V18, `features/meta.metric_catalog` | 지표를 **calc 단계에서** 만들면 지역 카드 · 순위 · 보고서 · GeoJSON · `/metrics available` · 배치 제안 캐시가 그대로 따라온다 |
| 순위는 값 DESC 고정(`10_ranks.sql`), 화면 팔레트는 단색 순차만(`lib/choropleth.ts`), 문구는 "클수록 취약/양호" | `10_ranks.sql`, `lib/rules.ts`, `about/metrics.tsx` | ± 값(순이동)을 그대로 지표로 두면 색·순위가 어색해진다 → **순유출(전출−전입, + = 유출)** 로 정의해 `higher_is_worse=true` |
| 스케줄은 주간 · 일간만(`scheduler.next_run` 8일 창) | `jobs/scheduler.py`, `JobsPanel.tsx:99` | 월 단위 스케줄을 새로 만들지 않고, **빠진 달만 받는 증분 수집기**를 주 1회 돌린다 |
| 계산은 `calc/runner.py` 한 트랜잭션에서 `sql/calc/NN_*.sql` 순서 실행, `10_ranks` 가 마지막; 모든 조인은 `stat_year = run.stat_year` | `calc/runner.py`, `core/db.run_sql_file` | 새 SQL 파일을 `10_ranks` 앞 단계로 등록. 최근 12개월 자료(2026 행정구역)와 경계 연도(2024)가 어긋날 수 있어 대응 실패를 DQ 로 남긴다 |
| 배치 제안 알고리즘(`domain/placement.py`)은 `Area(cd, w, cands)` 만 본다. 경고는 `q.sole_hub` → `soleHubPpltn` 패턴으로 바깥에서 붙인다 | `features/plan/service.py` | 가중치는 바꾸지 않고 **경고 열 하나**만 추가. 응답이 바뀌니 `ALGO_VERSION` 4 → 5, 스냅숏 재기록 |
| 다음 번호: 마이그레이션 **V25**, ADR **ADR-028** | `db/migrations/`, `docs/adr/` | |
| 테스트: Python 385 · 웹 118. `tests/sql/conftest.py clean()` TRUNCATE 목록, `tests/contract/fixtures/*.json` | `docs/quality.md` | 새 표를 TRUNCATE 목록에, 실응답(키 가림)을 contract fixture 로 |

---

## 1. API 사실과 미확인 사항

확인한 것(공공데이터포털 15108093 설명 · 메타데이터, 2026-10-18):
- 전입지 행정기관 / 전출지 행정기관 × 통계년월 기준으로 **전입 시도·시군구·행정동명, 전출 시도·시군구·행정동명, 총인구수, 남·여, 만0세~만110세이상 남/여** 를 준다. 주민등록 기준, **매월 말일 집계**, 거주자·거주불명자·재외국민 포함.
- 무료 · 이용허락 제한 없음 · 개발계정 **일 10,000건**(활용사례 등록 뒤 증량 가능).

미확인(활용명세가 이미지로만 제공) → **0단계 스모크에서 실호출로 확정**:
- 요청 변수 이름과 형식(전입지/전출지 행정기관코드, 통계년월 `YYYYMM`, 집계 수준(시군구/행정동) 선택 변수가 있는지, `numOfRows`/`pageNo`, `type=json`).
- 응답 봉투(`response.header/body` 인지 다른 모양인지), 결과 코드 체계, 행 단위(전입지×전출지 행정동 쌍인지 시군구 쌍인지), 한 시군구·한 달의 행 수(호출 수 추정).
- 자료 시작 월, 최신 월의 공개 지연(며칠 뒤에 전월이 나오는지), 코드 필드 유무(이름만 주면 KOSIS 와 같은 이름 대응).

---

## 2. 설계

### 2-1. 지표 정의 (`mart.metric_def` 에 V25 로 추가)

| metric_code | name_ko | unit | 정의 | higher_is_worse |
|---|---|---|---|---|
| `NET_OUT_12M_PER_1K` | 12개월 순유출(천 명당) | ‰ | (전출 − 전입) 최근 12개월 합 ÷ 주민등록 인구(`area_resident_pop.tot_ppltn`) × 1000. **시군구 사이 이동만**(전입·전출 시군구가 같은 행 제외) | true |
| `AGED65_NET_IN_12M` | 12개월 65세 이상 순유입 | 명 | 전입 − 전출, 만65세 이상 남·여 합, 최근 12개월 | false |

- 창은 **수집된 달 가운데 최근 12개 연속 달**. 12개가 안 차면 지표를 만들지 않고(`available=false`) DQ `MIGR_WINDOW_INCOMPLETE`(WARN).
- 분모는 KOSIS 주민등록 인구(같은 행안부 원천, 이미 SGIS 코드로 대응됨). SGIS 센서스 인구는 쓰지 않는다.
- `formula` · `limitation` 열에 "시군구 간 이동만 · 행정구역 개편 지역은 대응 실패 시 제외 · 공식 통계가 아님" 을 적는다. `unit` 은 10자 제한(‰ 1자).

### 2-2. 저장 — `mart.area_migration_month` (V25)

| 열 | 뜻 |
|---|---|
| `adm_cd varchar(8)`, `stat_year smallint` | SGIS 시군구 코드(level 2) · 대응에 쓴 경계 연도 |
| `ref_ym char(6)` | 통계년월 |
| `in_cnt int`, `out_cnt int` | 시군구 간 전입 · 전출(같은 시군구 안 이동 제외) |
| `in_aged65 int`, `out_aged65 int` | 만65세 이상 전입 · 전출 |
| `in_total_raw int`, `out_total_raw int` | 제외 전 원 합계(검증용) |
| `mois_cd varchar(12)`, `mois_nm`, `match_method CHECK IN ('NAME','SINGLE','KOSIS_CD')` | 행안부 코드 · 대응 방법 |
| `collect_run_id uuid REFERENCES ops.collect_run`, `loaded_at` | |

PK `(adm_cd, ref_ym)`. 시도 행은 시군구 합으로 같은 표에(adm_cd 2자리, `match_method='CHILD_SUM'` 대신 집계 플래그는 두지 않고 level 로 구분 — `admin_area.level` 조인). `GRANT SELECT … TO atlas_api`(기본 권한이 있어도 명시). V25 에 `ops.collect_run` kind CHECK 에 `MOIS_MIGR`, `raw.api_response` source CHECK 에 `MOIS_MIGR` 추가, `metric_def` 2행 `ON CONFLICT DO NOTHING`.

### 2-3. 수집기 — `atlas/atlas/collector/mois/migration.py`

- 패턴은 `collector/datago/care.py`(페이지 · 완전성 · 실행 기록) + `collector/kosis/pipeline.py`(이름 대응 · 부분 실패 처리).
- 대상 = **(시군구, 통계년월)** 쌍. `pending()` = 최근 `MIGR_MONTHS`(기본 13)개 달 × `area_resident_pop` 의 시군구(`kosis_cd` 있음) 가운데 `area_migration_month` 에 없는 것 + 최신 2개 달(늦게 바뀔 수 있음). 호출 단위는 스모크로 정한다 — 전입지 기준 1회 + 전출지 기준 1회가 기본 가정(시군구 250 × 달 → 월 500회, 13개월 백필 약 6,500회로 일 한도 안).
- 행 처리: 전입지 조회에서 **전출 시군구 ≠ 해당 시군구** 인 행만 `in_cnt` 에, 전출지 조회에서 전입 시군구 ≠ 해당 시군구인 행만 `out_cnt` 에. 65세 이상은 `만65세~만110세이상` 남·여 열 합.
- 코드 대응: 응답에 행안부 코드가 있으면 `area_resident_pop.kosis_cd`(같은 `stat_year`) 로 바로 → `KOSIS_CD`; 코드가 없거나 비면 `kosis/matching.py` 의 `norm`·`KosisTree`·`match` 로 이름 대응 → `NAME`/`SINGLE`. 실패는 `DQ MIGR_UNMATCHED`(INFO) 로 남기고 행을 버린다(추정으로 채우지 않음).
- 실행 기록: `runs.start_run("MOIS_MIGR", scope=...)` → `DataGoStop` 이면 받은 것까지 저장하고 `PARTIAL` → `finish_run`. 코드 22 뒤 다음 주 실행이 이어받는다(`pending` 이 DB 상태에서 다시 계산되므로 커서 없음). `BaseException` 에서도 `finish_run(FAILED)`(`test_layers` 가 강제).
- 등록: `jobs/registry.py` `JobSpec("migration", "인구이동(행안부)", _migration, needs=_DATAGO, recalc=True, long=True)` · `collector/cli.py` `collect` choices · `jobs/scheduler.py` 주 1회 `Entry("migration", group="population", times=((5, 30),), weekdays=(1,))`(그룹 `population` 을 `ATLAS_SCHEDULE` 기본값에 넣을지는 §4 결정) · `Makefile` `migration:` 타깃 + `all-data` · `web/pages/quality.tsx` `KIND_LABEL`·`KIND_ORDER`.
- 설정: `core/config.py` 에 `mois_migration_url: str = "https://apis.data.go.kr/1741000/ppltnDataStus"` · `migration_months: int = 13`(기본값만, `.env` 변수는 두지 않음 — 두면 compose 앵커 테스트 `test_compose_env` 대상). `.env.example` 의 `DATA_GO_KR_KEY` 주석에 활용신청 서비스 추가. 키 변수 이름이 `serviceKey` 가 아니면 `masking.SENSITIVE_PARAMS` 에 추가.

### 2-4. 계산 — `atlas/atlas/sql/calc/12_migration.sql` (runner 에 `10_ranks` 앞 단계로 등록)

```sql
-- 최근 12개 연속 달(as_of 이하) 창을 고르고, 시군구 × 창 합을 access_metric 에 넣는다
WITH months AS (SELECT DISTINCT ref_ym FROM mart.area_migration_month WHERE ref_ym <= to_char(:as_of::date, 'YYYYMM') ORDER BY ref_ym DESC LIMIT 12),
 win AS (SELECT min(ref_ym) fr, max(ref_ym) to_, count(*) n FROM months),
 agg AS (SELECT m.adm_cd, sum(out_cnt - in_cnt) net_out, sum(in_aged65 - out_aged65) aged_net_in
           FROM mart.area_migration_month m JOIN months USING (ref_ym) GROUP BY m.adm_cd HAVING count(*) = 12)
INSERT INTO mart.access_metric (calc_run_id, adm_cd, metric_code, level, value)
SELECT :calc_run_id, a.adm_cd, 'NET_OUT_12M_PER_1K', a.level, g.net_out * 1000.0 / r.tot_ppltn
  FROM calc_area a JOIN agg g USING (adm_cd)
  JOIN mart.area_resident_pop r ON r.adm_cd = a.adm_cd AND r.stat_year = :stat_year AND r.tot_ppltn > 0
 WHERE (SELECT n FROM win) = 12
UNION ALL
SELECT :calc_run_id, a.adm_cd, 'AGED65_NET_IN_12M', a.level, g.aged_net_in
  FROM calc_area a JOIN agg g USING (adm_cd) WHERE (SELECT n FROM win) = 12;
```

- 12개 달이 연속인지(`months` 가 빠진 달 없이 이어지는지)는 SQL 에서 `to_date` 차이로 검사하고, 아니면 행을 만들지 않는다. 창(`fr`·`to_`)은 `calc_run.stats` 에 `migrationWindow` 로 남겨 화면 기준 문구(`Layout.tsx basisText()` 의 `kosisRefPeriod` 와 같은 방식)에 쓴다.
- 분모 0 · 인구 없음은 자연히 제외. `AGED65_NET_IN_12M` 은 ± 값이라 순위는 값 DESC(유입 많은 곳이 1위) — `higher_is_worse=false` 로 "양호 쪽" 문구가 맞는다.
- 읍면동(level 3)은 v1 에서 만들지 않는다(호출 ×14, 화면 요구 없음). 보고서 읍면동 지도(`EMD_METRICS`)에는 넣지 않는다.

### 2-5. API · 화면

| 곳 | 변경 |
|---|---|
| `GET /areas/{admCd}` | `migration: {refFrom, refTo, inCnt, outCnt, netOut, aged65NetIn, source:"행정안전부 주민등록 인구이동", loadedAt} \| null` — `residentPop` 블록과 같은 방식(`queries.resident_pop` 모델). 12개월 합은 `area_migration_month` 를 직접 읽는다(지표와 같은 창) |
| `GET /areas/{admCd}/report` | `KEY_METRICS` 에 `NET_OUT_12M_PER_1K` 추가(전국 중앙값 비교 표) · `area` 에 `migration` 요약 |
| `GET /metrics` | 자동(`metric_def`) |
| `POST /plan/close` · `/open` | 각 step 과 `leastImpact`/`mostCritical` 에 `netOutPer1k`(해당 시설이 속한 시군구의 `NET_OUT_12M_PER_1K`, 없으면 null) — `q.sole_hub` 패턴으로 `q.migration_trend(c, run_id, adm_cds)`. 가중치 · 알고리즘은 그대로. `ALGO_VERSION` "4" → "5" |
| 웹 `components/RegionCard.tsx` | "인구 이동 · 행안부" 블록(12개월 전입/전출/순유출/65+ 순유입, 기준 창). 지표 목록은 자동 |
| 웹 `lib/format.ts` | `METRIC_GROUP` 에 두 코드 → 그룹 "인구 추세", `GROUP_ORDER` 에 추가; `withUnit` 은 ‰ 를 `num(v,1)+unit` 으로 이미 처리 |
| 웹 `pages/report/[admCd].tsx` | 핵심 지표 표에 자동 포함(`KEY_METRICS`), `Fact` 카드 1장 "12개월 순유출" |
| 웹 `pages/plan.tsx` | 표에 "순유출(‰)" 열 + `badge-warn`(순유출 상위 20% 시군구 — 기준은 `percentile` 로, 숫자 임계값은 두지 않음) |
| 웹 `pages/rankings.tsx` | 머리글 문구 `접근성 취약 쪽` 이 접근성 전용이라 지표 그룹이 "인구 추세" 면 `유출 많은 쪽 / 유입 많은 쪽` 으로 바꾸는 분기 |
| 웹 `pages/about/metrics.tsx` | 자동(`metric_def`) · 출처 문단에 행안부 인구이동 추가 |
| `web/lib/api.ts` | `AreaDetail.migration`, `PlanClose/PlanFacility` 의 `netOutPer1k` 타입 |

### 2-6. 테스트

- 단위: `tests/unit/test_mois_parse.py`(contract fixture → 행 변환 · 65세 합 · 같은 시군구 제외) · 코드 대응은 기존 `test_kosis_matching.py` 재사용 + 인구이동 케이스 2개.
- DB: `tests/sql/test_collect_guards.py` 에 수집기 가드(FakeFetcher · 코드 22 중단 시 PARTIAL + 받은 달 유지 · 빈 응답에 기존 달 삭제 안 함) · `tests/sql/test_calc_metrics.py::test_migration_metrics`(13개월 중 12개 연속 → 값, 11개 → 행 없음 · 분모 0 제외) · `tests/sql/test_api_snapshots.py` 재기록(`metrics.json` · `area_detail.json` · `area_report.json` · `plan_close.json` · `plan_open.json`, `UPDATE_SNAPSHOTS=1` 뒤 diff 검토) · `test_jobs_security.py::test_api_role_least_privilege` 통과 확인.
- 웹: `lib/format.test.ts`(그룹 · ‰) · `pages` 타입 검사 · vitest. `scripts/qa/fuzz.py` 엔드포인트 목록에 변경 없음(새 경로 없음, 새 필드만).
- 수집 실측: `make migration` 1회(일 한도 안에서 13개월 백필 가능한지 측정) → `make calc` → `/areas?metric=NET_OUT_12M_PER_1K` 상위·하위 지역이 상식과 맞는지 확인 · 대응 실패 건수(DQ) 기록.

---

## 3. 진행 순서와 묶음

0. **스모크** — `DATA_GO_KR_KEY` 로 실호출 1~3건(키 값 출력 금지): 요청 변수 · 봉투 · 행 단위 · 월 공개 지연 확정, 응답(키 가림)을 `tests/contract/fixtures/mois_migration_sample.json` 으로. `client.call()` 이 봉투를 못 읽으면 `_error_of` 일반화를 먼저.
1. **V25 + 수집기** — 표 · CHECK · `metric_def` · 수집기 · 레지스트리 · CLI · 스케줄 · Makefile · 품질 화면 라벨 · 단위/가드 테스트. 검증: `make test`(Python) → `make migration` 실측 → `atlas status`.
2. **계산 + 지표** — `12_migration.sql` · runner 등록 · `stats.migrationWindow` · calc 테스트 · 스냅숏(`metrics.json`). 검증: `make calc` → `/metrics` 에서 `available=true`.
3. **API · 화면** — 지역 카드 · 보고서 · 순위 문구 · 배치 제안 경고(`ALGO_VERSION` 5) · 타입 · 웹 테스트 · 스냅숏 재기록. 검증: `cd web && npx tsc --noEmit && npm test && npm run lint`, `make qa`(크롤·요청 점검) 1회.
4. **문서** — `docs/adr/ADR-028-population-migration.md`(모델 ADR-009 · 015: 맥락 · 결정 · 제외한 것과 이유(읍면동 미수집 · 가중치 미변경) · 한계) · `docs/README.md` ADR·API·마이그레이션 표 · README §1 키 표(활용신청) · §3 갱신 표(주 1회 증분) · §4 지표 표 · 출처 · `docs/CHANGELOG.md` · `docs/quality.md` 테스트 수.

---

## 4. 결정이 필요한 것 (구현 전에 답할 것)

| # | 결정 | 선택지 | 권장 |
|---|---|---|---|
| 1 | 65세 이상 지표를 넣을지 | (a) 순유출 하나만 (b) 둘 다 | **(b)** — 우체국 주제(고령 이용자)와 맞고 같은 응답에서 나와 비용이 없음 |
| 2 | 배치 제안에 반영 방식 | (a) 경고 열만 (b) 가중치(`aged65_trend`) 추가 | **(a)** — 알고리즘 · 스냅숏 영향 최소. (b) 는 ADR 로 따로 |
| 3 | 스케줄 그룹 | (a) 새 그룹 `population` 을 `ATLAS_SCHEDULE` 기본값에 추가 (b) 수동만 | **(a)** 주 1회 · 증분이라 호출 수백 건 |
| 4 | 백필 길이 | 13개월(기본) / 25개월(전년 동기 비교 가능) | 13개월로 시작, 한도 여유를 보고 25개월 |

---

## 5. 하지 않기로 한 것과 이유

| API | 이유 |
|---|---|
| 기상청 기상특보 조회서비스 | 방문 여건은 이미 단기예보 · 에어코리아로 판정하며 "공식 특보가 아님"을 명시한다(ADR-011). 특보를 넣으려면 구역 코드가 구조화된 **기상청 API허브 특보현황**(Wakeline 에서 쓰는 것)이 맞고, 이 서비스는 통보문 텍스트 위주라 시군구 매핑 신뢰성이 낮다 |
| 건강보험심사평가원 병원정보서비스 | 병의원은 국립중앙의료원 전수(`collector/datago/care.py`)로 이미 받는다. 진료과목 필터(소아청소년과 없는 지역)는 가능하지만 우체국 주제에서 벗어난다 |
| 그 외(실거래 · 청약홈 · 금융위 · whois · CCTV 도로날씨) | 주제와 무관 |

---

## 6. 한계 (ADR · 화면 문구에 그대로)

- 주민등록 전입신고 기준이라 실제 거주 이동과 다를 수 있고, 거주불명자 · 재외국민이 포함된다(원천 설명).
- 시군구 간 이동만 센다. 같은 시군구 안 이동은 제외하므로 다른 통계(통계청 국내인구이동, 시도 내 이동 포함)와 수치가 다르다.
- 최근 12개월 자료의 행정구역과 경계 연도(`STAT_YEAR`)가 다를 수 있다 — 대응 실패 지역은 지표 없음으로 두고 DQ 에 남긴다.
- 분석용 지표이며 공식 통계가 아니다(기존 면책 문구와 같음).

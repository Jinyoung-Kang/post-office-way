# ADR-012 작업 큐·워커 분리, 마이그레이션 전용 단계, 최소 권한 DB 역할

- 상태: 채택 (2026-09-25)

## 맥락
- 관리 API(`POST /admin/collect/*`)가 **API 프로세스 스레드**에서 수집기·계산을 돌렸다. 긴 작업(도로 거리 25분)이
  웹 요청 워커의 자원을 쓰고, API 재시작 때 작업이 조용히 사라지며, API 가 모든 표에 쓰기 권한을 가져야 했다.
- API 가 기동할 때 마이그레이션(DDL)을 적용해, 조회용 서비스가 스키마 소유자 권한으로 접속했다.
- 예보·공휴일처럼 정해진 시각에 받아야 하는 자료가 생겼는데 실행 수단이 수동(`make`)뿐이었다.

## 결정
1. **Postgres 작업 큐(`ops.job`)** — 별도 브로커(Redis 큐·Celery·RabbitMQ) 없이 DB 하나로.
   - API 는 `INSERT` + `NOTIFY atlas_jobs` 만 하고 202 를 돌려준다.
   - 워커는 `UPDATE … WHERE job_id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1)` 로 한 건씩 가져간다 → 워커를 늘려도 중복 실행 없음.
   - 같은 종류는 대기·실행 중 하나만(`ux_job_active` 부분 유니크 인덱스, 중복 요청은 409).
   - 30초 하트비트, 10분 끊기면 재시도(최대 2회) 또는 FAILED(`reap`). 수집이 끝나면 **지표 재계산을 자동으로 이어서** 넣는다(`source=chain`).
   - 대기 중에는 `LISTEN` 으로 잠들어 있다가 알림에 즉시 깨어난다(폴링 30초는 스케줄 확인 겸 안전망).
2. **스케줄러는 워커 안에** — 예정 시각 뒤 30분 창 안이면 `slot` 고유키(`kma@2026-09-25T05:20`)로 한 번만 넣는다.
   워커가 꺼져 있던 동안 지난 슬롯은 몰아서 실행하지 않는다(지난 예보는 의미 없음). 그룹은 `ATLAS_SCHEDULE`.
3. **마이그레이션 전용 단계** — compose `migrate` 서비스(소유자 권한)가 적용 후 종료하고, api·worker 는
   `service_completed_successfully` 를 기다린다. API 는 기동 때 `pending()` 으로 **확인만** 하고 `/health` 가 알린다.
4. **최소 권한 역할 `atlas_api`** (V12) — mart·ops 조회, What-if 결과·작업 요청 INSERT, 대기 작업 취소 UPDATE(열 단위)만.
   raw(원본 응답)·stg 접근 없음, DDL 없음, 역할 단위 `statement_timeout=15s`·`lock_timeout=3s`·`idle_in_transaction_session_timeout=30s`.
   비밀번호는 SQL 파일이 아니라 `.env API_DB_PASSWORD`(make env 가 생성) → `atlas migrate` 가 `ALTER ROLE … PASSWORD` 로 설정.
5. **단일 작업 목록(`atlas.jobs.registry`)** — CLI·API·워커·스케줄러가 같은 목록(필요 키, 실행 함수, 재계산 필요 여부)을 본다.

## 결과
- API 프로세스는 조회·What-if 만 한다. 권한 테스트(`test_api_role_least_privilege`)가 raw 조회·DELETE·DDL·열 밖 UPDATE 거부를 고정한다.
- 운영 화면(데이터·운영)에서 작업 큐·스케줄·다음 실행 시각·키 누락을 본다.
- 대안: Celery+Redis(브로커 운영 부담, 작업 기록이 DB 밖), pg_cron(DB 확장·파이썬 코드 실행 불가), APScheduler 단독(다중 워커 중복 실행).

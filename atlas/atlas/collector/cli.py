"""배치 진입점 — `atlas <command>` (docker compose run --rm collector <command>).

  atlas migrate                          스키마 적용
  atlas smoke                            키 3종 동작 확인 + 응답을 fixtures/ 에 저장
  atlas discover post [--range 100-799]  우편 지역코드 seed 생성
  atlas collect post [--scope 100,101] [--resume RUN_ID]
  atlas collect sgis|sgis-pop|sgis-bnd
  atlas collect kosis                    KOSIS 주민등록인구(65세 이상) — 키 없으면 건너뜀
  atlas collect oa [--refresh]           ① SGIS 집계구 인구·경계 (이어받기 가능)
  atlas collect road [--max-calls N]     ② 카카오모빌리티 도로 거리 (캐시·예산 안에서 이어서)
  atlas collect geocheck [--max-calls N] ③ 카카오 주소 검색으로 시설 좌표 검증
  atlas collect banks                    ④ 카카오 로컬 은행·금고 지점
  atlas collect weather|kma|air          ⑥ 방문 여건 — 기상청 단기예보·에어코리아 미세먼지 예보 (하루 1~3회)
  atlas collect care|holidays            ⑦ 약국·병의원(국립중앙의료원) · 공휴일(한국천문연구원 특일)
  atlas worker [--once]                  작업 큐 워커 + 스케줄러 (API 가 넣은 작업 실행)
  atlas enqueue KIND [--param k=v]       작업을 큐에 넣기 · atlas jobs 최근 작업 · atlas schedule 스케줄
  atlas calc [--levels 2,3]
  atlas status                           최근 수집·계산 현황
  atlas prune [--keep 3]                 오래된 원문(raw)·스냅샷(stg) 정리 — 종류별 최근 N개 run 만 남김
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import text

from atlas.core.config import get_settings
from atlas.core.db import get_engine
from atlas.core.logging import setup_logging
from atlas.core.migrate import migrate


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_migrate(_: argparse.Namespace) -> int:
    from atlas.core.migrate import set_role_password

    applied = migrate(get_engine())
    # API 전용 최소 권한 역할(V12)의 비밀번호 — .env API_DB_PASSWORD (make env 가 생성)
    set_role_password(get_engine(), "atlas_api", get_settings().api_db_password)
    _print({"applied": applied, "apiRole": "atlas_api" if get_settings().api_db_password else "비밀번호 없음(API_DB_PASSWORD)"})
    return 0


def cmd_discover(a: argparse.Namespace) -> int:
    from atlas.collector.post.discover import discover

    lo, hi = (int(x) for x in a.range.split("-"))
    path, n = discover(lo, hi, extra=[x for x in (a.extra or "").split(",") if x])
    _print({"seed": path, "codes": n})
    return 0


COLLECT_ALIASES = {"weather": ("kma", "air"), "sgis": ("sgis",)}


def cmd_collect(a: argparse.Namespace) -> int:
    """수집을 이 프로세스에서 바로 실행 (make 명령용). 워커로 보내려면 `atlas enqueue`."""
    from atlas.jobs import registry

    params = {"scope": a.scope, "resume": a.resume, "refresh": a.refresh, "maxCalls": a.max_calls, "recalc": False}
    ids: list[str] = []
    for kind in COLLECT_ALIASES.get(a.what, (a.what,)):
        spec = registry.get(kind)
        if miss := spec.missing():
            print(f"{spec.title}: .env 에 {', '.join(miss)} 가 없어 건너뜁니다 (넣으면 켜집니다).")
            continue
        ids += registry.run(kind, params).get("collectRunIds", [])
    if not ids:
        return 0
    with get_engine().connect() as c:
        rows = c.execute(text("""SELECT collect_run_id, kind, status, stats - 'doneCodes' - 'failedCodes' AS stats,
                                        jsonb_array_length(CASE WHEN jsonb_typeof(stats->'failedCodes') = 'array'
                                                                THEN stats->'failedCodes' ELSE '[]' END) AS failed, error
                                 FROM ops.collect_run WHERE collect_run_id = ANY(CAST(:ids AS uuid[]))"""),
                         {"ids": [str(i) for i in ids]}).mappings().all()
    _print([dict(r) for r in rows])
    ok = all(r["status"] in ("DONE", "PARTIAL") for r in rows)
    if any((r["stats"] or {}).get("remaining") for r in rows):
        print("\n→ 아직 남은 대상이 있습니다. 같은 명령을 다시 실행하면 이어서 채웁니다(쿼터·예산 보호).")
    if ok and a.what in ("weather", "kma", "air", "holidays"):
        print("\n→ 화면 「방문 여건」에 바로 반영됩니다(다시 계산할 필요 없음).")
    elif ok and a.what not in ("post", "geocheck"):
        # 인구·경계·주민등록 값은 calc 때 지표로 굳어지므로, 새로 적재했으면 다시 계산해야 화면에 반영됨
        print("\n→ 지표에 반영하려면 `make calc` 를 실행하세요.")
    return 0 if ok else 1


def cmd_calc(a: argparse.Namespace) -> int:
    from atlas.calc.runner import run_calc

    levels = [int(x) for x in a.levels.split(",")] if a.levels else None
    rid = run_calc(stat_year=a.year, levels=levels)
    with get_engine().connect() as c:
        r = c.execute(text("SELECT status, stats FROM mart.calc_run WHERE calc_run_id = :id"), {"id": rid}).one()
    _print({"calcRunId": rid, "status": r[0], "stats": r[1]})
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    with get_engine().connect() as c:
        runs = c.execute(text("""SELECT DISTINCT ON (kind) kind, status, started_at, finished_at,
                                        stats->'rows' AS rows, stats->'calls' AS calls,
                                        jsonb_array_length(coalesce(stats->'failedCodes', '[]')) AS failed
                                 FROM ops.collect_run ORDER BY kind, started_at DESC""")).mappings().all()
        calc = c.execute(text("""SELECT calc_run_id, status, created_at, stats->'areas' AS areas, error
                                 FROM mart.calc_run ORDER BY created_at DESC LIMIT 1""")).mappings().first()
        counts = c.execute(text("""SELECT
            (SELECT count(*) FROM mart.post_facility_hist WHERE is_current) AS facilities_current,
            (SELECT count(*) FROM mart.post_facility_hist WHERE is_current AND fin_available) AS fin_available,
            (SELECT count(*) FROM mart.admin_area) AS areas,
            (SELECT count(*) FROM mart.area_population) AS population_rows,
            (SELECT count(*) FROM mart.area_resident_pop) AS kosis_rows""")).mappings().one()
    s = get_settings()
    _print({"keys": {"POST_SERVICE_KEY": bool(s.post_service_key), "SGIS_CONSUMER_KEY": bool(s.sgis_consumer_key),
                     "SGIS_CONSUMER_SECRET": bool(s.sgis_consumer_secret), "KOSIS_API_KEY": bool(s.kosis_api_key),
                     "KAKAO_REST_API_KEY": bool(s.kakao_rest_api_key), "DATA_GO_KR_KEY": bool(s.data_go_kr_key)},
            "collect": [dict(r) for r in runs], "latestCalc": dict(calc) if calc else None, "counts": dict(counts)})
    return 0


def cmd_prune(a: argparse.Namespace) -> int:
    """raw 원문은 재처리용, stg 는 병합용 스냅샷 — 수집마다 약 10MB 씩 늘어 종류별 최근 N개 run 만 남깁니다.
    계산 결과도 계산마다 약 25MB(집계구 최근접 10만 행 등)라 최근 N개 계산만 남깁니다.
    품질 이슈는 이력으로 남기되 INFO(수천 건 반복)만 함께 정리합니다."""
    keep, keep_calc = max(1, a.keep), max(1, a.keep_calc)
    with get_engine().begin() as c:
        # 계산 결과(지표·최근접·집계구 최근접·What-if)는 계산마다 약 25MB — 최근 N개 계산만 남김(가장 최근 DONE 은 항상 보존)
        old_calc = f"""SELECT calc_run_id FROM (
                          SELECT calc_run_id, row_number() OVER (ORDER BY created_at DESC) AS rn FROM mart.calc_run
                           WHERE status <> 'RUNNING') x WHERE rn > {keep_calc}
                        AND calc_run_id <> (SELECT calc_run_id FROM mart.calc_run WHERE status = 'DONE'
                                             ORDER BY finished_at DESC NULLS LAST LIMIT 1)"""
        c.execute(text(f"DELETE FROM ops.dq_issue WHERE calc_run_id IN ({old_calc})"))
        c.execute(text(f"DELETE FROM ops.dq_check WHERE calc_run_id IN ({old_calc})"))
        calc = c.execute(text(f"DELETE FROM mart.calc_run WHERE calc_run_id IN ({old_calc})")).rowcount
        old = f"""SELECT collect_run_id FROM (
                     SELECT collect_run_id, row_number() OVER (PARTITION BY kind ORDER BY started_at DESC) AS rn
                       FROM ops.collect_run WHERE status <> 'RUNNING') x WHERE rn > {keep}"""
        raw = c.execute(text(f"DELETE FROM raw.api_response WHERE collect_run_id IN ({old})")).rowcount
        stg = c.execute(text(f"DELETE FROM stg.post_facility WHERE collect_run_id IN ({old})")).rowcount
        info = c.execute(text(f"DELETE FROM ops.dq_issue WHERE severity = 'INFO' AND collect_run_id IN ({old})")).rowcount
        size = c.execute(text("SELECT pg_size_pretty(pg_total_relation_size('raw.api_response'))")).scalar()
    _print({"keepPerKind": keep, "keepCalc": keep_calc,
            "deleted": {"raw": raw, "stg": stg, "dqInfo": info, "calcRuns": calc}, "rawTableSize": size,
            "note": "디스크 공간은 PostgreSQL autovacuum 이 재사용합니다."})
    return 0


def cmd_worker(a: argparse.Namespace) -> int:
    from atlas.jobs.worker import run_forever

    run_forever(poll_s=a.poll, once=a.once)
    return 0


def cmd_enqueue(a: argparse.Namespace) -> int:
    from atlas.jobs import queue, registry

    registry.get(a.kind)
    params = dict(kv.split("=", 1) for kv in a.param or [])
    try:
        jid = queue.enqueue(a.kind, params, source="cli", requested_by="cli")
    except queue.JobConflict as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    _print({"jobId": jid, "kind": a.kind, "status": "QUEUED", "check": "atlas jobs"})
    return 0


def cmd_jobs(a: argparse.Namespace) -> int:
    from atlas.jobs import queue

    _print([{k: v for k, v in j.items() if k not in ("result",)} for j in queue.recent(a.limit)])
    return 0


def cmd_schedule(_: argparse.Namespace) -> int:
    from atlas.core.clock import now_kst
    from atlas.jobs import scheduler

    _print({"ATLAS_SCHEDULE": get_settings().atlas_schedule,
            "entries": scheduler.describe(now_kst(), get_settings().atlas_schedule)})
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    from atlas.tools.bench import print_table, run

    res = run(base=a.base, n=a.requests, conc=a.concurrency)
    print_table(res)
    if a.json:
        _print(res)
    return 0


def cmd_smoke(_: argparse.Namespace) -> int:
    from atlas.collector.smoke import smoke

    ok = smoke()
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="atlas", description="우체국 접근성 아틀라스 배치")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    sub.add_parser("smoke").set_defaults(fn=cmd_smoke)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    pr = sub.add_parser("prune")
    pr.add_argument("--keep", type=int, default=3, help="종류별로 남길 최근 수집 run 수")
    pr.add_argument("--keep-calc", type=int, default=5, help="남길 최근 계산 run 수 (지난 What-if 결과도 함께 삭제)")
    pr.set_defaults(fn=cmd_prune)
    d = sub.add_parser("discover")
    d.add_argument("what", choices=["post"])
    d.add_argument("--range", default="100-799")
    d.add_argument("--extra", default="", help="범위 밖 추가 코드(쉼표)")
    d.set_defaults(fn=cmd_discover)
    c = sub.add_parser("collect")
    c.add_argument("what", choices=["post", "sgis", "sgis-pop", "sgis-bnd", "kosis", "oa", "road", "geocheck", "banks",
                                   "weather", "kma", "air", "care", "holidays"])
    c.add_argument("--refresh", action="store_true", help="집계구 경계를 전부 다시 받기 (oa)")
    c.add_argument("--max-calls", type=int, help="호출 예산 (road·geocheck)")
    c.add_argument("--scope", help="지역코드 목록 (post)")
    c.add_argument("--resume", help="이어서 수집할 collect_run_id (post)")
    c.set_defaults(fn=cmd_collect)
    w = sub.add_parser("worker", help="작업 큐 워커 + 스케줄러 (compose 서비스 worker)")
    w.add_argument("--poll", type=float, default=30.0, help="알림이 없을 때 깨어나는 주기(초)")
    w.add_argument("--once", action="store_true", help="대기열이 빌 때까지만 실행하고 종료")
    w.set_defaults(fn=cmd_worker)
    q = sub.add_parser("enqueue", help="작업을 큐에 넣기 (워커가 실행)")
    q.add_argument("kind")
    q.add_argument("--param", action="append", help="key=value")
    q.set_defaults(fn=cmd_enqueue)
    j = sub.add_parser("jobs", help="최근 작업")
    j.add_argument("--limit", type=int, default=20)
    j.set_defaults(fn=cmd_jobs)
    sub.add_parser("schedule", help="스케줄과 다음 실행 시각").set_defaults(fn=cmd_schedule)
    bn = sub.add_parser("bench", help="API 부하 측정 (p50/p95·처리량·느린 SQL)")
    bn.add_argument("--base", default="http://api:8100")
    bn.add_argument("--requests", type=int, default=200)
    bn.add_argument("--concurrency", type=int, default=16)
    bn.add_argument("--json", action="store_true")
    bn.set_defaults(fn=cmd_bench)
    k = sub.add_parser("calc")
    k.add_argument("--levels")
    k.add_argument("--year", type=int)
    k.set_defaults(fn=cmd_calc)
    return p


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    if args.cmd != "migrate":
        migrate(get_engine())
    try:
        return args.fn(args)
    except RuntimeError as e:
        print(f"\n오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

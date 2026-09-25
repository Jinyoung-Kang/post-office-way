"""작업 종류 목록 — 각 작업이 필요한 키, 실행 함수, 끝나면 지표 재계산이 필요한지.

API·CLI·워커·스케줄러가 모두 이 목록만 봅니다(종류를 추가할 때 한 곳만 고치면 됨).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from atlas.core.config import Settings, get_settings


class MissingKey(RuntimeError):
    """작업에 필요한 키가 .env 에 없음."""


@dataclass(frozen=True)
class JobSpec:
    kind: str
    title: str
    run: Callable[[dict[str, Any]], dict[str, Any]]
    needs: tuple[str, ...] = ()          # Settings 속성 이름 (예: "kakao_rest_api_key")
    recalc: bool = False                 # 끝나면 지표에 반영하려면 calc 가 필요한 작업
    long: bool = False                   # 10분 넘게 걸릴 수 있음 (하트비트만으로 생존 판단)

    def missing(self, s: Settings | None = None) -> list[str]:
        s = s or get_settings()
        return [k.upper() for k in self.needs if not getattr(s, k)]


def _ids(*ids: uuid.UUID | None) -> dict[str, Any]:
    return {"collectRunIds": [str(i) for i in ids if i]}


def _post(p: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.post.pipeline import collect_post

    scope = p.get("scope")
    return _ids(collect_post(scope=scope.split(",") if isinstance(scope, str) else scope,
                             resume=uuid.UUID(p["resume"]) if p.get("resume") else None))


def _sgis(what: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def run(_: dict[str, Any]) -> dict[str, Any]:
        from atlas.collector.sgis.pipeline import collect_sgis

        return _ids(*collect_sgis(what))
    return run


def _kosis(_: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.kosis.pipeline import collect_kosis

    return _ids(collect_kosis())


def _oa(p: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.sgis.oa import collect_oa

    return _ids(collect_oa(refresh=bool(p.get("refresh"))))


def _road(p: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.kakao.road import collect_road

    return _ids(collect_road(max_calls=p.get("maxCalls")))


def _geocheck(p: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.kakao.geocheck import run_geocheck

    return _ids(run_geocheck(max_checks=p.get("maxCalls") or 8000))


def _banks(_: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.kakao.banks import collect_banks

    return _ids(collect_banks())


def _kma(_: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.weather.kma import collect_kma

    return _ids(collect_kma())


def _air(_: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.weather.air import collect_air

    return _ids(collect_air())


def _care(_: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.datago.care import collect_care

    return _ids(collect_care())


def _holidays(p: dict[str, Any]) -> dict[str, Any]:
    from atlas.collector.datago.holiday import collect_holidays

    return _ids(collect_holidays(years=p.get("years")))


def _calc(p: dict[str, Any]) -> dict[str, Any]:
    from atlas.calc.runner import run_calc

    return {"calcRunId": str(run_calc(stat_year=p.get("statYear"), levels=p.get("levels"), params=p.get("params")))}


_DATAGO = ("data_go_kr_key",)
_KAKAO = ("kakao_rest_api_key",)
_SGIS = ("sgis_consumer_key", "sgis_consumer_secret")

JOBS: dict[str, JobSpec] = {j.kind: j for j in (
    JobSpec("post", "우체국 시설", _post, ("post_service_key",), recalc=True),
    JobSpec("sgis", "SGIS 인구·경계", _sgis("all"), _SGIS, recalc=True),
    JobSpec("sgis-pop", "SGIS 인구", _sgis("pop"), _SGIS, recalc=True),
    JobSpec("sgis-bnd", "SGIS 경계", _sgis("bnd"), _SGIS, recalc=True),
    JobSpec("kosis", "KOSIS 주민등록인구", _kosis, ("kosis_api_key",), recalc=True),
    JobSpec("oa", "SGIS 집계구", _oa, _SGIS, recalc=True, long=True),
    JobSpec("banks", "은행·금고 지점", _banks, _KAKAO, recalc=True, long=True),
    JobSpec("road", "도로 거리", _road, _KAKAO, recalc=True, long=True),
    JobSpec("geocheck", "주소 좌표 검증", _geocheck, _KAKAO, long=True),
    JobSpec("kma", "기상청 단기예보", _kma, _DATAGO),
    JobSpec("air", "에어코리아 예보", _air, _DATAGO),
    JobSpec("care", "약국·병의원", _care, _DATAGO, recalc=True),
    JobSpec("holidays", "공휴일(특일)", _holidays, _DATAGO),
    JobSpec("calc", "지표 계산", _calc),
)}


def get(kind: str) -> JobSpec:
    if kind not in JOBS:
        raise KeyError(kind)
    return JOBS[kind]


def run(kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = get(kind)
    if miss := spec.missing():
        raise MissingKey(f"{spec.title}: .env 에 {', '.join(miss)} 가 없습니다.")
    return spec.run(params or {})

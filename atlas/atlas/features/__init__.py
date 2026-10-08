"""API 가 쓰는 기능 모듈 — 흐름(service)과 조회(queries). HTTP 를 모르고, 규칙은 atlas.domain, 공용 기반은 atlas.core.

의존 방향: api.routers → features → domain·calc.runs·core (반대 방향 import 없음, tests/unit/test_layers.py 가 확인).
"""

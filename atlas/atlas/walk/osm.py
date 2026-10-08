"""② OSM 한국 도로망 내려받기 + 도보 그래프 만들기 (`atlas collect osm`, 작업 kind=osm).

- 같은 파일이면 다시 받지 않음(서버 Last-Modified 비교). 받은 뒤 Geofabrik 의 .md5 로 무결성 확인, 다 받은 뒤에만 바꿔치기.
- 그래프(.npz)는 파일이 바뀌었거나 그래프 규칙(GRAPH_VERSION)이 바뀌었을 때만 다시 만듦.
- 실행 기록은 ops.collect_run(kind=OSM_WALK). 원본 파일은 수백 MB 라 raw 스키마에 넣지 않음.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from atlas.collector import runs
from atlas.core.config import get_settings

log = logging.getLogger(__name__)
GRAPH_VERSION = 1            # graph.py 의 규칙(걸을 수 있는 길·꼭짓점 간격)을 바꾸면 올림 → 그래프 다시 만듦
CHUNK = 1 << 20


def paths() -> dict[str, Path]:
    d = Path(get_settings().osm_dir)
    return {"dir": d, "pbf": d / "south-korea.osm.pbf", "meta": d / "meta.json", "graph": d / "walk_graph.npz"}


def read_meta() -> dict[str, Any]:
    p = paths()["meta"]
    return json.loads(p.read_text()) if p.exists() else {}


def _download(url: str, dest: Path, meta: dict[str, Any], client: httpx.Client) -> dict[str, Any]:
    """바뀌었을 때만 받음. 반환: {"downloaded": bool, "lastModified", "bytes", "md5"}"""
    head = client.head(url, follow_redirects=True)
    head.raise_for_status()
    last_mod = head.headers.get("last-modified")
    if dest.exists() and last_mod and meta.get("lastModified") == last_mod:
        return {"downloaded": False, "lastModified": last_mod, "bytes": dest.stat().st_size, "md5": meta.get("md5")}
    want = client.get(url + ".md5", follow_redirects=True)
    want.raise_for_status()
    want_md5 = want.text.split()[0].strip().lower()
    tmp = dest.with_suffix(".part")
    h = hashlib.md5()                                   # 무결성 확인용(보안 해시 아님) — 제공자가 md5 만 줌
    size = 0
    with client.stream("GET", url, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(CHUNK):
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
    got = h.hexdigest()
    if got != want_md5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"OSM 파일 md5 불일치 (받은 {got[:8]}…, 기대 {want_md5[:8]}…) — 다시 실행하세요.")
    tmp.replace(dest)
    return {"downloaded": True, "lastModified": last_mod, "bytes": size, "md5": got}


def refresh(force_graph: bool = False) -> dict[str, Any]:
    """OSM 파일 갱신 + 필요하면 그래프 다시 만들기. 반환에 collectRunIds."""
    from atlas.walk.graph import build

    s = get_settings()
    p = paths()
    p["dir"].mkdir(parents=True, exist_ok=True)
    run_id = runs.start_run("OSM_WALK", scope=f"url={s.osm_pbf_url};graphVersion={GRAPH_VERSION}")
    stats: dict[str, Any] = {}
    t0 = time.monotonic()
    try:
        meta = read_meta()
        with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), headers={"User-Agent": "post-office-way/0.2"}) as client:
            dl = _download(s.osm_pbf_url, p["pbf"], meta, client)
        stats["download"] = dl
        need_graph = (force_graph or dl["downloaded"] or not p["graph"].exists()
                      or meta.get("graphVersion") != GRAPH_VERSION)
        if need_graph:
            g = build(p["pbf"], p["dir"])
            g.meta.update({"osmLastModified": dl["lastModified"], "graphVersion": GRAPH_VERSION})
            g.save(p["graph"])
            stats["graph"] = g.meta
        else:
            stats["graph"] = meta.get("graph", {})
            stats["graphReused"] = True
        p["meta"].write_text(json.dumps({"lastModified": dl["lastModified"], "md5": dl["md5"], "bytes": dl["bytes"],
                                         "graphVersion": GRAPH_VERSION, "graph": stats["graph"]}, ensure_ascii=False))
        stats["elapsedMs"] = int((time.monotonic() - t0) * 1000)
        runs.finish_run(run_id, "DONE", stats)
    except Exception as e:
        runs.finish_run(run_id, "FAILED", stats, error=f"{type(e).__name__}: {e}")
        raise
    return {"collectRunIds": [str(run_id)], "graphBuilt": need_graph, **{k: stats[k] for k in ("download",)}}

"""스모크 테스트 (준비 가이드 3장) — 키(우체국·SGIS·선택 KOSIS)가 실제로 동작하는지 확인하고 응답을 fixtures/ 에 저장.

저장 전에 키·토큰을 마스킹합니다. 이 파일들은 계약 테스트 기준 데이터로 쓸 수 있습니다.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from atlas.collector.post.parser import parse_post_xml
from atlas.collector.sgis.client import parse_timeout
from atlas.collector.sgis.pipeline import detect_srid
from atlas.core.config import get_settings
from atlas.core.masking import mask_secrets_in, mask_text

FIXTURES = Path("/app/fixtures") if Path("/app/fixtures").exists() else Path(__file__).resolve().parents[3] / "fixtures"


def _save(name: str, body: str, secrets: list[str]) -> Path:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    p = FIXTURES / name
    p.write_text(mask_secrets_in(mask_text(body), secrets), encoding="utf-8")
    return p


def smoke() -> bool:
    s = get_settings()
    secrets = [s.post_service_key, s.sgis_consumer_key, s.sgis_consumer_secret]
    ok = True
    with httpx.Client(timeout=20, follow_redirects=True) as h:
        print("① 우체국 찾기 — 반경 조회")
        if not s.post_service_key:
            print("   ✗ POST_SERVICE_KEY 없음"); ok = False
        else:
            r = h.get(f"{s.post_base_url}/searchPostScopeList.do",
                      params={"serviceKey": s.post_service_key, "postLatitude": 37.56, "postLongitude": 126.98,
                              "postGap": 0.5, "postDivType": 1})
            pg = parse_post_xml(r.text)
            print(f"   HTTP {r.status_code} · items={len(pg.items)} · error={pg.error} → {_save('post_scope_sample.xml', r.text, secrets)}")
            ok &= r.status_code == 200 and not pg.error

            print("② 우체국 찾기 — 지역 조회 (postOffiId=100)")
            r = h.get(f"{s.post_base_url}/searchPostAreaList.do",
                      params={"serviceKey": s.post_service_key, "postOffiId": 100, "nowPage": 1, "pageCount": 50})
            pg = parse_post_xml(r.text)
            print(f"   HTTP {r.status_code} · totalCount={pg.total_count} totalPage={pg.total_page} "
                  f"items={len(pg.items)} · error={pg.error} → {_save('post_area_100_p1.xml', r.text, secrets)}")
            if pg.items:
                print(f"   필드: {sorted(pg.items[0].keys())}")
            ok &= r.status_code == 200 and not pg.error

        print("③ SGIS 인증 → 인구 → 경계 (서울 11)")
        if not (s.sgis_consumer_key and s.sgis_consumer_secret):
            print("   ✗ SGIS 키 없음"); return False
        r = h.get(f"{s.sgis_base_url}/auth/authentication.json",
                  params={"consumer_key": s.sgis_consumer_key, "consumer_secret": s.sgis_consumer_secret})
        auth = r.json()
        token = (auth.get("result") or {}).get("accessToken")
        print(f"   auth errCd={auth.get('errCd')} token={'OK' if token else '없음'} "
              f"timeout={(auth.get('result') or {}).get('accessTimeout')}")
        if not token:
            return False
        try:
            parse_timeout((auth.get("result") or {}).get("accessTimeout"))
        except (TypeError, ValueError):
            print("   ⚠ accessTimeout 형식이 예상과 다름")
        secrets.append(token)
        r = h.get(f"{s.sgis_base_url}/stats/population.json",
                  params={"accessToken": token, "year": s.stat_year, "adm_cd": "11", "low_search": 1})
        pop = r.json()
        print(f"   population errCd={pop.get('errCd')} rows={len(pop.get('result') or [])} → "
              f"{_save('sgis_pop_11.json', r.text, secrets)}")
        if pop.get("result"):
            print(f"   필드: {sorted(pop['result'][0].keys())}")
        r = h.get(f"{s.sgis_base_url}/boundary/hadmarea.geojson",
                  params={"accessToken": token, "year": s.stat_year, "adm_cd": "11", "low_search": 1})
        bnd = r.json()
        feats = bnd.get("features") or []
        srid = detect_srid(feats[0]["geometry"]) if feats else None
        print(f"   boundary errCd={bnd.get('errCd')} features={len(feats)} 좌표계 판정=EPSG:{srid} → "
              f"{_save('sgis_bnd_11.geojson', json.dumps(bnd, ensure_ascii=False), secrets)}")
        ok &= bool(pop.get("result")) and bool(feats)
        print("④ (선택) KOSIS 주민등록인구 — 통계표 메타")
        if not s.kosis_api_key:
            print("   – KOSIS_API_KEY 없음 (선택 기능, 건너뜀)")
        else:
            r = h.get(f"{s.kosis_base_url}/statisticsData.do",
                      params={"method": "getMeta", "type": "TBL", "apiKey": s.kosis_api_key, "orgId": s.kosis_org_id,
                              "tblId": s.kosis_tbl_id, "format": "json", "jsonVD": "Y"})
            body = r.json() if r.headers.get("content-type", "").startswith(("application/json", "text")) else {}
            name = body[0].get("TBL_NM") if isinstance(body, list) and body else None
            print(f"   HTTP {r.status_code} · 통계표={name or body}")
            ok &= bool(name)
        print("⑤ (선택) 공공데이터포털 — 기상청 단기예보·에어코리아 미세먼지 예보")
        if not s.data_go_kr_key:
            print("   – DATA_GO_KR_KEY 없음 (선택 기능, 건너뜀)")
        else:
            from datetime import timedelta

            from atlas.collector.weather.client import _error_of, now_kst
            from atlas.collector.weather.kma import latest_base

            secrets.append(s.data_go_kr_key)
            base, now = latest_base(now_kst()), now_kst()
            for label, url, params, fname in (
                ("기상청 단기예보(서울 60,127)", f"{s.kma_base_url}/getVilageFcst",
                 {"pageNo": 1, "numOfRows": 20, "dataType": "JSON", "base_date": f"{base:%Y%m%d}",
                  "base_time": f"{base:%H%M}", "nx": 60, "ny": 127}, "kma_vilage_60_127.json"),
                ("에어코리아 미세먼지 예보", f"{s.airkorea_base_url}/getMinuDustFrcstDspth",
                 {"returnType": "json", "numOfRows": 10, "pageNo": 1, "InformCode": "PM10",
                  "searchDate": f"{(now - timedelta(hours=6)).date()}"}, "air_frcst_pm10.json")):
                r = h.get(url, params={**params, "serviceKey": s.data_go_kr_key})
                code, msg = _error_of(r.status_code, r.text)
                print(f"   {label}: HTTP {r.status_code} · resultCode={code} {msg} → {_save(fname, r.text, secrets)}")
                if code in ("30", "20") or "SERVICE_KEY" in (msg or ""):
                    print("     ↳ 키가 이 API 에 아직 등록되지 않았습니다. 공공데이터포털에서 활용신청(승인 후 반영까지 최대 1시간)을 확인하세요.")
                ok &= code in ("00", "03")
    print("\n결과:", "모두 정상 ✓" if ok else "실패 항목이 있습니다 ✗")
    return ok

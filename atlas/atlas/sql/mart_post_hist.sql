-- stg.post_facility(:run) → mart.post_facility_hist  SCD Type 2 병합 (FR-106)
--   · 같은 row_hash 면 아무것도 하지 않음 (재수집 멱등)
--   · row_hash 가 바뀐 시설: 현재 이력 닫고 새 이력 추가
--   · 이번 run 에서 '성공한' 지역코드(:done_codes)에 속했는데 사라진 시설: 이력 닫기
--     (실패한 지역코드의 시설은 건드리지 않음 → 일시 오류로 문 닫은 것처럼 처리되는 일 방지)
--   · 좌표가 없거나 국내 범위 밖이면 mart 에 넣지 않음 (DQ ERROR 로 이미 기록)
--   · 판정 열(fin_available·is_center)은 원천이 아니라 규칙(RULE_VERSION)에서 나온 값 — row_hash 가 같아도 이번 판정과 다르면
--     바뀐 시설처럼 이력을 닫고 새로 엶. 예전에는 규칙을 바꿔도 원천이 같은 시설은 옛 판정이 남았음. 제자리 갱신은 하지 않음 —
--     지난 계산 실행이 as_of 로 다시 만드는 시설 집합까지 바뀌어 같은 실행의 What-if·배치 제안·도보 값이 달라지기 때문(NFR-03)

UPDATE mart.post_facility_hist h
   SET valid_to = now(), is_current = false
 WHERE h.is_current
   AND (
        EXISTS (SELECT 1 FROM stg.post_facility s
                 WHERE s.collect_run_id = :run AND s.post_id = h.post_id
                   AND (s.row_hash <> h.row_hash OR s.fin_available IS DISTINCT FROM h.fin_available
                        OR s.is_center IS DISTINCT FROM h.is_center)
                   AND s.lat BETWEEN 33 AND 39 AND s.lon BETWEEN 124 AND 132)
     OR (h.area_code = ANY(CAST(:done_codes AS text[]))
         AND NOT EXISTS (SELECT 1 FROM stg.post_facility s
                          WHERE s.collect_run_id = :run AND s.post_id = h.post_id))
   );

INSERT INTO mart.post_facility_hist
       (post_id, post_div, name, addr, tel, geom, geom_5179, post_time, finance_time, fin_available,
        lunch_yn, lunch_time, post365_yn, area_code, is_center, mod_dt, row_hash, collect_run_id,
        valid_from, valid_to, is_current, coord_source)
SELECT s.post_id, s.post_div, s.name, s.addr, s.tel,
       ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326),
       ST_Transform(ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326), 5179),
       s.post_time, s.finance_time, s.fin_available, s.lunch_yn, s.lunch_time, s.post365_yn,
       s.area_code, s.is_center, s.mod_dt, s.row_hash, s.collect_run_id,
       now(), NULL, true, s.coord_source
  FROM stg.post_facility s
 WHERE s.collect_run_id = :run
   AND s.lat BETWEEN 33 AND 39 AND s.lon BETWEEN 124 AND 132
   AND NOT EXISTS (SELECT 1 FROM mart.post_facility_hist h WHERE h.is_current AND h.post_id = s.post_id);

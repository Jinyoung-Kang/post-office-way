# ADR-005 What-if 는 area_nearest 상위 3개 기반 부분 재계산

- 상태: 채택
- 결정: 계산 시 지역별 최근접 금융 가능 시설 상위 3개를 저장한다. 시설 제외 시 rank 1 이 제외된 지역만 다시 계산하고,
  rank 2·3 중 남은 가장 가까운 시설로 대체, 셋 다 제외되면 KNN 재탐색(최대 5개 제외이므로 드묾).
- 검증: 무작위 20회 부분 재계산 = 전체 재계산 (`tests/sql/test_whatif.py`). 동률은 hist_id 로 순서 고정.
- 결과는 `whatif_scenario`(정렬된 제외 목록이 멱등 키) · `whatif_result` 에 저장, Redis TTL 1h.

-- 생활 거점 지표의 '은행 지점' 문구를 계산에 맞춤 — 09_life 는 은행·금고 지점 전체(07_bank, 새마을금고·저축은행 포함 대면 창구)로
-- 계산하는데 정의는 '은행 지점'이라, 은행만 세는 은행 지점 영향평가(BANK-IMPACT-1, V18)와 뜻이 갈렸음.
-- 계산은 그대로(금고도 대면 금융 창구), 문구만 바꿈 — 2026-10-15 2차 리뷰 Q1 사용자 결정. 지표 값·순위는 바뀌지 않음.
UPDATE mart.metric_def
   SET formula = '2km 안 금융 우체국은 있지만 은행·금고 지점(새마을금고·저축은행 포함)·약국·의원이 모두 없는 집계구 인구 합.'
 WHERE metric_code = 'POST_SOLE_HUB_PPLTN';
UPDATE mart.metric_def
   SET formula = '2km 안에 금융 우체국·은행·금고 지점(새마을금고·저축은행 포함)·약국·의원이 하나도 없는 집계구 인구 합.'
 WHERE metric_code = 'LIFE_DESERT_PPLTN';

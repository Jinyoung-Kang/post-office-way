-- V20 — 브라우저가 보낸 CSP 위반 보고도 오류 로그(ops.app_error)에 남김.
--   2026-10 카카오 지도 SDK 가 CDN 호스트를 바꿔(t1.daumcdn.net → t1.kakaocdn.net) CSP 에 막혔는데, 서버 쪽에는 아무 기록이
--   없어 화면을 열어 봐야 알 수 있었음 → 이제 '보안 정책' 출처로 데이터·운영 오류 로그에 바로 보임.
ALTER TABLE ops.app_error DROP CONSTRAINT app_error_source_check;
ALTER TABLE ops.app_error ADD CONSTRAINT app_error_source_check CHECK (source IN ('api', 'worker', 'csp'));

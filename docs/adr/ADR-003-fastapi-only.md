# ADR-003 백엔드는 FastAPI 단일

- 상태: 채택
- 맥락: 기존 매크로 대시보드는 Python·Java·TypeScript 3언어였다. 이 프로젝트의 핵심은 공간 SQL 과 데이터 품질이다.
- 결정: API·수집·계산을 Python 하나로. ORM 모델 없이 SQLAlchemy `text()` + 파일로 관리하는 SQL.

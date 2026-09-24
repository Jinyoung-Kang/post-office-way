"""설정 — 환경변수 / 저장소 루트 .env 에서 읽습니다. 키는 서버 코드에서만 사용."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://atlas:atlas@localhost:5442/atlas"
    redis_url: str = "redis://localhost:6389/0"

    post_service_key: str = ""
    sgis_consumer_key: str = ""
    sgis_consumer_secret: str = ""
    kakao_rest_api_key: str = ""
    kosis_api_key: str = ""
    data_go_kr_key: str = ""                  # 공공데이터포털 일반 인증키 — 기상청 단기예보·에어코리아 (방문 여건)
    admin_token: str = ""

    stat_year: int = 2024
    sgis_sido: str = "all"
    sgis_levels: str = "2,3"

    post_base_url: str = "https://www.koreapost.go.kr/koreapost/openapi"
    sgis_base_url: str = "https://sgisapi.mods.go.kr/OpenAPI3"
    kosis_base_url: str = "https://kosis.kr/openapi"
    kosis_org_id: str = "101"                 # 행정안전부
    kosis_tbl_id: str = "DT_1B04005N"         # 행정구역(읍면동)별/5세별 주민등록인구
    kosis_period: str = ""                    # 비우면 {STAT_YEAR}12 (경계 연도와 맞춤), 'latest' 면 최신월
    kakao_local_base: str = "https://dapi.kakao.com"
    kakao_navi_base: str = "https://apis-navi.kakaomobility.com"
    kakao_call_delay_ms: int = 60             # 카카오 호출 간 지연
    road_max_calls: int = 8000                # 도로 거리 수집 1회 호출 예산 (쿼터 보호, 다음 실행에 이어서)
    kma_base_url: str = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
    airkorea_base_url: str = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc"
    datago_call_delay_ms: int = 100           # 공공데이터포털(기상청·에어코리아) 호출 간 지연
    post_call_delay_ms: int = 300
    http_timeout_s: float = 10.0
    http_retries: int = 3

    migrations_dir: str = str(_REPO_ROOT / "db" / "migrations")
    seed_dir: str = str(_REPO_ROOT / "seed")

    @field_validator("post_service_key", "sgis_consumer_key", "sgis_consumer_secret",
                     "kakao_rest_api_key", "kosis_api_key", "data_go_kr_key", "admin_token", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            # 값이 비어 있을 때 docker compose 가 줄 끝 주석('# …')을 값으로 넘기는 경우 방지
            return "" if v.startswith("#") else v
        return v

    @property
    def kosis_period_resolved(self) -> str:
        p = self.kosis_period.strip().lower()
        return "latest" if p == "latest" else (p or f"{self.stat_year}12")

    @property
    def levels(self) -> list[int]:
        return sorted({int(x) for x in self.sgis_levels.split(",") if x.strip()})


@lru_cache
def get_settings() -> Settings:
    import os

    s = Settings()
    # Docker 이미지에서는 경로를 환경변수로 덮어씁니다.
    if os.environ.get("ATLAS_MIGRATIONS_DIR"):
        s.migrations_dir = os.environ["ATLAS_MIGRATIONS_DIR"]
    if os.environ.get("ATLAS_SEED_DIR"):
        s.seed_dir = os.environ["ATLAS_SEED_DIR"]
    return s

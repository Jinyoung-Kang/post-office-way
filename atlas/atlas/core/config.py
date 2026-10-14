"""설정 — 환경변수에서 읽습니다(컨테이너는 compose 가 넘긴 변수만, 호스트 개발은 저장소 루트 .env 도). 키는 서버 코드에서만 사용."""
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
    db_statement_timeout_ms: int = 0          # 0 = 제한 없음. 워커는 compose 에서 30분 (API 역할은 DB 역할 설정 15초)

    post_service_key: str = ""
    sgis_consumer_key: str = ""
    sgis_consumer_secret: str = ""
    kakao_rest_api_key: str = ""
    kosis_api_key: str = ""
    data_go_kr_key: str = ""                  # 공공데이터포털 일반 인증키 — 기상청 단기예보·에어코리아 (방문 여건)
    admin_token: str = ""
    api_db_password: str = ""                 # 최소 권한 역할 atlas_api 비밀번호 (make env 가 생성)

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
    pharmacy_url: str = "https://apis.data.go.kr/B552657/ErmctInsttInfoInqireService"
    hospital_url: str = "https://apis.data.go.kr/B552657/HsptlAsembySearchService"
    holiday_url: str = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService"
    datago_call_delay_ms: int = 100
    datago_concurrency: int = 4               # 공공데이터포털 동시 호출 수 (기상청 격자). 서비스 한도 30 tps 안
    # ② 도보 — OSM 한국 도로망(Geofabrik, ODbL). 내려받은 파일·그래프는 osm_dir(도커 볼륨)에 둠
    osm_pbf_url: str = "https://download.geofabrik.de/asia/south-korea-latest.osm.pbf"
    osm_dir: str = "/data/osm"
    walk_speed_mps: float = 0.8               # 고령자 보행 속도 — 서울시 보행약자 신호시간(1m 당 1.25초) 기준
    walk_limit_m: float = 3000.0              # 이보다 멀면 '걸어서 갈 수 없음'으로 보고 탐색을 멈춤
    walk_snap_max_m: float = 1000.0           # 집계구 대표점·시설이 도로에서 이보다 멀면 도보 계산에서 뺌
    walk_minutes: int = 30                    # 'N분 안' 지표의 기준
    migrate_on_start: bool = False            # API 기동 때 마이그레이션 (호스트 개발용. compose 는 migrate 서비스가 담당)
    rate_limit_enabled: bool = True
    # 이 대역에서 온 요청만 X-Forwarded-For 를 믿음 (web 컨테이너가 있는 도커 사설망 + 로컬)
    trusted_proxies: str = "127.0.0.1/32,::1/128,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"
    atlas_schedule: str = "weather,holidays,care"   # 워커 스케줄 그룹 (weather·holidays·care·post, all, 빈 값=끔)           # 공공데이터포털(기상청·에어코리아) 호출 간 지연
    post_call_delay_ms: int = 300
    http_timeout_s: float = 10.0
    http_retries: int = 3

    migrations_dir: str = str(_REPO_ROOT / "db" / "migrations")
    seed_dir: str = str(_REPO_ROOT / "seed")

    @field_validator("post_service_key", "sgis_consumer_key", "sgis_consumer_secret",
                     "kakao_rest_api_key", "kosis_api_key", "data_go_kr_key", "admin_token", "api_db_password",
                     mode="before")
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

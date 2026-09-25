import { useEffect, useState } from "react";
import Layout, { Card, ErrorBox, Hero } from "@/components/Layout";
import { api, type MetricDef } from "@/lib/api";
import { groupMetrics } from "@/lib/format";

type Resp = { items: MetricDef[]; finRule: { code: string; version: string; name: string; conditions: string[] }; disclaimer: string };

// 지표 정의 — metric_def 내용을 그대로 표시 (FR-504)
export default function MetricsAbout() {
  const [d, setD] = useState<Resp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Resp>("/metrics").then(setD).catch((e) => setErr(e.message)); }, []);

  return (
    <Layout title="지표 정의">
      <Hero title="지표 정의." sub="모든 숫자가 어떻게 계산되는지, 어디까지 믿을 수 있는지 적어 둡니다." />
      <div className="mx-auto max-w-page space-y-5 px-4 pb-20">
        <div className="card flex gap-3 p-5 text-[14px]">
          <span className="badge badge-warn h-fit">공식 통계 아님</span>
          <p className="text-ink-2">{d?.disclaimer ?? "이 서비스의 지표는 분석용으로 정의한 값입니다."}</p>
        </div>
        {err && <ErrorBox error={err} />}
        {d && (
          <>
            <nav className="flex flex-wrap gap-2 text-[13px]" aria-label="지표 묶음">
              {groupMetrics(d.items).map((g) => <a key={g.label} href={`#g-${g.label}`} className="badge badge-info no-underline">{g.label} {g.items.length}</a>)}
              <a href="#rules" className="badge badge-info no-underline">판정 규칙</a>
            </nav>
            {groupMetrics(d.items).map((g) => (
            <section key={g.label} id={`g-${g.label}`} className="scroll-mt-16 space-y-3">
            <h2 className="px-1 text-[21px] font-semibold tracking-tight">{g.label}</h2>
            <div className="grid gap-4 md:grid-cols-2">
              {g.items.map((m) => (
                <section key={m.code} className="card p-6">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="text-[19px] font-semibold tracking-tight">{m.name}</h3>
                    <span className="badge badge-info shrink-0">{m.unit}</span>
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-ink-3">{m.code}</p>
                  <p className="mt-3 text-[14px] leading-relaxed">{m.formula}</p>
                  {m.limitation && <p className="mt-2 text-[13px] leading-relaxed text-ink-2">한계 — {m.limitation}</p>}
                  <p className="mt-3 flex flex-wrap gap-1.5 text-[12px]">
                    <span className={`badge ${m.higherIsWorse ? "badge-warn" : "badge-good"}`}>{m.higherIsWorse ? "클수록 취약" : "클수록 양호"}</span>
                    {!m.available && <span className="badge badge-info">현재 계산값 없음</span>}
                  </p>
                </section>
              ))}
            </div>
            </section>
            ))}
            <div id="rules" className="scroll-mt-16" />
            <Card title={`${d.finRule.code} · ${d.finRule.name}`} right={<code className="text-[12px] text-ink-3">{d.finRule.version}</code>}>
              <ol className="list-decimal space-y-1.5 pl-5 text-[14px]">
                {d.finRule.conditions.map((c) => <li key={c}>{c}</li>)}
              </ol>
              <p className="mt-3 text-[13px] text-ink-2">해석이 바뀌면 규칙 버전을 올리고 새 calc_run 으로 다시 계산합니다(이전 결과 보존).</p>
            </Card>
            <div className="grid gap-5 md:grid-cols-2">
              <Card title="VISIT-1 · 방문 여건" right={<a href="/today" className="link text-[13px]">화면 ›</a>}>
                <p className="text-[14px] text-ink-2">시군구 대표점의 기상청 5km 격자 · 09~18시 시간 예보 + 에어코리아 권역 예보. 가장 나쁜 항목이 그날 등급입니다.</p>
                <ul className="mt-3 space-y-1 text-[14px]">
                  <li><b>비</b> 운영 시간에 비 → 주의 · 합계 30mm+ 또는 시간당 10mm+ → 나쁨</li>
                  <li><b>눈</b> 눈·진눈깨비 → 주의 · 신적설 1cm+ → 나쁨</li>
                  <li><b>더위·추위</b> 31℃+ / -5℃- → 주의 · 33℃+ / -10℃- → 나쁨</li>
                  <li><b>바람</b> 9m/s+ → 주의 · 14m/s+ → 나쁨</li>
                  <li><b>미세먼지</b> 예보 나쁨 → 주의 · 매우나쁨 → 나쁨</li>
                </ul>
              </Card>
              <Card title="생활 거점 · 영업일" right={<a href="/hubs" className="link text-[13px]">화면 ›</a>}>
                <ul className="space-y-2 text-[14px] text-ink-2">
                  <li><b className="text-ink">마지막 생활 거점</b> — 집계구에서 2km 안 금융 우체국은 있지만 은행 지점·약국·의원(종합병원·병원·의원·보건소)은 없음.</li>
                  <li><b className="text-ink">대체 불가</b> — 그 우체국이 가장 가깝고 두 번째 우체국도 2km 밖이라, 닫히면 생활 거점을 모두 잃음.</li>
                  <li><b className="text-ink">창구 휴무일</b> — 토·일 + 한국천문연구원 특일 정보의 공공기관 휴일(대체·임시공휴일 포함). 3일 이상 이어지면 연휴.</li>
                  <li><b className="text-ink">공휴일 의료 공백</b> — 국립중앙의료원 자료에 공휴일 진료시간이 등록된 약국·의원이 2km 안에 없음.</li>
                </ul>
              </Card>
            </div>
            <Card title="데이터와 한계">
              <ul className="space-y-2 text-[14px] leading-relaxed text-ink-2">
                <li><b className="text-ink">시설</b> — 우정사업본부 「우체국 찾기」 OpenAPI. 수집 시점 현재이며 변경은 이력(SCD2)으로 보관합니다.</li>
                <li><b className="text-ink">인구·경계</b> — SGIS 총조사 주요지표·행정구역 경계(통계 연도 기준, 외국인 포함 총조사 인구).</li>
                <li><b className="text-ink">고령인구</b> — KOSIS 주민등록인구(행정안전부, 5세별). 경계 연도와 맞춘 기준월(기본 {`{통계 연도}`}년 12월). 행정구역 이름으로 SGIS 에 맞춥니다.</li>
                <li><b className="text-ink">거리</b> — EPSG:5179 직선거리. 지역 대표점(ST_PointOnSurface) 1개가 지역 전체를 대표합니다.</li>
                <li><b className="text-ink">집계구</b> — SGIS 통계 최소 단위(평균 약 500명) 인구·경계로 거주 분포를 반영한 거리(인구 가중 거리, 2km 밖 인구).</li>
                <li><b className="text-ink">도로 거리</b> — 카카오모빌리티 자동차 경로. 직선 상위 2개 우체국 후보 중 짧은 쪽(도보·대중교통 아님).</li>
                <li><b className="text-ink">은행·금고 지점</b> — 카카오 로컬 은행 범주(BK9)에서 ATM·우체국을 뺀 대면 창구. 폐점 반영이 늦을 수 있습니다.</li>
                <li><b className="text-ink">좌표 검증</b> — 우체국·365코너·무인창구 좌표를 주소 검색 좌표와 비교해 1km 넘게 다르면 품질 경고.</li>
                <li><b className="text-ink">약국·의원</b> — 국립중앙의료원 전국 약국·병의원 FullData(좌표·요일별 진료시간). 치과·한의원·요양병원 제외. 매주 갱신.</li>
                <li><b className="text-ink">날씨·대기</b> — 기상청 단기예보(하루 8회 발표), 에어코리아 대기질 예보(하루 4회). 기상특보가 아닌 참고 정보입니다.</li>
                <li><b className="text-ink">행정구역 판정</b> — 우편 지역코드가 아니라 좌표 공간 조인(우편 지역코드는 행정구역과 1:1 이 아님).</li>
                <li>빈 값은 ‘—’, 추정·가정이 들어간 값은 ⚠ 로 표시합니다.</li>
              </ul>
            </Card>
          </>
        )}
      </div>
    </Layout>
  );
}

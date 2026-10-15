import { describe, expect, it } from "vitest";
import { esc, placeTip, TIP_GAP, tipHtml } from "./mapTip";

describe("지도 말풍선", () => {
  it("제목·글자·굵은 조각을 모두 이스케이프", () => {
    const html = tipHtml("<img src=x onerror=alert(1)>", [["지표 ", { b: "<b>1</b>" }, " · 사유<script>"], ["인구 10명"]]);
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).toContain("<b>&lt;b&gt;1&lt;/b&gt;</b>");
    expect(html).toContain("<br/>인구 10명");
  });

  it("빈 줄은 건너뛰고, 고정된 말풍선에는 닫기 표시", () => {
    expect(tipHtml("의성군", [])).toBe('<div class="map-tip"><b>의성군</b></div>');
    expect(tipHtml("의성군", [[], ["예보 없음"]], true)).toContain('map-tip-x');
    expect(tipHtml("의성군", [[], ["예보 없음"]])).toBe('<div class="map-tip"><b>의성군</b><br/>예보 없음</div>');
  });

  it("esc", () => {
    expect(esc(`a&b"c'<>`)).toBe("a&amp;b&quot;c&#39;&lt;&gt;");
  });
});

describe("지도 말풍선 위치", () => {
  const map = { w: 1024, h: 720 };
  const tip = { w: 198, h: 60 };
  const pad: [number, number, number, number] = [24, 24, 24, 24];

  it("기본은 가리킨 점 위 가운데", () => {
    expect(placeTip(500, 300, tip, map, pad)).toEqual({ left: 500 - 99, top: 300 - 60 - TIP_GAP.above });
  });

  it("오른쪽 가장자리에서는 지도 안으로 — 거창군 말풍선이 1072px 까지 그려져 끝 글자가 잘렸던 경우", () => {
    // 지도 1024px, 가리킨 점 x 973 → 가운데 기준이면 874~1072
    const { left } = placeTip(973, 331, tip, map, pad);
    expect(left + tip.w).toBeLessThanOrEqual(map.w - pad[1]);
  });

  it("왼쪽 떠 있는 패널(340px)이 가리지 않게", () => {
    expect(placeTip(360, 300, tip, map, [24, 24, 24, 340]).left).toBe(340);
  });

  it("위 공간이 모자라면 점 아래로", () => {
    const { top } = placeTip(500, 60, tip, map, pad);
    expect(top).toBe(60 + TIP_GAP.below);
  });

  it("위아래 모두 모자라면(낮은 지도) 위 여백에 붙임", () => {
    expect(placeTip(500, 70, tip, { w: 1024, h: 140 }, pad).top).toBe(24);
  });

  it("말풍선이 지도보다 넓으면 왼쪽 여백부터 — 앞부분이 보이게", () => {
    expect(placeTip(150, 300, { w: 400, h: 60 }, { w: 375, h: 600 }, [16, 16, 16, 16]).left).toBe(16);
  });
});

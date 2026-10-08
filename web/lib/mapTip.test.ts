import { describe, expect, it } from "vitest";
import { esc, tipHtml } from "./mapTip";

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

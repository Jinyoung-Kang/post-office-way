import { useMemo } from "react";
import type { Geometry } from "@/lib/api";

// 지도 SDK 없이 그리는 작은 단계구분도 (SVG) — 보고서 인쇄·PDF 에 그대로 나오고, 외부 타일 요청이 없음.
// 위경도를 위도 중심의 등장방형으로 펼쳐 viewBox 에 맞춤 (시군구 한 곳 크기에서는 왜곡이 1% 안팎)
export type MiniFeature = { id: string; name: string; geometry: Geometry | null; fill: string; title: string };

const W = 520;

export default function MiniMap({ features, label, height = 360, onPick, selected }: {
  features: MiniFeature[]; label: string; height?: number; onPick?: (id: string) => void; selected?: string | null;
}) {
  const shapes = useMemo(() => {
    const polys = features.map((f) => {
      const g = f.geometry;
      if (!g) return [] as number[][][];
      return (g.type === "Polygon" ? [g.coordinates as number[][][]] : (g.coordinates as number[][][][])).flat();
    });
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    polys.flat(2).forEach(([x, y]) => { minx = Math.min(minx, x); maxx = Math.max(maxx, x); miny = Math.min(miny, y); maxy = Math.max(maxy, y); });
    if (!Number.isFinite(minx)) return { paths: [] as string[], h: height };
    const k = Math.cos(((miny + maxy) / 2) * (Math.PI / 180));
    const sx = (maxx - minx) * k, sy = maxy - miny;
    const s = Math.min((W - 8) / sx, (height - 8) / sy);
    const ox = (W - sx * s) / 2, oy = (height - sy * s) / 2;
    const px = (x: number) => (ox + (x - minx) * k * s).toFixed(1);
    const py = (y: number) => (oy + (maxy - y) * s).toFixed(1);
    const paths = polys.map((rings) => rings.map((r) => "M" + r.map(([x, y]) => `${px(x)},${py(y)}`).join("L") + "Z").join(""));
    return { paths, h: height };
  }, [features, height]);

  return (
    <svg viewBox={`0 0 ${W} ${shapes.h}`} className="h-auto w-full" role="img" aria-label={label}>
      {/* 고른 지역은 맨 위에 그려 테두리가 이웃에 가리지 않게 */}
      {features.map((f, i) => ({ f, i })).sort((a, b) => Number(a.f.id === selected) - Number(b.f.id === selected)).map(({ f, i }) => (
        <path key={f.id} d={shapes.paths[i]} fill={f.fill} fillRule="evenodd"
          stroke={selected === f.id ? "#1d1d1f" : "#ffffff"} strokeWidth={selected === f.id ? 2 : 0.8}
          className={onPick ? "cursor-pointer" : undefined} onClick={onPick ? () => onPick(f.id) : undefined}>
          <title>{f.title}</title>
        </path>
      ))}
    </svg>
  );
}

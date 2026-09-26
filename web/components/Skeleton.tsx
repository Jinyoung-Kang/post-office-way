// 불러오는 동안 자리 표시 — 레이아웃이 튀지 않게 실제 카드와 같은 크기로
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

// 실제 카드와 같은 줄 수로 자리를 잡아 두어 데이터가 와도 아래 내용이 밀리지 않게 (CLS)
export function StatSkeletons({ n = 4, rows = 1 }: { n?: number; rows?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4" role="status" aria-label="불러오는 중">
      {Array.from({ length: n * rows }, (_, i) => (
        <div key={i} className="card space-y-3 p-5"><Skeleton className="h-3 w-24" /><Skeleton className="h-7 w-32" /><Skeleton className="h-3 w-20" /></div>
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 px-6 pb-6" role="status" aria-label="불러오는 중">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-9 w-full" />)}
    </div>
  );
}

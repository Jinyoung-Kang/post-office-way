// 화면이 보일 때만 주기적으로 다시 받기 — 받는 중에 다시 시작해도(탭 복귀) 타이머 사슬이 하나만 남게.
// load 는 계속 받을지(예: 작업이 대기·실행 중) 돌려줌
export type Poller = { kick: () => void; stop: () => void };

export function poll(load: () => Promise<boolean>, intervalMs: number, visible: () => boolean): Poller {
  let gen = 0, stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const run = async () => {
    const my = ++gen;
    if (timer) { clearTimeout(timer); timer = null; }
    const again = await load();
    if (stopped || my !== gen) return;          // 더 새로 시작한 받기가 있으면 이 사슬은 여기서 끝
    if (again && visible()) timer = setTimeout(run, intervalMs);
  };
  void run();
  return {
    kick: () => { if (!stopped) void run(); },
    stop: () => { stopped = true; gen++; if (timer) clearTimeout(timer); },
  };
}

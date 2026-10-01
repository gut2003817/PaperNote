import { useEffect, useState } from "react";
import { api } from "./api";
import type { Engine, EngineHealth } from "./types";

export function HealthLight() {
  const [health, setHealth] = useState<Record<Engine, EngineHealth> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch((e: Error) => setError(e.message));
  }, []);
  if (error) return <span className="health"><span className="health-dot bad" />後端未啟動：{error}</span>;
  if (!health) return <span className="health">檢查 AI 狀態中…</span>;
  return (
    <span className="health">
      {(Object.keys(health) as Engine[]).map((engine) => {
        const h = health[engine];
        return (
          <span key={engine} title={h.ok ? h.detail : `${h.detail}；修復：${h.fix ?? ""}`}>
            <span className={`health-dot ${h.ok ? "ok" : "bad"}`} />
            {engine === "claude" ? "Claude" : "Codex"}
            {!h.ok && `（${h.detail}）`}
          </span>
        );
      })}
    </span>
  );
}

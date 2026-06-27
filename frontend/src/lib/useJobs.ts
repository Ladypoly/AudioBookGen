import { useEffect, useRef, useState } from "react";
import { wsUrl, type JobView } from "./api";

// Subscribe to the /ws/jobs stream and keep a live map of jobs for the queue
// strip. Reconnects automatically if the socket drops.
export function useJobs(): JobView[] {
  const [jobs, setJobs] = useState<Record<string, JobView>>({});
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      const ws = new WebSocket(wsUrl("/ws/jobs"));
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "job") {
            const job: JobView = msg.job;
            setJobs((prev) => ({ ...prev, [job.id]: job }));
          }
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 1500);
      };
      ws.onerror = () => ws.close();
    };
    connect();

    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  // Newest first; finished jobs sink below active ones.
  return Object.values(jobs).sort((a, b) => {
    const rank = (s: JobView["state"]) => (s === "running" ? 0 : s === "pending" ? 1 : 2);
    return rank(a.state) - rank(b.state);
  });
}

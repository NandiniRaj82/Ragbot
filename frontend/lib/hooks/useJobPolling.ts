import { useState, useEffect, useRef, useCallback } from "react";
import { getJobStatus, JobStatus } from "@/lib/api";

interface UseJobPollingOptions {
  jobId: string | null;
  interval?: number;       // ms between polls (default: 1500)
  onComplete?: (result: JobStatus) => void;
  onError?: (error: string) => void;
}

export function useJobPolling({
  jobId,
  interval = 1500,
  onComplete,
  onError,
}: UseJobPollingOptions) {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);

  // Keep refs up to date without re-triggering effect
  useEffect(() => { onCompleteRef.current = onComplete; }, [onComplete]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setIsPolling(false);
  }, []);

  useEffect(() => {
    if (!jobId) {
      stopPolling();
      setStatus(null);
      return;
    }

    setIsPolling(true);

    const poll = async () => {
      try {
        const data = await getJobStatus(jobId);
        setStatus(data);

        if (data.stage === "completed") {
          stopPolling();
          onCompleteRef.current?.(data);
        } else if (data.stage === "failed") {
          stopPolling();
          onErrorRef.current?.(data.error || "Job failed");
        }
      } catch (err) {
        // Network error — don't stop polling, it might recover
        console.warn("[useJobPolling] poll error:", err);
      }
    };

    // Poll immediately, then on interval
    poll();
    intervalRef.current = setInterval(poll, interval);

    return stopPolling;
  }, [jobId, interval, stopPolling]);

  return { status, isPolling, stopPolling };
}

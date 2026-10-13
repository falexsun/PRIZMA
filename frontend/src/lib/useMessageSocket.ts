"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getAccessToken } from "@/lib/api";

function getDefaultWsUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  if (typeof window === "undefined") return "ws://localhost:8000";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.hostname}:8000`;
}

export function useMessageSocket(messageId: number) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;

    const ws = new WebSocket(`${getDefaultWsUrl()}/ws/messages/${messageId}?token=${token}`);

    ws.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ["message", messageId] });
      queryClient.invalidateQueries({ queryKey: ["messages"] });
    };

    return () => ws.close();
  }, [messageId, queryClient]);
}

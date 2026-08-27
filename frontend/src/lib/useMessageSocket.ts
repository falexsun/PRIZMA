"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getAccessToken } from "@/lib/api";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

export function useMessageSocket(messageId: number) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;

    const ws = new WebSocket(`${WS_URL}/ws/messages/${messageId}?token=${token}`);

    ws.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ["message", messageId] });
      queryClient.invalidateQueries({ queryKey: ["messages"] });
    };

    return () => ws.close();
  }, [messageId, queryClient]);
}

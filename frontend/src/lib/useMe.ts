import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

export function useMe() {
  return useQuery<Me>({
    queryKey: ["me"],
    queryFn: async () => (await api.get("/me")).data,
    staleTime: 5 * 60 * 1000,
  });
}

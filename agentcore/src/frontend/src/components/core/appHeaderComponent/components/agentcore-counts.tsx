import { useDarkStore } from "@/stores/darkStore";

export const AgentCoreCounts = () => {
  useDarkStore((state) => state.stars);

  return (
    <div className="flex items-center gap-3" />
  );
};

export default AgentCoreCounts;

import type { AgentType } from "@/types/agent";
import a2a from "./templates/a2a_agent.json";
import supervisor_agent from "./templates/supervisor_agent.json";
import graph_rag_agent from "./templates/graph_rag.json";
import collab_agent from "./templates/collab_agent.json";
import hierarchical from "./templates/hierarchical_agent.json";
import talktodata from "./templates/talk_to_data.json";
import hil from "./templates/human_in_loop.json";
import rag from "./templates/rag.json";
import azure_ai_search from "./templates/azure_aisearch.json";

export const PREBUILT_TEMPLATES: AgentType[] = [
  a2a,
  supervisor_agent,
  graph_rag_agent,
  collab_agent,
  hierarchical,
  talktodata,
  hil,
  rag,
  azure_ai_search
] as unknown as AgentType[];

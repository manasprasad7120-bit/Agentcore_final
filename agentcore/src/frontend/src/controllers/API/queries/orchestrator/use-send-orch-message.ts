export interface OrchChatRequest {
  session_id: string;
  agent_id?: string | null;
  deployment_id?: string | null;
  input_value: string;
  version_number?: number | null;
}

export interface OrchMessageResponse {
  id: string;
  timestamp: string;
  sender: string;
  sender_name: string;
  session_id: string;
  text: string;
  agent_id: string | null;
  deployment_id: string | null;
  model_id?: string | null;
  category?: string;
  files?: string[];
  properties?: {
    hitl?: boolean;
    thread_id?: string;
    actions?: string[];
    [key: string]: unknown;
  };
  content_blocks?: any[] | null;
}

export interface OrchChatResponse {
  session_id: string;
  agent_name: string;
  message: OrchMessageResponse;
  context_reset: boolean;
}

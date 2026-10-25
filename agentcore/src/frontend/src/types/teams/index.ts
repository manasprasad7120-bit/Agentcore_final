// Types for Microsoft Teams integration

export interface TeamsPublishRequest {
  agent_id: string;
  display_name?: string;
  short_description?: string;
  long_description?: string;
  bot_app_id?: string;
  bot_app_secret?: string;
}

export interface TeamsPublishResponse {
  teams_app_id: string;
  agent_id: string;
  status: TeamsPublishStatus;
  teams_external_id?: string;
  message: string;
}

export interface TeamsAppStatusResponse {
  agent_id: string;
  status: TeamsPublishStatus;
  teams_external_id?: string;
  display_name: string;
  published_at?: string;
  last_error?: string;
  has_own_bot?: boolean;
  bot_app_id?: string;
}

export type TeamsPublishStatus =
  | "DRAFT"
  | "UPLOADED"
  | "PUBLISHED"
  | "FAILED"
  | "UNPUBLISHED";

export interface TeamsHealthResponse {
  configured: boolean;
  bot_app_id: string;
  endpoint_base: string;
  adapter?: string;
  graph_api?: string;
}

export interface TeamsOAuthStatusResponse {
  connected: boolean;
  /**
   * The Microsoft Graph delegated scopes the connected user's token actually
   * has. May be an empty array for legacy tokens stored before the backend
   * started capturing this — treat empty as "permissive" (publishing
   * allowed) so existing connections keep working.
   */
  granted_scopes?: string[];
  /**
   * Convenience flag: true when the user is connected AND the stored token
   * includes ``AppCatalog.ReadWrite.All`` (or the granted_scopes list is
   * empty / legacy). False blocks Publish/Sync/Unpublish in the UI.
   */
  publishing_available?: boolean;
}

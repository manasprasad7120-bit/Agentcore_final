
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Send, Sparkles, ChevronDown, Plus, MessageSquare, User, Loader2, Trash2, Check, ImagePlus, X, Clock, Search, Image, Archive, ChevronRight, Globe, BookOpen, Headphones, Info, HelpCircle, Mic, AudioLines, FileUp, Paintbrush, Lightbulb, Upload, MoreVertical, Folder, ArrowLeft, File as FileIcon, FileText, Shield, CheckCircle2, SquarePen, Mail, Download, Copy, Pencil, Share2, LayoutGrid, Bot, ThumbsUp, ThumbsDown, AlertCircle } from "lucide-react";
import FeedbackPopup from "./FeedbackPopup";
import { FaChevronLeft, FaChevronRight } from "react-icons/fa";
import { useTranslation } from "react-i18next";
import {
  useGetOrchAgents,
  useGetOrchSessions,
  useGetOrchMessages,
  useDeleteOrchSession,
} from "@/controllers/API/queries/orchestrator";
import type {
  OrchAgentSummary,
  OrchSessionSummary,
  OrchMessageResponse,
} from "@/controllers/API/queries/orchestrator";
import { usePostUploadFileV2 } from "@/controllers/API/queries/file-management/use-post-upload-file";
import { useGetFilesV2 } from "@/controllers/API/queries/file-management/use-get-files";
import { api, performStreamingRequest } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { BASE_URL_API } from "@/constants/constants";
import { AuthContext } from "@/contexts/authContext";
import { MarkdownField } from "@/modals/IOModal/components/chatView/chatMessage/components/edit-message";
import { ContentBlockDisplay } from "@/components/core/chatComponents/ContentBlockDisplay";
import type { ContentBlock } from "@/types/chat";
import SharePointFilePicker from "./SharePointFilePicker";
// OutlookConnector removed — replaced by OutlookOrchConnector below.
import NotebookLMPanel from "./NotebookLMPanel";
import OutlookOrchConnector, {
  useOutlookOrchStatus,
  disconnectOutlookOrch,
} from "./OutlookOrchConnector";
import CanvasEditor from "./CanvasEditor";
import useAlertStore from "@/stores/alertStore";
import shareTeamsIcon from "@/assets/share_teams.png";
import outlookIcon from "@/assets/icons8-outlook-48.png";
import openaiLogo from "@/assets/openai_logo.svg";
import openaiLightLogo from "@/assets/openai_light.jfif";
import grokLogoLight from "@/assets/grok_logo_light.svg";
import { useDarkStore } from "@/stores/darkStore";
import geminiLogo from "@/assets/gemini_logo.svg";
import mistralLogo from "@/assets/mistral_logo.svg";
import claudeLogo from "@/assets/claude_logo.svg";
import azureLogo from "@/assets/azure_logo.svg";
import metaLogo from "@/assets/meta_logo.svg";
import cohereLogo from "@/assets/cohere_logo.svg";
import perplexityLogo from "@/assets/perplexity_logo.svg";
import nvidiaLogo from "@/assets/nvidia_logo.svg";
import huggingfaceLogo from "@/assets/huggingface_logo.svg";
import micoreLogo from "@/assets/mibuddy_logo.png";
import grokLogo from "@/assets/grok_logo.png";
import nanoBananaLogo from "@/assets/nano_banana_logo.png";
import dalleLogo from "@/assets/dalle_logo.svg";
import googleLogo from "@/assets/google_logo.svg";
import defaultLlmLogo from "@/assets/default_llm_logo.png";
import notebookLMLogo from "@/assets/notebooklm.svg";
import translatorLogo from "@/assets/ai translator.svg";
import imageLibraryLogo from "@/assets/image_library_logo.svg";
import do33Logo from "@/assets/DO33M.16.svg";
import miNewChatIcon from "@/assets/mibuddy_new_chat.svg?url";
import miSearchIcon from "@/assets/mibuddy_search.svg?url";
import miChatHistoryIcon from "@/assets/mibuddy_chat_history.svg?url";
import miArchiveIcon from "@/assets/mibuddy_archive.svg?url";
import miInformationIcon from "@/assets/mibuddy_information.svg?url";
import miHelpIcon from "@/assets/mibuddy_help.svg?url";
import talentaiIcon from "@/assets/mothersonLogo.svg";
import capexIcon from "@/assets/mothersonLogo.svg";
import KIPIcon from "@/assets/mothersonLogo.svg";
import yachioIcon from "@/assets/mothersonLogo.svg";
import MMNextIcon from "@/assets/mothersonLogo.svg";
import spendanalyticsIcon from "@/assets/mothersonLogo.svg";
import MessagesPage from "../SettingsPage/pages/messagesPage";




function SidebarMaskIcon({ src, className = "h-4 w-4 shrink-0" }: { src: string; className?: string }) {
  return (
    <img
      src={src}
      alt=""
      className={`${className} opacity-80 object-contain dark:invert`}
    />
  );
}

/* ------------------ REASONING BLOCK (CoT display) ------------------ */

function ReasoningBlock({
  reasoning,
  streaming,
}: {
  reasoning: string;
  streaming: boolean;
}) {
  const [open, setOpen] = useState(streaming);
  // Re-open while streaming; user can manually toggle after streaming stops
  useEffect(() => {
    if (streaming) setOpen(true);
  }, [streaming]);

  return (
    <div
      style={{
        marginBottom: "12px",
        width: "100%",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "8px",
          padding: "8px 16px",
          borderRadius: "9999px",
          border: "1px solid #e5e7eb",
          background: "#f9fafb",
          fontSize: "14px",
          fontWeight: 500,
          cursor: "pointer",
          color: "#374151",
        }}
      >
        <Lightbulb size={16} style={{ color: "#eab308" }} />
        <span>Reasoning</span>
        {streaming && <Loader2 size={12} className="animate-spin" style={{ color: "#6b7280" }} />}
        <ChevronDown
          size={14}
          style={{
            color: "#6b7280",
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 0.2s",
          }}
        />
      </button>
      {open && (
        <div
          style={{
            marginTop: "12px",
            padding: "16px",
            borderRadius: "8px",
            border: "1px solid #e5e7eb",
            background: "#f9fafb",
            fontSize: "13px",
            lineHeight: "1.6",
            color: "#4b5563",
            whiteSpace: "pre-wrap",
          }}
        >
          {reasoning}
        </div>
      )}
    </div>
  );
}

/* ------------------ TYPES ------------------ */

interface Agent {
  id: string;
  name: string;
  description: string;
  online: boolean;
  color: string;
  deploy_id: string;
  agent_id: string;
  version_number: number;
  version_label: string;
  environment: "uat" | "prod" | string;
}

interface Message {
  id: string;
  sender: "user" | "agent" | "system";
  agentName?: string;
  content: string;
  timestamp: string;
  category?: string;
  contentBlocks?: ContentBlock[];
  blocksState?: string;
  files?: string[];
  reasoningContent?: string;
  // HITL (Human-in-the-Loop) approval fields
  hitl?: boolean;
  hitlActions?: string[];
  hitlThreadId?: string;
  hitlIsDeployed?: boolean;
  // Canvas mode (MiBuddy-style) — if true, agent responses render in the
  // editable CanvasEditor card rather than as a plain MarkdownField.
  canvasEnabled?: boolean;
  // True when the backend saved this row as sender="agent" (an agent
  // deployment response). False when it came from direct model chat
  // (backend sender="model"). Used by UI affordances that should only
  // apply to one side — e.g. hiding the Teams/Outlook share menu on
  // agent replies.
  isAgentResponse?: boolean;
  // Thumbs up/down feedback (MiBuddy-parity). Present only on assistant
  // messages the user has rated; cleared when the user un-votes.
  feedbackRating?: "up" | "down" | null;
  feedbackReasons?: string[] | null;
  feedbackComment?: string | null;
  feedbackAt?: string | null;
}

interface FilePreview {
  id: string;
  file: File;
  path?: string;
  loading: boolean;
  error: boolean;
}

/* ------------------ COLOR PALETTE ------------------ */

const AGENT_COLORS = [
  "#10a37f", "#ab68ff", "#19c37d", "#ef4146", "#f5a623", "#0ea5e9",
  "#8b5cf6", "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16",
];

/* ------------------ HELPERS ------------------ */

function mapApiAgents(apiAgents: OrchAgentSummary[]): Agent[] {
  return apiAgents.map((a, i) => ({
    id: a.deploy_id,
    name: a.agent_name,
    description: a.agent_description || "",
    online: true,
    color: AGENT_COLORS[i % AGENT_COLORS.length],
    deploy_id: a.deploy_id,
    agent_id: a.agent_id,
    version_number: a.version_number,
    version_label: a.version_label,
    environment: a.environment,
  }));
}

function inferHitlFromText(text: string): boolean {
  if (!text) return false;
  const normalized = text.toLowerCase();
  return (
    normalized.includes("waiting for human review") &&
    normalized.includes("available actions")
  );
}

function extractHitlActions(text: string): string[] {
  if (!text) return [];
  const out = new Set<string>();

  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^[\s>*•-]*([A-Za-z][A-Za-z ]*[A-Za-z])\s*$/);
    if (!m?.[1]) continue;
    const action = m[1].trim();
    if (/approve|reject|edit|cancel/i.test(action)) {
      out.add(action);
    }
  }

  // Fallback for inline formats like "Available actions: • Approve • Reject"
  if (out.size === 0) {
    const inline = text.match(/approve|reject|edit|cancel/gi) ?? [];
    for (const action of inline) {
      out.add(action.charAt(0).toUpperCase() + action.slice(1).toLowerCase());
    }
  }

  return Array.from(out);
}

function mapApiMessages(apiMessages: OrchMessageResponse[]): Message[] {
  return apiMessages.map((m) => {
    const props = (m.properties || {}) as Record<string, any>;
    const isHitl = !!props.hitl || inferHitlFromText(m.text || "");
    const parsedActions = Array.isArray(props.actions)
      ? props.actions
      : extractHitlActions(m.text || "");

    // Restore content_blocks (reasoning / tool-use steps) from persisted data.
    // During streaming these arrive via SSE; on reload they come from the API.
    const toolBlocks = (m.content_blocks ?? []).filter((block: any) =>
      block.contents?.some((c: any) => c.type === "tool_use"),
    );

    // Backend stores assistant messages with sender="agent" (agent deployments)
    // or sender="model" (direct model chat). The UI treats both identically —
    // normalize to "agent" at this boundary so existing sender === "agent"
    // checks throughout this file don't each need to learn about "model".
    // `isAgentResponse` preserves the original distinction for the handful
    // of UI affordances that should only apply to one side (e.g. the
    // Teams/Outlook share menu, shown only for model replies).
    const isAgentResponse = m.sender === "agent";
    const normalizedSender = (m.sender === "model" ? "agent" : m.sender) as
      | "user"
      | "agent"
      | "system";

    return {
      id: m.id,
      sender: normalizedSender,
      agentName: normalizedSender === "agent" ? m.sender_name : undefined,
      isAgentResponse: normalizedSender === "agent" ? isAgentResponse : undefined,
      content: m.text,
      timestamp: m.timestamp
        ? new Date(m.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "",
      category: m.category || "message",
      files: m.files && m.files.length > 0 ? m.files : undefined,
      contentBlocks: toolBlocks.length > 0 ? toolBlocks : undefined,
      blocksState: toolBlocks.length > 0 ? "complete" : undefined,
      // Restore canvas flag so the editable CanvasEditor renders after
      // a refetch / reload. Persisted in the message's `properties` JSON
      // by the backend when canvas was on.
      canvasEnabled: !!props?.canvas_enabled,
      // Restore HITL metadata from persisted properties.
      // Fallback to text inference because some interrupted rows may miss fields.
      hitl: isHitl,
      hitlActions: isHitl ? parsedActions : undefined,
      hitlThreadId: isHitl ? (props.thread_id ?? m.session_id ?? "") : undefined,
      // Default false when missing: backend stores playground runs as
      // is_deployed_run=false with no assignee, and showing "Pending dept admin"
      // for those runs contradicts the HITL page (which shows "Unassigned").
      hitlIsDeployed: isHitl
        ? (props.is_deployed_run !== undefined ? !!props.is_deployed_run : false)
        : undefined,
      reasoningContent: (m as any).reasoning_content || undefined,
      // Feedback (thumbs up/down) — hydrated from DB so state persists on reload.
      feedbackRating: ((m as any).feedback_rating ?? null) as "up" | "down" | null,
      feedbackReasons: ((m as any).feedback_reasons ?? null) as string[] | null,
      feedbackComment: ((m as any).feedback_comment ?? null) as string | null,
      feedbackAt: ((m as any).feedback_at ?? null) as string | null,
    };
  });
}

type SessionSelectionHint =
  | { mode: "agent"; deploymentId?: string; agentId?: string }
  | { mode: "model"; modelId: string }
  | null;

function inferSessionSelectionHint(messages: OrchMessageResponse[]): SessionSelectionHint {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (!msg || (msg.category && msg.category !== "message")) continue;

    const deploymentId = msg.deployment_id || undefined;
    const agentId = msg.agent_id || undefined;
    if (deploymentId || agentId) {
      return { mode: "agent", deploymentId, agentId };
    }

    const modelId = (msg as any).model_id || undefined;
    if (modelId) {
      return { mode: "model", modelId };
    }
  }
  return null;
}

function findAgentFromSessionSummary(
  sessionInfo: OrchSessionSummary | undefined,
  agents: Agent[],
): Agent | undefined {
  if (!sessionInfo) return undefined;

  if (sessionInfo.active_deployment_id) {
    const byDeployment = agents.find(
      (a) => a.id === sessionInfo.active_deployment_id || a.deploy_id === sessionInfo.active_deployment_id,
    );
    if (byDeployment) return byDeployment;
  }

  if (sessionInfo.active_agent_id) {
    const byAgentId = agents.find((a) => a.agent_id === sessionInfo.active_agent_id);
    if (byAgentId) return byAgentId;
  }

  if (sessionInfo.active_agent_name) {
    return agents.find((a) => a.name === sessionInfo.active_agent_name);
  }

  return undefined;
}

function hitlStatusLabel(value: string): string {
  const normalized = (value || "").toLowerCase();
  if (normalized.includes("reject")) return "Rejected";
  if (normalized.includes("approve")) return "Approved";
  if (normalized.includes("edit")) return "Edited";
  if (normalized.includes("cancel")) return "Cancelled";
  if (normalized.includes("timeout")) return "Timed out";
  return "Resolved";
}

function groupSessionsByDate(
  sessions: OrchSessionSummary[],
  getLabel: (key: string) => string,
): Record<string, OrchSessionSummary[]> {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);

  const groups: Record<string, OrchSessionSummary[]> = {};

  for (const s of sessions) {
    const ts = s.last_timestamp ? new Date(s.last_timestamp) : new Date(0);
    let label: string;
    if (ts >= today) label = getLabel("Today");
    else if (ts >= yesterday) label = getLabel("Yesterday");
    else if (ts >= weekAgo) label = getLabel("Previous 7 Days");
    else label = getLabel("Older");

    if (!groups[label]) groups[label] = [];
    groups[label].push(s);
  }
  return groups;
}

/* ------------------ AI MODEL OPTIONS (Addon) ------------------ */

interface AiModelOption {
  id: string;
  name: string;
  icon: string;        // image path (svg/png) for the model
  group: "main" | "more";
  capabilities?: Record<string, any>;
  is_default?: boolean;
}

// Resolve a model logo by matching id/name/provider against known patterns.
function resolveModelIcon(model: { model_id?: string; model_name?: string; display_name?: string; provider?: string }): string {
  // If display_name starts with "mibuddy", always show mibuddy icon regardless of model family.
  // Only check display_name — model_id may contain "mibuddy" as a prefix for all models (e.g. "mibuddy-gpt-5.2-chat").
  const displayName = (model.display_name || "").toLowerCase();
  if (/^mibuddy/.test(displayName)) return micoreLogo;

  // Combine all name fields + provider so we can match the actual model family
  // even when it's deployed behind a provider like Azure.
  const hay = `${model.model_id || ""} ${model.model_name || ""} ${model.display_name || ""} ${model.provider || ""}`.toLowerCase();

  // 1. Match specific model families first (order matters — most specific first)
  if (/dall[\s_-]?e/.test(hay)) return dalleLogo;
  if (/grok/.test(hay)) return grokLogo;
  if (/nano[\s_-]?banana/.test(hay)) return nanoBananaLogo;
  if (/web[\s_-]?search|google[\s_-]?search/.test(hay)) return googleLogo;
  if (/gemini|bard|palm/.test(hay)) return geminiLogo;
  if (/mistral|mixtral/.test(hay)) return mistralLogo;
  if (/claude|anthropic/.test(hay)) return claudeLogo;
  if (/llama|meta/.test(hay)) return metaLogo;
  if (/cohere|command[\s_-]?r/.test(hay)) return cohereLogo;
  if (/perplexity|sonar/.test(hay)) return perplexityLogo;
  if (/nvidia|nemotron/.test(hay)) return nvidiaLogo;
  if (/hugging[\s_-]?face/.test(hay)) return huggingfaceLogo;
  if (/gpt|openai|o[13][\s_-]|o[13]$|o4/.test(hay)) return openaiLogo;

  // 2. MiBuddy / MiCore — only if no known model family matched above
  if (/mibuddy|mi[\s_-]?core|micore/.test(hay)) return micoreLogo;

  // 3. Provider-based fallbacks (e.g. azure with a custom deployment name)
  const provider = (model.provider || "").toLowerCase();
  if (provider === "openai" || provider === "openai_compatible") return openaiLogo;
  if (provider === "azure" || provider === "azure_ai") return micoreLogo;
  if (provider === "anthropic") return claudeLogo;
  if (provider === "google" || provider === "google_vertex") return geminiLogo;
  return defaultLlmLogo;
}


// Empty default — models are fetched from API on mount
const FALLBACK_AI_MODELS: AiModelOption[] = [];

/* ------------------ IMAGE GALLERY VIEW ------------------ */

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"];

function ImageGalleryView({
  onBack,
  selectedImage,
  onSelectImage,
  onClosePreview,
}: {
  onBack: () => void;
  selectedImage: { src: string; name: string; shareSrc?: string } | null;
  onSelectImage: (img: { src: string; name: string; shareSrc?: string }) => void;
  onClosePreview: () => void;
}) {
  const { t } = useTranslation();
  const [images, setGalleryImages] = useState<
    { id: string; name: string; src: string; shareSrc: string; createdAt: string }[]
  >([]);
  const [isLoading, setGalleryLoading] = useState(true);

  // Fetch AI-generated images from MiBuddy dedicated endpoint
  useEffect(() => {
    const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
    const headers: Record<string, string> = {};
    if (tokenMatch?.[1]) headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;

    fetch(`${getURL("ORCHESTRATOR")}/generated-images`, { headers, credentials: "include" })
      .then((res) => res.json())
      .then((data: any[]) => {
        setGalleryImages(
          (data || []).map((img: any, idx: number) => ({
            id: `gen-${idx}`,
            name: img.name || "AI Generated Image",
            src: img.src || "",
            // Prefer app-proxied URL for sharing (verified working in current session).
            // Fall back to direct blob URL when proxy URL is unavailable.
            shareSrc: img.src || img.share_url || "",
            createdAt: "",
          })),
        );
      })
      .catch((err) => console.warn("Failed to load generated images:", err))
      .finally(() => setGalleryLoading(false));
  }, []);

  const handleDownload = async (src: string, name: string) => {
    try {
      // MiBuddy-style: public blob URLs (https://...blob.core.windows.net/...) need
      // no auth. Our proxied /api/... URLs need JWT. Auto-detect which applies.
      const isPublicBlob = /\.blob\.core\.windows\.net\//i.test(src);
      const headers: Record<string, string> = {};
      if (!isPublicBlob) {
        const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
        if (tokenMatch?.[1]) {
          headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;
        }
      }
      const res = await fetch(src, isPublicBlob ? {} : { headers, credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name || `image-${Date.now()}.png`;
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // Delay revoke slightly to ensure the download kicks off on all browsers
      setTimeout(() => URL.revokeObjectURL(url), 500);
    } catch (err) {
      console.error("[handleDownload] Failed:", err);
      // Last-resort fallback: trigger download via anchor with download attr
      // (works for same-origin URLs). Avoid window.open which just expands the image.
      const a = document.createElement("a");
      a.href = src;
      a.download = name || `image-${Date.now()}.png`;
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  };

  // Share a generated image using the browser's native Web Share API.
  // Windows/iOS/Android will open the OS-level share sheet (WhatsApp, Teams,
  // Outlook, Gmail, LinkedIn, etc.). Firefox / older browsers fall back to
  // copying the image URL to the clipboard.
  const toAbsoluteUrl = (rawUrl: string) => {
    try {
      return new URL(rawUrl, window.location.origin).toString();
    } catch {
      return rawUrl;
    }
  };

  const handleShare = async (src: string, name: string) => {
    const title = name || "Generated Image";
    const shareUrl = toAbsoluteUrl(src);

    // 1) MiBuddy-parity URL share first
    try {
      if ((navigator as any).share) {
        await (navigator as any).share({ title, url: shareUrl });
        return;
      }
    } catch (err: any) {
      if (err?.name === "AbortError") return;
      console.warn("[handleShare] URL share failed, trying file share:", err);
    }

    // 2) Fallback to file share
    try {
      const isPublicBlob = /\.blob\.core\.windows\.net\//i.test(shareUrl);
      const headers: Record<string, string> = {};
      if (!isPublicBlob) {
        const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
        if (tokenMatch?.[1]) {
          headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;
        }
      }
      const res = await fetch(shareUrl, isPublicBlob ? {} : { headers, credentials: "include" });
      if (res.ok) {
        const blob = await res.blob();
        const file = new File([blob], name || `image-${Date.now()}.png`, {
          type: blob.type || "image/png",
        });
        if ((navigator as any).share && (navigator as any).canShare?.({ files: [file] })) {
          await (navigator as any).share({ title, files: [file] });
          return;
        }
      }
    } catch (err: any) {
      if (err?.name === "AbortError") return;
      console.warn("[handleShare] File share failed, falling back to clipboard:", err);
    }

    // 3) Final fallback: copy share URL
    try {
      await navigator.clipboard.writeText(shareUrl);
      useAlertStore.getState().setSuccessData?.({ title: "Image link copied to clipboard" });
    } catch {
      useAlertStore.getState().setErrorData?.({
        title: "Unable to share",
        list: ["Your browser doesn't support sharing. Please copy the link manually."],
      });
    }
  };
  return (
    <div className="relative flex flex-1 flex-col">
      {/* Header */}
      <div className="flex h-[52px] shrink-0 items-center gap-3 border-b border-border px-4">
        <button
          onClick={onBack}
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <ArrowLeft size={18} />
        </button>
        <Image size={20} className="text-primary" />
        <h2 className="text-base font-semibold text-foreground">{t("My Images")}</h2>
        <span className="ml-auto text-xs text-muted-foreground">
          {images.length > 0 ? `${images.length} ${t("most recent")}` : ""}
        </span>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 size={32} className="animate-spin text-muted-foreground" />
          </div>
        ) : images.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-muted-foreground">
            <Image size={48} className="opacity-30" />
            <p className="text-lg">{t("No images available")}</p>
            <p className="text-sm">{t("Images generated by agents will appear here")}</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {images.map((img) => (
              <div
                key={img.id}
                className="group relative cursor-pointer overflow-hidden rounded-xl border border-border bg-muted/30 transition-shadow hover:shadow-lg hover:border-primary/50"
                onClick={() => onSelectImage({ src: img.src, name: img.name, shareSrc: img.shareSrc })}
              >
                <div className="aspect-square overflow-hidden">
                  <img
                    src={img.src}
                    alt={img.name}
                    className="h-full w-full object-cover transition-transform group-hover:scale-105"
                    loading="lazy"
                  />
                </div>
                <div className="absolute inset-0 flex flex-col justify-end bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 transition-opacity group-hover:opacity-100">
                  <div className="flex items-center justify-between p-3">
                    <span className="max-w-[60%] truncate text-xs font-medium text-white">{img.name}</span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleShare(img.shareSrc, img.name); }}
                        className="rounded-full bg-white/20 p-1.5 text-white backdrop-blur-sm hover:bg-white/40"
                        title="Share"
                      >
                        <Share2 size={14} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDownload(img.src, img.name); }}
                        className="rounded-full bg-white/20 p-1.5 text-white backdrop-blur-sm hover:bg-white/40"
                        title="Download"
                      >
                        <Download size={14} />
                      </button>
                    </div>
                  </div>
                </div>
                {img.createdAt && (
                  <div className="absolute right-2 top-2 rounded-md bg-black/40 px-1.5 py-0.5 text-xxs text-white opacity-0 backdrop-blur-sm group-hover:opacity-100">
                    {new Date(img.createdAt).toLocaleDateString()}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Lightbox */}
      {selectedImage && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/80" onClick={onClosePreview}>
          <div className="relative flex max-h-[90vh] max-w-[90vw] flex-col items-center" onClick={(e) => e.stopPropagation()}>
            <button onClick={onClosePreview} className="absolute -right-3 -top-3 z-10 rounded-full bg-zinc-800 p-2 text-white shadow-lg hover:bg-zinc-700">
              <X size={18} />
            </button>
            <img src={selectedImage.src} alt={selectedImage.name} className="max-h-[80vh] max-w-[85vw] rounded-lg object-contain" />
            <div className="mt-4 flex items-center gap-4">
              <span className="max-w-xs truncate text-sm text-white/80">{selectedImage.name}</span>
              <button
                onClick={() => handleShare(selectedImage.shareSrc || selectedImage.src, selectedImage.name)}
                className="flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2 text-sm text-white backdrop-blur-sm hover:bg-white/20"
              >
                <Share2 size={16} />
                {t("Share")}
              </button>
              <button onClick={() => handleDownload(selectedImage.src, selectedImage.name)} className="flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2 text-sm text-white backdrop-blur-sm hover:bg-white/20">
                <Download size={16} />
                {t("Download")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------ THINKING INDICATOR ------------------ */
/**
 * Renders the agent loading state. Two flavours:
 *  - With files attached: progressive timed stages
 *      0–600ms      "Resolving attachments…"
 *      600–2500ms   "Reading <filename>…" (rotates if multiple)
 *      2500ms+      "Generating response…"
 *  - Without files: cycles generic phrases.
 * Plus: animated dots, live elapsed counter, and skeleton lines.
 *
 * Stages here are TIME-BASED (frontend-only). For genuine backend-event
 * stages, an SSE protocol upgrade is required (see chat history).
 */
function ThinkingIndicator({
  fileNames,
  routedMode,
}: {
  fileNames: string[];
  routedMode: string | null;
}) {
  const { t } = useTranslation();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed(Date.now() - start), 200);
    return () => clearInterval(id);
  }, []);

  const hasFiles = fileNames.length > 0;

  // Stage durations: tuned slow so labels read like a deliberate UX, not a flicker.
  const RESOLVE_MS = 1500;       // "Resolving attachments…"
  const READ_PER_FILE_MS = 3000; // each file gets a full 3s of "Reading X…"
  const PHRASE_DWELL_MS = 3000;  // each generic phrase shows for 3s

  let label: string;
  if (hasFiles) {
    if (elapsed < RESOLVE_MS) {
      label = t("Resolving attachments");
    } else {
      const readingPhaseTotal = READ_PER_FILE_MS * fileNames.length;
      if (elapsed < RESOLVE_MS + readingPhaseTotal) {
        const fileIdx = Math.floor((elapsed - RESOLVE_MS) / READ_PER_FILE_MS) % fileNames.length;
        label = `${t("Reading")} ${fileNames[fileIdx]}`;
      } else {
        label = t("Generating response");
      }
    }
  } else if (routedMode === "image_gen") {
    const phrases = [
      t("Understanding your prompt"),
      t("Generating image"),
      t("Adding final touches"),
    ];
    const idx = Math.floor(elapsed / PHRASE_DWELL_MS) % phrases.length;
    label = phrases[idx];
  } else if (routedMode === "web_search") {
    const phrases = [
      t("Searching the web"),
      t("Reading top results"),
      t("Summarizing findings"),
    ];
    const idx = Math.floor(elapsed / PHRASE_DWELL_MS) % phrases.length;
    label = phrases[idx];
  } else {
    // No routing decision (covers agents — which never emit a routing event —
    // and the pre-routing gap for models). Also catches routedMode === "chat".
    const phrases = [
      t("Reading your message"),
      t("Thinking"),
      t("Drafting a reply"),
    ];
    const idx = Math.floor(elapsed / PHRASE_DWELL_MS) % phrases.length;
    label = phrases[idx];
  }

  // Animated dots — one dot fades in per 400ms cycle
  const dotCount = (Math.floor(elapsed / 400) % 3) + 1;
  const dots = ".".repeat(dotCount);

  // Skeleton differs per output type. Image-gen → square placeholder
  // (the actual image is what's coming), everything else → text bars.
  const isImageOutput = routedMode === "image_gen";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2 text-sm text-muted-foreground">
        <span className="font-medium">
          {label}
          <span className="inline-block w-4 text-left">{dots}</span>
        </span>
      </div>
      {isImageOutput ? (
        <div className="flex h-48 w-48 animate-pulse items-center justify-center rounded-lg bg-muted-foreground/20">
          <Image size={32} className="text-muted-foreground/40" />
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <div className="h-2 w-3/4 animate-pulse rounded bg-muted-foreground/30" />
          <div className="h-2 w-5/6 animate-pulse rounded bg-muted-foreground/30" style={{ animationDelay: "150ms" }} />
          <div className="h-2 w-2/3 animate-pulse rounded bg-muted-foreground/30" style={{ animationDelay: "300ms" }} />
        </div>
      )}
    </div>
  );
}

/* ------------------ COMPONENT ------------------ */

function resolveDisplayIcon(icon: string, isDark: boolean): string {
  if (!isDark) return icon;
  if (icon === openaiLogo) return openaiLightLogo;
  if (icon === grokLogo) return grokLogoLight;
  return icon;
}

export default function AgentOrchestrator() {
  const { t } = useTranslation();
  const isDark = useDarkStore((state) => state.dark);
  const { permissions } = useContext(AuthContext);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [showMentions, setShowMentions] = useState(false);
  const [filteredAgents, setFilteredAgents] = useState<Agent[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string>(crypto.randomUUID());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  // Tracks which session the in-flight request belongs to. When the user
  // switches to a different chat while a response is streaming, only the
  // sending session's input should be blocked — not the new one.
  const [sendingSessionId, setSendingSessionId] = useState<string | null>(null);
  const [streamingAgentName, setStreamingAgentName] = useState<string>("");
  const [streamingMsgId, setStreamingMsgId] = useState<string | null>(null);
  // HITL state: track which message had its action clicked
  const [hitlDoneMap, setHitlDoneMap] = useState<Record<string, string>>({});
  const [hitlLoadingId, setHitlLoadingId] = useState<string | null>(null);
  const [hitlLoadingAction, setHitlLoadingAction] = useState<string | null>(null);
  const [uploadFiles, setUploadFiles] = useState<FilePreview[]>([]);
  // Addon UI state
  const [showPlusMenu, setShowPlusMenu] = useState(false);
  const [plusMenuPos, setPlusMenuPos] = useState<{ bottom: number; left: number }>({ bottom: 0, left: 0 });
  const [showAppsPopover, setShowAppsPopover] = useState(false);
  const [appsPopoverPos, setAppsPopoverPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const appsPopoverRef = useRef<HTMLDivElement>(null);
  const [showAgentsPopover, setShowAgentsPopover] = useState(false);
  const [agentsPopoverPos, setAgentsPopoverPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const [cotReasoning, setCotReasoning] = useState(false);
  const [showChatHistoryExpand, setShowChatHistoryExpand] = useState(false);
  const [showArchiveChatExpand, setShowArchiveChatExpand] = useState(false);
  const [sidebarSearchQuery, setSidebarSearchQuery] = useState("");
  const [showSearchInput, setShowSearchInput] = useState(false);
  const [chatMenuOpenId, setChatMenuOpenId] = useState<string | null>(null);
  // Context of the three-dot menu: "active" for chat history rows (Rename /
  // Share / Archive / Delete) vs "archived" (Unarchive / Delete).
  const [chatMenuContext, setChatMenuContext] = useState<"active" | "archived">("active");
  // Per-session override of the user-chosen title. Optimistic update only —
  // the authoritative value lives in `chat.session_title` from the sessions
  // API. This ref/state is for instant UI feedback before the API returns.
  const [titleOverrides, setTitleOverrides] = useState<Record<string, string | null>>({});
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState<string>("");
  const [chatMenuPos, setChatMenuPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  // Addon: AI Model selector state
  const [showAiModelPicker, setShowAiModelPicker] = useState(false);
  const [showMoreModels, setShowMoreModels] = useState(false);
  const [selectedAiModel, setSelectedAiModel] = useState<string | null>(null);
  // Header-only model label override (used for routed specialist turns like
  // web search) without mutating selectedAiModel/request model.
  const [headerModelOverride, setHeaderModelOverride] = useState<{
    name: string;
    icon?: string;
  } | null>(null);
  const [aiModels, setAiModels] = useState<AiModelOption[]>(FALLBACK_AI_MODELS);
  const [noAgentMode, setNoAgentMode] = useState(false);
  // Addon: SharePoint file picker
  const [spPickerOpen, setSpPickerOpen] = useState(false);
  // Addon: Image gallery view (replaces chat area when active)
  const [showImageGallery, setShowImageGallery] = useState(false);
  const [showNotebookLM, setShowNotebookLM] = useState(false);
  const [showOutlookOrch, setShowOutlookOrch] = useState(false);
  const { isOutlookConnected: isOutlookOrchConnected, setIsOutlookConnected: setIsOutlookOrchConnected } =
    useOutlookOrchStatus();
  const [selectedGalleryImage, setSelectedGalleryImage] = useState<
    { src: string; name: string; shareSrc?: string } | null
  >(null);
  // Addon: Canvas mode
  const [isCanvasEnabled, setIsCanvasEnabled] = useState(false);
  // Addon: Image generation mode (sticky chip — stays until user clicks ×)
  const [imageMode, setImageMode] = useState(false);
  // Per-send routing decision from backend SSE "routing" event. Drives the
  // ThinkingIndicator's phrase set and skeleton shape ("image_gen" → image
  // placeholder + "Generating image"; "web_search" → search phrases; etc.).
  // Null = backend hasn't decided yet (gap between send and routing event).
  const [routedMode, setRoutedMode] = useState<string | null>(null);
  // Addon: Per-message export menu (msg.id) and copy feedback
  const [exportMenuOpenId, setExportMenuOpenId] = useState<string | null>(null);
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);
  // Addon: Per-message share/more-options menu
  const [shareMenuOpenId, setShareMenuOpenId] = useState<string | null>(null);
  // Inline prompt editing (user messages)
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<string>("");
  // Feedback popup (thumbs up/down) — opens when the user picks a rating or
  // switches from one to the other. Null while no popup is active.
  const [feedbackPopup, setFeedbackPopup] = useState<{
    messageId: string;
    mode: "up" | "down";
    initialReasons: string[];
    initialComment: string;
  } | null>(null);

  // ------------------------------------------------------------------
  // Thumbs up/down feedback handlers (MiBuddy-parity)
  //  1. First vote on a message         → opens popup, POST on submit
  //  2. Clicking the opposite thumb     → opens popup for the new rating,
  //                                       POST overwrites the same DB row
  //  3. Clicking the active thumb again → DELETE endpoint clears the row
  //  4. Double-click Submit in popup    → disabled while in-flight (see popup)
  // ------------------------------------------------------------------
  const feedbackAuthHeaders = (): Record<string, string> => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
    if (tokenMatch?.[1]) headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;
    return headers;
  };

  const handleRemoveFeedback = async (messageId: string): Promise<void> => {
    const previous = messages.find((m) => m.id === messageId);
    // Optimistic clear.
    setMessages((prev) => prev.map((m) => (
      m.id === messageId
        ? { ...m, feedbackRating: null, feedbackReasons: null, feedbackComment: null, feedbackAt: null }
        : m
    )));

    try {
      const res = await fetch(
        `${getURL("ORCHESTRATOR")}/messages/${encodeURIComponent(messageId)}/feedback`,
        { method: "DELETE", headers: feedbackAuthHeaders(), credentials: "include" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      console.error("[handleRemoveFeedback] failed:", err);
      if (previous) {
        setMessages((prev) => prev.map((m) => (m.id === messageId ? previous : m)));
      }
      useAlertStore.getState().setErrorData?.({
        title: "Could not remove rating",
        list: ["Please try again."],
      });
    }
  };

  const handleThumbClick = (msg: Message, rating: "up" | "down") => {
    if (msg.sender !== "agent") return;
    // Case 3: clicking the already-active thumb → un-vote → DELETE.
    if (msg.feedbackRating === rating) {
      void handleRemoveFeedback(msg.id);
      return;
    }
    // Cases 1 & 2: first vote or switch → open popup, pre-fill if switching.
    setFeedbackPopup({
      messageId: msg.id,
      mode: rating,
      initialReasons: msg.feedbackRating === rating ? (msg.feedbackReasons ?? []) : [],
      initialComment: msg.feedbackRating === rating ? (msg.feedbackComment ?? "") : "",
    });
  };

  const handleSubmitFeedback = async (reasons: string[], comment: string): Promise<void> => {
    if (!feedbackPopup) return;
    const { messageId, mode } = feedbackPopup;

    // Optimistic update — UI fills the thumb immediately.
    const previous = messages.find((m) => m.id === messageId);
    setMessages((prev) => prev.map((m) => (
      m.id === messageId
        ? {
            ...m,
            feedbackRating: mode,
            feedbackReasons: reasons.length ? reasons : null,
            feedbackComment: comment || null,
            feedbackAt: new Date().toISOString(),
          }
        : m
    )));

    try {
      const res = await fetch(
        `${getURL("ORCHESTRATOR")}/messages/${encodeURIComponent(messageId)}/feedback`,
        {
          method: "POST",
          headers: feedbackAuthHeaders(),
          credentials: "include",
          body: JSON.stringify({ rating: mode, reasons, comment: comment || null }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // Reconcile with server-returned state (authoritative).
      setMessages((prev) => prev.map((m) => (
        m.id === messageId
          ? {
              ...m,
              feedbackRating: (data.feedback_rating ?? null) as "up" | "down" | null,
              feedbackReasons: data.feedback_reasons ?? null,
              feedbackComment: data.feedback_comment ?? null,
              feedbackAt: data.feedback_at ?? null,
            }
          : m
      )));
      setFeedbackPopup(null);
    } catch (err) {
      console.error("[handleSubmitFeedback] failed:", err);
      if (previous) {
        setMessages((prev) => prev.map((m) => (m.id === messageId ? previous : m)));
      }
      useAlertStore.getState().setErrorData?.({
        title: "Could not save feedback",
        list: ["Please try again."],
      });
      throw err; // let FeedbackPopup re-enable Submit
    }
  };

  // Ref holder so handleSaveEdit can call handleSend without creating a circular
  // useCallback dependency chain. Accepts an optional override text for edit-and-send.
  const handleSendRef = useRef<((overrideText?: string) => void) | null>(null);
  const [canvasEditingId, setCanvasEditingId] = useState<string | null>(null);
  const [canvasEditTexts, setCanvasEditTexts] = useState<Record<string, string>>({});
  // Addon: Autocomplete suggestions
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedSuggestionIdx, setSelectedSuggestionIdx] = useState(-1);
  const suggestionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // AbortController so we can cancel any in-flight suggestion fetches when the
  // user clicks Send. Without this, a debounced fetch can return AFTER the
  // message is submitted and re-show suggestions under the response.
  const suggestionAbortRef = useRef<AbortController | null>(null);
  // Addon: Speech-to-Text (mic)
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<any>(null);
  // Outlook connector state moved to useOutlookOrchStatus (see OutlookOrchConnector).
  // Kept these stub locals so refs from older code paths still compile; they
  // are not connected to anything.

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const TEXTAREA_MAX_HEIGHT = 124;

  // Auto-grow textarea to fit content (MiBuddy-style), up to max height
  const autoGrowTextarea = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const sh = ta.scrollHeight;
    if (sh <= TEXTAREA_MAX_HEIGHT) {
      ta.style.overflowY = "hidden";
      ta.style.height = `${sh}px`;
    } else {
      ta.style.overflowY = "auto";
      ta.style.height = `${TEXTAREA_MAX_HEIGHT}px`;
    }
  }, []);

  useEffect(() => { autoGrowTextarea(); }, [input, autoGrowTextarea]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const aiModelPickerRef = useRef<HTMLDivElement>(null);
  const hitlSessionRef = useRef<string | null>(null);
  const sessionSelectionSyncRef = useRef<string | null>(null);
  // Tracks message IDs that were just regenerated via the edit endpoint, with
  // the wall-clock time of the edit. The polling-refetch merge prefers API
  // content over local when local isn't longer (see merge useEffect) — fine
  // for text edits, but for image edits the new and old URLs have identical
  // length, so the heuristic falls through and a stale read-replica response
  // can briefly clobber the just-applied new image. While an ID lives in this
  // ref we keep local content during the merge.
  const recentlyEditedRef = useRef<Map<string, number>>(new Map());
  const RECENT_EDIT_TTL_MS = 30_000;

  /* ------------------ FILE UPLOAD ------------------ */

  const { mutate: uploadFileMutate } = usePostUploadFileV2();
  // Model mode (No Agent): allow documents + images
  // Agent mode: allow images only
  const IMAGE_EXTENSIONS_LIST = ["png", "jpg", "jpeg"];
  const DOC_EXTENSIONS_LIST = [
    "pdf", "docx", "pptx", "xlsx", "xls",                   // Documents
    "txt", "md", "csv",                                      // Text
    "py", "js", "ts", "java", "cpp", "c", "cs", "go",       // Code
    "json", "html", "css", "php", "rb", "sh", "tex",        // More code/markup
  ];
  // Both modes accept all file types (images + documents). Agent mode previously
  // restricted to images only — removed per UX feedback.
  const ALLOWED_EXTENSIONS = [...IMAGE_EXTENSIONS_LIST, ...DOC_EXTENSIONS_LIST];

  const uploadFile = (file: File) => {
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ext || !ALLOWED_EXTENSIONS.includes(ext)) return;

    const id = crypto.randomUUID().slice(0, 10);
    setUploadFiles((prev) => [...prev, { id, file, loading: true, error: false }]);

    if (noAgentMode) {
      // Model mode: upload to MiBuddy dedicated container
      const formData = new FormData();
      formData.append("file", file);
      const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
      const headers: Record<string, string> = {};
      if (tokenMatch?.[1]) headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;

      fetch(`${getURL("ORCHESTRATOR")}/upload`, {
        method: "POST",
        headers,
        credentials: "include",
        body: formData,
      })
        .then((res) => {
          if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
          return res.json();
        })
        .then((data) => {
          setUploadFiles((prev) =>
            prev.map((f) => (f.id === id ? { ...f, loading: false, path: data.file_path } : f)),
          );
        })
        .catch(() => {
          setUploadFiles((prev) =>
            prev.map((f) => (f.id === id ? { ...f, loading: false, error: true } : f)),
          );
        });
    } else {
      // Agent mode: upload to main storage (existing flow)
      uploadFileMutate(
        { file },
        {
          onSuccess: (data: any) => {
            setUploadFiles((prev) =>
              prev.map((f) => (f.id === id ? { ...f, loading: false, path: data.file_path } : f)),
            );
          },
          onError: () => {
            setUploadFiles((prev) =>
              prev.map((f) => (f.id === id ? { ...f, loading: false, error: true } : f)),
            );
          },
        },
      );
    }
  };

  const MAX_FILES = 10;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    const currentCount = uploadFiles.length;
    const available = MAX_FILES - currentCount;

    if (available <= 0) {
      alert(`Maximum ${MAX_FILES} files allowed.`);
      e.target.value = "";
      return;
    }

    const filesToUpload = Array.from(files).slice(0, available);
    if (files.length > available) {
      alert(`Only ${available} file(s) can be added. Maximum is ${MAX_FILES}.`);
    }

    for (const file of filesToUpload) {
      uploadFile(file);
    }
    e.target.value = "";
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    // Enforce the 5-file limit on paste too (not just the file picker)
    if (uploadFiles.length >= MAX_FILES) {
      alert(`Maximum ${MAX_FILES} files allowed.`);
      e.preventDefault();
      return;
    }
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        const blob = items[i].getAsFile();
        if (blob) {
          e.preventDefault();
          uploadFile(blob);
          return;
        }
      }
    }
  };

  const removeFile = (id: string) => {
    setUploadFiles((prev) => prev.filter((f) => f.id !== id));
  };

  /* ------------------ SHAREPOINT FILE PICKER (Addon) ------------------ */

  const handleSpFilesSelected = (files: File[]) => {
    const rejected: string[] = [];
    for (const file of files) {
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (!ext || !ALLOWED_EXTENSIONS.includes(ext)) {
        rejected.push(file.name);
        continue;
      }
      uploadFile(file);
    }
    if (rejected.length > 0) {
      const allowedHint = noAgentMode
        ? "Allowed file types: documents and images."
        : "When an agent is selected, only image files are accepted. Switch to Model mode to upload documents.";
      useAlertStore.getState().setErrorData({
        title: "Some SharePoint files were not uploaded",
        list: [...rejected, allowedHint],
      });
    }
  };

  /* ------------------ API HOOKS ------------------ */

  const { data: apiAgents } = useGetOrchAgents();
  const { data: apiSessions, refetch: refetchSessions } = useGetOrchSessions();
  const { mutate: deleteSession } = useDeleteOrchSession();

  /* MiBuddy-parity share-link deep-link: when the page mounts with
   * `?session=<id>` in the URL (typical when a user pastes a shared
   * link), remember the session id. ProtectedRoute has already bounced
   * an unauthenticated viewer through login before we get here. */
  const [pendingSharedId, setPendingSharedId] = useState<string | null>(null);
  const [isSharedReadOnly, setIsSharedReadOnly] = useState(false);
  const sharedLinkCapturedRef = useRef(false);
  useEffect(() => {
    if (sharedLinkCapturedRef.current) return;
    sharedLinkCapturedRef.current = true;
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session");
    if (!sid) return;
    setPendingSharedId(sid);
    setShowImageGallery(false);
    // Strip the query param so a refresh doesn't re-trigger.
    const clean = window.location.pathname + window.location.hash;
    window.history.replaceState({}, "", clean);
  }, []);

  const agents: Agent[] = useMemo(
    () => (apiAgents ? mapApiAgents(apiAgents) : []),
    [apiAgents],
  );
  const selectedAgent = useMemo(
    () => agents.find((a) => a.id === selectedModelId) || agents[0],
    [agents, selectedModelId],
  );
  const canInteract = permissions?.includes("interact_agents") ?? false;
  // Per-session send-in-progress flag. Lets the user start a NEW chat while
  // an old one is still streaming a response, instead of being globally
  // locked out of all chats.
  const isSendingThisSession = isSending && sendingSessionId === currentSessionId;

  // Block typing/sending while an agent is waiting for an HITL approve/reject.
  // Why: once the agent pauses for human review, new user input must not be
  // sent until the pending decision is resolved — otherwise the resume call
  // loses context and the UI desyncs.
  const hasPendingHitl = useMemo(() => {
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (!msg.hitl) continue;
      const explicitHitlStatus = hitlDoneMap[msg.id];
      const hasFollowupAgentReply = messages
        .slice(i + 1)
        .some(
          (nextMsg) =>
            nextMsg.sender === "agent" &&
            !nextMsg.hitl &&
            (!!nextMsg.content?.trim() || !!nextMsg.contentBlocks?.length),
        );
      const resolved = msg.hitlIsDeployed
        ? !!explicitHitlStatus
        : (!!explicitHitlStatus || hasFollowupAgentReply);
      if (!resolved) return true;
    }
    return false;
  }, [messages, hitlDoneMap]);

  // The effective session ID for fetching messages: activeSessionId is set
  // when the user clicks a session in the sidebar.  When null (e.g. after
  // streaming created a new session), fall back to currentSessionId if it
  // exists in the sessions list (meaning it was persisted to the DB).
  const effectiveSessionId = useMemo(() => {
    if (activeSessionId) return activeSessionId;
    if (apiSessions?.some((s) => s.session_id === currentSessionId)) return currentSessionId;
    return null;
  }, [activeSessionId, currentSessionId, apiSessions]);

  useEffect(() => {
    if (!effectiveSessionId) {
      sessionSelectionSyncRef.current = null;
    }
  }, [effectiveSessionId]);

  // Load messages when switching to an existing session
  const { data: apiSessionMessages, refetch: refetchMessages } = useGetOrchMessages(
    { session_id: effectiveSessionId || "" },
    {
      enabled: !!effectiveSessionId,
      refetchOnWindowFocus: true,
      staleTime: 0,
      // Prevent background polling from clobbering the local streaming placeholder/tokens.
      refetchInterval: isSending ? false : 5000,
    },
  );

  useEffect(() => {
    if (apiSessionMessages && effectiveSessionId) {
      // Keep local in-flight stream state intact for the active session.
      if (isSending && effectiveSessionId === currentSessionId) {
        return;
      }
      const mapped = mapApiMessages(apiSessionMessages);
      // DEBUG: log what's arriving from API vs what we have locally
      console.warn("[Refetch] API returned", mapped.length, "messages. Local had:", mapped.length);
      mapped.forEach((m) => {
        if (m.sender === "agent") {
          console.warn("[Refetch] API msg", m.id.slice(0, 8), "contentBlocks:", m.contentBlocks?.length || 0, "reasoning:", m.reasoningContent?.length || 0);
        }
      });
      // Preserve canvas state on refetch — the mapper reads it from
      // `properties.canvas_enabled` in the DB, but if a message was
      // already flagged in-memory we keep that flag even if the DB
      // didn't persist it (e.g. backend restart mid-stream).
      setMessages((prev) => {
        const prevCanvasIds: Record<string, boolean> = {};
        const prevById = new Map<string, Message>();
        prev.forEach((m) => {
          if (m.canvasEnabled) prevCanvasIds[m.id] = true;
          prevById.set(m.id, m);
          if (m.sender === "agent") {
            console.warn("[Refetch] Local msg", m.id.slice(0, 8), "contentBlocks:", m.contentBlocks?.length || 0, "reasoning:", m.reasoningContent?.length || 0);
          }
        });
        return mapped.map((m) => {
          const local = prevById.get(m.id);
          // Existing canvas preservation
          let merged = prevCanvasIds[m.id] ? { ...m, canvasEnabled: true } : m;
          // Also preserve contentBlocks (agent worker-node "Finished" blocks)
          // and reasoningContent (CoT thinking) if API didn't return them
          if (local) {
            // Prefer local `content` when API returns empty or shorter text —
            // this prevents the just-streamed bubble from going blank for a
            // moment while the post-end refetch lands with a DB row whose
            // persistence may briefly lag behind (read-replica delay, late
            // commit, etc). Only override when local clearly has more text.
            const apiContent = (merged.content as string | undefined) || "";
            const localContent = (local.content as string | undefined) || "";
            // Image-edit grace period: the length heuristic below can't tell
            // a new vs old image URL apart (same format → same length), so a
            // stale polling read can clobber the just-applied new image. If
            // this id was edited within the TTL, keep the authoritative
            // local content.
            const editedAt = recentlyEditedRef.current.get(m.id);
            const isRecentlyEdited =
              editedAt !== undefined && Date.now() - editedAt < RECENT_EDIT_TTL_MS;
            if (editedAt !== undefined && !isRecentlyEdited) {
              recentlyEditedRef.current.delete(m.id);
            }
            const preferredContent =
              isRecentlyEdited && localContent
                ? localContent
                : localContent && (!apiContent || localContent.length > apiContent.length)
                ? localContent
                : apiContent;

            merged = {
              ...merged,
              content: preferredContent,
              contentBlocks: merged.contentBlocks ?? local.contentBlocks,
              blocksState: merged.contentBlocks ? merged.blocksState : (local.blocksState ?? merged.blocksState),
              reasoningContent: merged.reasoningContent ?? local.reasoningContent,
            };
            if (m.sender === "agent" && (local.contentBlocks?.length || local.reasoningContent)) {
              console.warn("[Refetch] MERGED msg", m.id.slice(0, 8), "final contentBlocks:", merged.contentBlocks?.length || 0, "final reasoning:", merged.reasoningContent?.length || 0);
            }
          }
          return merged;
        });
      });
      setCurrentSessionId(effectiveSessionId);
      // Reset HITL UI state only when switching sessions (not on every poll).
      if (hitlSessionRef.current !== effectiveSessionId) {
        setHitlDoneMap({});
        setHitlLoadingId(null);
        hitlSessionRef.current = effectiveSessionId;
      }

      // Restore session-specific selection (agent vs model) only once per
      // session switch so polling doesn't override user's in-progress choice.
      if (sessionSelectionSyncRef.current !== effectiveSessionId) {
        const sessionInfo = apiSessions?.find((s) => s.session_id === effectiveSessionId);
        const hint = inferSessionSelectionHint(apiSessionMessages);

        if (hint?.mode === "model") {
          setSelectedModelId("");
          setNoAgentMode(true);
          // Restore the user's actual dropdown choice, not the model the
          // backend ended up using. Backend stores two different model_ids:
          //   - user_msg.model_id    = what you picked (your dropdown)
          //   - agent_msg.model_id   = what actually answered (overridden
          //                            to Nano Banana for auto-routed
          //                            image_gen — see orchestrator.py
          //                            ~2035-2045)
          // `hint.modelId` returns whichever model_id is on the LATEST
          // message regardless of sender, so it picks up the auto-routed
          // Nano Banana for an auto-routing turn. Walk back specifically
          // to the latest USER message so:
          //   - Explicit pick (user picked Nano Banana): user_msg.model_id
          //     is Nano Banana → chip persists across reloads.
          //   - Auto-routed (user stayed on MiBuddy AI, classifier sent the
          //     turn to image_gen): user_msg.model_id is MiBuddy AI → chip
          //     stays off, plain-text follow-ups go through normal intent
          //     classification instead of being locked into image_gen.
          let restoreModelId: string = hint.modelId;
          for (let i = apiSessionMessages.length - 1; i >= 0; i -= 1) {
            const m = apiSessionMessages[i] as any;
            if (m?.sender === "user" && m?.model_id) {
              restoreModelId = String(m.model_id);
              break;
            }
          }
          setSelectedAiModel(restoreModelId);
          setHeaderModelOverride(null);
          sessionSelectionSyncRef.current = effectiveSessionId;
          return;
        }

        if (hint?.mode === "agent") {
          let deploymentId = hint.deploymentId;
          if (!deploymentId && hint.agentId) {
            deploymentId = agents.find((a) => a.agent_id === hint.agentId)?.id;
          }
          if (deploymentId) {
            setSelectedModelId(deploymentId);
            setNoAgentMode(false);
            setHeaderModelOverride(null);
            sessionSelectionSyncRef.current = effectiveSessionId;
            return;
          }
          // Wait for agents to load if we only got agent_id.
          if (hint.agentId && agents.length === 0) {
            return;
          }
        }

        const fallbackAgent = findAgentFromSessionSummary(sessionInfo, agents);
        if (fallbackAgent) {
          setSelectedModelId(fallbackAgent.id);
          setNoAgentMode(false);
          setHeaderModelOverride(null);
          sessionSelectionSyncRef.current = effectiveSessionId;
          return;
        }

        const hasAgentInSummary =
          !!sessionInfo?.active_agent_id
          || !!sessionInfo?.active_deployment_id
          || !!sessionInfo?.active_agent_name;

        if (hasAgentInSummary && agents.length === 0) {
          return;
        }

        // No restorable session mode found: keep current/default UI state.
        sessionSelectionSyncRef.current = effectiveSessionId;
      }
    }
  }, [apiSessionMessages, effectiveSessionId, apiSessions, agents, isSending, currentSessionId]);

  /* Resolve a pending share-link session once the user's own session
   * list has loaded. If the shared session belongs to the viewer, take
   * the normal selection path (the useGetOrchMessages hook will then
   * fetch it). Otherwise treat the UUID as a MiBuddy-style share token
   * and pull messages from the `/sessions/{id}/shared-messages`
   * endpoint (authenticated, no owner filter), rendering them in
   * read-only mode. */
  useEffect(() => {
    if (!pendingSharedId) return;
    if (apiSessions === undefined) return; // sessions still loading
    const owned = apiSessions.some((s) => s.session_id === pendingSharedId);
    if (owned) {
      setActiveSessionId(pendingSharedId);
      setIsSharedReadOnly(false);
      setPendingSharedId(null);
      return;
    }
    let cancelled = false;
    const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
    const headers: Record<string, string> = {};
    if (tokenMatch?.[1]) {
      headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;
    }
    const url = `${getURL("ORCHESTRATOR")}/sessions/${encodeURIComponent(pendingSharedId)}/shared-messages`;
    fetch(url, { headers, credentials: "include" })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.text().catch(() => "");
          throw new Error(res.status === 404
            ? "This shared chat does not exist or has been deleted."
            : `Failed to load shared chat (${res.status}) ${body}`);
        }
        return res.json();
      })
      .then((payload: { is_owner: boolean; messages: OrchMessageResponse[] }) => {
        if (cancelled) return;
        const mapped = mapApiMessages(payload.messages || []);
        setMessages(mapped);
        setCurrentSessionId(pendingSharedId);
        setActiveSessionId(null); // don't trigger user-scoped fetch
        setIsSharedReadOnly(!payload.is_owner);
        setPendingSharedId(null);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        useAlertStore.getState().setErrorData?.({
          title: "Could not load shared chat",
          list: [err.message],
        });
        setPendingSharedId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pendingSharedId, apiSessions]);

  // Fetch available models from backend
  useEffect(() => {
    let cancelled = false;
    // Use native fetch to avoid axios duplicate-request interceptor
    const modelsUrl = `${getURL("ORCHESTRATOR")}/models`;
    const headers: Record<string, string> = {};
    // Extract JWT from cookie (same cookie name used by axios interceptor)
    const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
    if (tokenMatch?.[1]) {
      headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;
    }

    fetch(modelsUrl, { headers, credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: any[]) => {
        if (cancelled || !data) return;
        const models: AiModelOption[] = data.map((m: any, idx: number) => ({
          id: m.model_id,
          name: m.display_name || m.model_name,
          icon: resolveModelIcon(m),
          group: (idx < 5 ? "main" : "more") as "main" | "more",
          capabilities: m.capabilities || undefined,
          is_default: m.is_default || false,
        }));
        setAiModels(models);
      })
      .catch((err) => {
        console.warn("[OrchestratorChat] Failed to fetch models:", err.message);
      });
    return () => { cancelled = true; };
  }, []);

  // Default state on page open: No Agent selected, MiBuddy AI pre-selected in
  // the model dropdown. MUST run exactly once — without the ref guard, picking
  // an agent (which sets selectedAiModel=null) would re-trigger this effect and
  // snap the UI back to MiBuddy AI, blocking agent selection entirely.
  // Priority for model: explicit MiBuddy AI entry → is_default flag → first model.
  const didDefaultSelectRef = useRef(false);
  useEffect(() => {
    if (didDefaultSelectRef.current) return;
    if (aiModels.length === 0) return;
    // If an existing session is open, restore that session's selection
    // instead of forcing the page-level default model.
    if (effectiveSessionId) return;
    didDefaultSelectRef.current = true;
    const mibuddy = aiModels.find((m) => /mibuddy[\s_-]?ai/i.test(m.name));
    const defaultModel = mibuddy || aiModels.find((m) => m.is_default) || aiModels[0];
    if (defaultModel) {
      setSelectedAiModel(defaultModel.id);
      setNoAgentMode(true);
      setSelectedModelId("");
    }
  }, [aiModels, effectiveSessionId]);

  // Keep HITL status in sync when decisions happen on HITL Approvals page.
  // This lets orchestrator chat hide the pending banner and show final status
  // (Approved / Rejected / etc.) without requiring a full page reload.
  useEffect(() => {
    const hitlMsgs = messages.filter((m) => m.hitl && m.hitlThreadId);
    if (hitlMsgs.length === 0) return;

    let isMounted = true;
    const syncStatuses = async () => {
      try {
        // Collect unique thread_ids for visible HITL messages.
        const threadIds = Array.from(
          new Set(
            hitlMsgs
              .map((m) => m.hitlThreadId)
              .filter((t): t is string => !!t),
          ),
        );
        if (threadIds.length === 0) return;

        // Use the creator-or-assignee endpoint so the run's creator (not just
        // the dept admin assignee) also gets resolved status for the banner.
        const res = await api.get(`${getURL("HITL")}/thread-status`, {
          params: { thread_ids: threadIds.join(",") },
        });
        const rows: Array<{ thread_id?: string; status?: string; requested_at?: string }> = Array.isArray(res.data)
          ? res.data
          : [];

        // Build per-thread request timelines (oldest -> newest).
        const reqByThread = new Map<string, Array<{ status: string; requestedAt: number }>>();
        for (const row of rows) {
          if (!row?.thread_id || !row?.status) continue;
          const list = reqByThread.get(row.thread_id) ?? [];
          list.push({
            status: row.status,
            requestedAt: row.requested_at ? Date.parse(row.requested_at) : 0,
          });
          reqByThread.set(row.thread_id, list);
        }
        for (const list of reqByThread.values()) {
          list.sort((a, b) => a.requestedAt - b.requestedAt);
        }

        // Build per-thread HITL message timelines in chat order.
        const msgByThread = new Map<string, Message[]>();
        for (const msg of hitlMsgs) {
          const threadId = msg.hitlThreadId ?? "";
          const list = msgByThread.get(threadId) ?? [];
          list.push(msg);
          msgByThread.set(threadId, list);
        }

        // Assign status to each HITL message by timeline index in the same thread.
        const nextMap: Record<string, string> = {};
        for (const [threadId, threadMsgs] of msgByThread.entries()) {
          const threadReqs = reqByThread.get(threadId) ?? [];
          for (let i = 0; i < threadMsgs.length; i++) {
            const req = threadReqs[i];
            if (!req) continue;
            if (req.status.toLowerCase() !== "pending") {
              nextMap[threadMsgs[i].id] = hitlStatusLabel(req.status);
            }
          }
        }

        if (!isMounted) return;
        setHitlDoneMap(nextMap);
      } catch {
        // Best-effort status sync only; keep existing UI if polling fails.
      }
    };

    syncStatuses();
    const timer = window.setInterval(syncStatuses, 4000);
    return () => {
      isMounted = false;
      window.clearInterval(timer);
    };
  }, [messages]);

  // Set default selected model when agents load (skip if user chose "No Agent" mode)
  useEffect(() => {
    if (agents.length > 0 && !selectedModelId && !noAgentMode) {
      setSelectedModelId(agents[0].id);
    }
  }, [agents, selectedModelId, noAgentMode]);

  // Auto-disable COT when user switches to a non-Gemini model (or leaves model mode).
  useEffect(() => {
    if (!cotReasoning) return;
    const current = aiModels.find((m) => m.id === selectedAiModel);
    const modelName = (current?.name || "").toLowerCase();
    const isGemini = /\b(gemini|google)\b/.test(modelName) && /\b(2\.5|3|3\.\d+)\b/.test(modelName);
    if (!noAgentMode || !isGemini) {
      setCotReasoning(false);
    }
  }, [selectedAiModel, noAgentMode, aiModels, cotReasoning]);

  // Auto-enable image mode when user selects an image-generation model (Nano Banana,
  // DALL-E, etc.), and auto-disable when switching to any other model.
  useEffect(() => {
    if (!noAgentMode || !selectedAiModel) {
      if (imageMode) setImageMode(false);
      return;
    }
    const current = aiModels.find((m) => m.id === selectedAiModel);
    const modelName = (current?.name || "").toLowerCase();
    const isImageModel = /nano[\s_-]?banana|dall[\s_-]?e|flash[\s_-]?image|image[\s_-]?gen/.test(modelName);
    if (isImageModel && !imageMode) {
      setImageMode(true);
      setIsCanvasEnabled(false);
    } else if (!isImageModel && imageMode) {
      setImageMode(false);
    }
  }, [selectedAiModel, noAgentMode, aiModels, imageMode]);

  // Update filteredAgents when agents load
  useEffect(() => {
    setFilteredAgents(agents);
  }, [agents]);

  // After a response finishes streaming in THIS session, return focus to the
  // textarea so the user can type the next question without clicking. We
  // gate on isSendingThisSession (not the global isSending) so a response
  // landing in another tab/session doesn't yank focus from a chat the user
  // is currently typing in.
  const wasSendingThisSessionRef = useRef(false);
  useEffect(() => {
    if (wasSendingThisSessionRef.current && !isSendingThisSession) {
      // Defer one tick so the textarea isn't disabled when we focus it.
      setTimeout(() => {
        if (!textareaRef.current?.disabled) {
          textareaRef.current?.focus();
        }
      }, 0);
    }
    wasSendingThisSessionRef.current = isSendingThisSession;
  }, [isSendingThisSession]);

  useEffect(() => {
    // Use instant scroll while streaming so it keeps up with fast tokens;
    // smooth scroll otherwise for a nicer UX.
    messagesEndRef.current?.scrollIntoView({
      behavior: isSending ? "auto" : "smooth",
    });
  }, [messages, isSending, streamingAgentName]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modelPickerRef.current && !modelPickerRef.current.contains(e.target as Node)) {
        setShowModelPicker(false);
      }
      if (!(e.target as Element)?.closest?.("[data-plus-menu]")) {
        setShowPlusMenu(false);
      }
      if (!(e.target as Element)?.closest?.("[data-apps-popover]")) {
        setShowAppsPopover(false);
      }
      if (!(e.target as Element)?.closest?.("[data-agents-popover]")) {
        setShowAgentsPopover(false);
      }
      if (aiModelPickerRef.current && !aiModelPickerRef.current.contains(e.target as Node)) {
        setShowAiModelPicker(false);
        setShowMoreModels(false);
      }
      // Close three-dot chat menu when clicking outside
      if (!(e.target as Element)?.closest?.("[data-chat-menu]")) {
        setChatMenuOpenId(null);
      }
      // Close per-message export menu when clicking outside
      if (!(e.target as Element)?.closest?.("[data-export-menu]")) {
        setExportMenuOpenId(null);
      }
      // Close per-message share menu when clicking outside
      if (!(e.target as Element)?.closest?.("[data-share-menu]")) {
        setShareMenuOpenId(null);
      }
      // Close suggestions when clicking outside input area
      if (!(e.target as Element)?.closest?.("textarea")) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  /* ------------------ HELPERS ------------------ */

  const timeNow = () =>
    new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const highlightMentions = (text: string) => {
    // Build a regex that matches any known @agent_name (including spaces)
    // so "@smart agent" is bolded as one unit, not just "@smart".
    if (agents.length === 0) return [text];
    const escaped = [...agents]
      .sort((a, b) => b.name.length - a.name.length)
      .map((a) => a.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp(`(@(?:${escaped.join("|")}))`, "gi");
    return text.split(pattern).map((part, i) =>
      part.startsWith("@") ? (
        <span key={i} className="font-semibold text-primary">
          {part}
        </span>
      ) : (
        part
      )
    );
  };

  const getAgentColor = (name?: string) => {
    const agent = agents.find((a) => a.name === name);
    return agent?.color || "#10a37f";
  };

  const versionBadge = (versionLabel: string) => (
    <span className="ml-2 inline-flex items-center rounded-full border border-border bg-muted px-1.5 py-0.5 text-xxs font-semibold uppercase leading-none text-muted-foreground">
      {versionLabel}
    </span>
  );

  const uatBadge = (environment: string) =>
    String(environment).toLowerCase() === "uat" ? (
      <span className="ml-1.5 inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-xxs font-semibold uppercase leading-none text-amber-700">
        UAT
      </span>
    ) : null;

  /* ------------------ HITL ACTION HANDLER ------------------ */

  const handleHitlAction = useCallback(
    async (msgId: string, threadId: string, action: string) => {
      if (hitlDoneMap[msgId] || hitlLoadingId) return;
      setHitlLoadingId(msgId);
      setHitlLoadingAction(action);
      try {
        const res = await api.post(`${getURL("HITL")}/${threadId}/resume`, {
          action,
          feedback: "",
          edited_value: "",
        });
        setHitlDoneMap((prev) => ({ ...prev, [msgId]: action }));

        const resData = res.data;

        if (resData?.status === "interrupted" && resData.interrupt_data) {
          // Another HITL node was hit downstream — show new approval message
          const newInterrupt = resData.interrupt_data;
          const question = newInterrupt.question || "Approval required";
          const newActions: string[] = newInterrupt.actions || [];
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              sender: "agent",
              agentName: prev.find((m) => m.id === msgId)?.agentName,
              content: question,
              timestamp: timeNow(),
              hitl: true,
              hitlActions: newActions,
              hitlThreadId: threadId,
            },
          ]);
        } else if (resData?.status === "completed") {
          // Graph finished — show only resumed AI output in orchestrator chat.
          setMessages((prev) => {
            const name = prev.find((m) => m.id === msgId)?.agentName;
            if (!resData.output_text) return prev;
            return [
              ...prev,
              {
                id: crypto.randomUUID(),
                sender: "agent" as const,
                agentName: name,
                content: resData.output_text,
                timestamp: timeNow(),
              },
            ];
          });
          // Refetch messages from DB so the persisted orch_conversation
          // response is available if user reloads or navigates away.
          refetchMessages();
        }
      } catch (_err) {
        // leave buttons enabled so user can retry
      } finally {
        setHitlLoadingId(null);
        setHitlLoadingAction(null);
      }
    },
    [hitlDoneMap, hitlLoadingId, timeNow, refetchMessages],
  );

  /* ------------------ INPUT HANDLING ------------------ */

  const handleInputChange = (value: string) => {
    setInput(value);
    // @-mentions only open the agent picker on a fresh chat. Once a model-mode
    // conversation is in progress, typing "@" must NOT switch the user to an
    // agent — they need to start a New Chat to change agent/model context.
    const inActiveModelChat = noAgentMode && messages.length > 0;
    const match = value.match(/@([\w\s().-]*)$/);
    if (match && agents.length > 0 && !inActiveModelChat) {
      const query = match[1].toLowerCase();
      setFilteredAgents(agents.filter((a) => a.name.toLowerCase().includes(query)));
      setShowMentions(true);
    } else {
      setShowMentions(false);
    }

    // Autocomplete suggestions — only in model mode, debounced fetch
    if (suggestionTimerRef.current) clearTimeout(suggestionTimerRef.current);
    // Cancel any in-flight suggestion fetch from a previous keystroke so its
    // delayed response can't re-show suggestions after the user has already sent.
    if (suggestionAbortRef.current) suggestionAbortRef.current.abort();
    setSelectedSuggestionIdx(-1);
    if (!noAgentMode || value.trim().length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    suggestionTimerRef.current = setTimeout(() => {
      const suggestUrl = `${getURL("ORCHESTRATOR")}/suggestions?q=${encodeURIComponent(value.trim())}`;
      const headers: Record<string, string> = {};
      const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
      if (tokenMatch?.[1]) headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;
      const controller = new AbortController();
      suggestionAbortRef.current = controller;
      fetch(suggestUrl, { headers, credentials: "include", signal: controller.signal })
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          // Guard against a stale response (aborted or a newer fetch started)
          if (controller.signal.aborted) return;
          const items: string[] = data?.suggestions || [];
          setSuggestions(items);
          setShowSuggestions(items.length > 0);
        })
        .catch((err) => {
          // Silent on abort; clear on other errors
          if (err?.name === "AbortError") return;
          setSuggestions([]);
          setShowSuggestions(false);
        });
    }, 400);
  };

  const handleSelectSuggestion = (text: string) => {
    setInput(text);
    setSuggestions([]);
    setShowSuggestions(false);
    setSelectedSuggestionIdx(-1);
    textareaRef.current?.focus();
  };

  const handleSelectAgent = (agent: Agent) => {
    const updated = input.replace(/@[\w\s().-]*$/, `@${agent.name} `);
    setInput(updated);
    setSelectedModelId(agent.id);
    // If the user was in model mode and just @-mentioned an agent, flip
    // them into agent mode so the model picker disables and the send
    // goes to the agent runtime.
    if (noAgentMode) setNoAgentMode(false);
    setShowMentions(false);
    textareaRef.current?.focus();
  };

  /* ------------------ SPEECH-TO-TEXT (MIC) ------------------ */

  const handleMicClick = useCallback(() => {
    // Stop listening
    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop();
      setIsListening(false);
      return;
    }

    // Start listening
    const SpeechRecognition = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition is not supported in this browser. Please use Chrome.");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognitionRef.current = recognition;
    setIsListening(true);

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setInput((prev) => (prev ? prev + " " + transcript : transcript));
      textareaRef.current?.focus();
    };

    recognition.onerror = () => {
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognition.start();
  }, [isListening]);

  /* ------------------ TEXT-TO-SPEECH (SPEAKER) ------------------ */

  const handleSpeak = useCallback((text: string) => {
    const synth = window.speechSynthesis;
    if (!synth) return;

    // If already speaking, stop
    if (synth.speaking) {
      synth.cancel();
      return;
    }

    // Strip markdown for cleaner speech
    const clean = text
      .replace(/!\[.*?\]\(.*?\)/g, "")          // remove images
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")  // links → text
      .replace(/[*_~`#>|\\-]{1,3}/g, "")        // remove markdown symbols
      .replace(/```[\s\S]*?```/g, "")            // remove code blocks
      .replace(/\n{2,}/g, ". ")                  // paragraphs → pause
      .replace(/\n/g, " ")
      .trim();

    if (!clean) return;

    const utterance = new SpeechSynthesisUtterance(clean);
    synth.speak(utterance);
  }, []);

  /* ------------------ EXPORT MESSAGE (DOCX / PDF / TEXT) ------------------ */

  // Strip raw HTML tags + decode common entities. LLM responses can embed
  // <h1>/<p>/<br/> directly; without this the markdown→HTML escape step would
  // render them as literal "<h1>" text in Word/PDF output.
  const stripHtml = useCallback((s: string): string => {
    return s
      .replace(/<\s*br\s*\/?\s*>/gi, "\n")
      .replace(/<\s*\/\s*(p|div|li|h[1-6]|tr)\s*>/gi, "\n")
      .replace(/<[^>]+>/g, "")
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/&quot;/gi, '"')
      .replace(/&#39;/gi, "'");
  }, []);

  // Markdown + HTML → clean plain text. Emojis preserved.
  const toPlainText = useCallback((input: string): string => {
    return stripHtml(input)
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 ($2)")
      .replace(/```[a-zA-Z0-9_-]*\n?([\s\S]*?)```/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/^\s{0,3}#{1,6}\s+/gm, "")
      .replace(/^\s*>\s?/gm, "")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/__([^_]+)__/g, "$1")
      .replace(/(^|\W)\*([^*\n]+)\*(\W|$)/g, "$1$2$3")
      .replace(/(^|\W)_([^_\n]+)_(\W|$)/g, "$1$2$3")
      .replace(/~~([^~]+)~~/g, "$1")
      .replace(/^\s*[-*+]\s+/gm, "• ")
      .replace(/^\s*\|.*\|\s*$/gm, (m) =>
        m.replace(/^\s*\|/, "").replace(/\|\s*$/, "").replace(/\s*\|\s*/g, "\t"))
      .replace(/^\s*[-:|\s]+\s*$/gm, "")
      .replace(/\r\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }, [stripHtml]);

  const renderMarkdownToHtml = useCallback((md: string): string => {
    // Lightweight markdown → HTML (headings, bold, italic, code, links, lists, line breaks)
    const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    let html = esc(stripHtml(md));
    html = html.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code}</code></pre>`);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/^###### (.*)$/gm, "<h6>$1</h6>");
    html = html.replace(/^##### (.*)$/gm, "<h5>$1</h5>");
    html = html.replace(/^#### (.*)$/gm, "<h4>$1</h4>");
    html = html.replace(/^### (.*)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.*)$/gm, "<h2>$1</h2>");
    html = html.replace(/^# (.*)$/gm, "<h1>$1</h1>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
    html = html.replace(/^\s*[-*+] (.*)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>");
    html = html.replace(/\n{2,}/g, "</p><p>");
    html = html.replace(/\n/g, "<br/>");
    return `<p>${html}</p>`;
  }, [stripHtml]);

  const handleExportDocx = useCallback((text: string) => {
    if (!text) return;
    const body = renderMarkdownToHtml(text);
    const html = `<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'><head><meta charset='utf-8'><title>Export</title><style>body{font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.5;}h1,h2,h3,h4{color:#1a1a1a;}pre{background:#f5f5f5;padding:8px;border-radius:4px;font-family:Consolas,monospace;white-space:pre-wrap;}code{background:#f5f5f5;padding:2px 4px;border-radius:3px;font-family:Consolas,monospace;}</style></head><body>${body}</body></html>`;
    const blob = new Blob(["\ufeff", html], { type: "application/msword" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `response-${Date.now()}.doc`;
    a.click();
    URL.revokeObjectURL(url);
  }, [renderMarkdownToHtml]);

  const handleExportPdf = useCallback((text: string) => {
    if (!text) return;
    const body = renderMarkdownToHtml(text);
    const printWindow = window.open("", "_blank", "width=800,height=600");
    if (!printWindow) return;
    printWindow.document.write(`<html><head><title>Export</title><style>body{font-family:Arial,sans-serif;font-size:12pt;line-height:1.6;max-width:800px;margin:40px auto;padding:0 20px;color:#1a1a1a;}h1,h2,h3,h4{color:#000;}pre{background:#f5f5f5;padding:10px;border-radius:4px;font-family:Consolas,monospace;white-space:pre-wrap;overflow-x:auto;}code{background:#f5f5f5;padding:2px 4px;border-radius:3px;font-family:Consolas,monospace;}a{color:#2563eb;}@media print{body{margin:0;}}</style></head><body>${body}<script>window.onload=function(){window.print();setTimeout(function(){window.close();},500);}</script></body></html>`);
    printWindow.document.close();
  }, [renderMarkdownToHtml]);

  const handleExportText = useCallback((text: string) => {
    if (!text) return;
    const clean = toPlainText(text);
    if (!clean) return;
    const blob = new Blob([clean], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `response-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }, [toPlainText]);

  const handleCopyMessage = useCallback(async (text: string, msgId: string) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback for non-secure contexts
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch {}
      document.body.removeChild(ta);
    }
    setCopiedMsgId(msgId);
    setTimeout(() => setCopiedMsgId((id) => (id === msgId ? null : id)), 1500);
  }, []);

  // Strip markdown for email body
  const stripMarkdownForEmail = useCallback((text: string): string => {
    return text
      .replace(/\*{1,3}(.*?)\*{1,3}/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/^\s*[-*+]\s+/gm, "• ")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/`+([^`]+)`+/g, "$1")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }, []);

  // Share on MS Teams
  const handleShareTeams = useCallback((text: string) => {
    if (!text) return;
    const encodedText = encodeURIComponent(text);
    const deepLink = `https://teams.microsoft.com/l/chat/0/0?users=&topicName=Topic&message=${encodedText}`;

    navigator.clipboard.writeText(text).then(() => {
      useAlertStore.getState().setSuccessData?.({ title: "Content copied to clipboard" });
      setTimeout(() => {
        useAlertStore.getState().setNoticeData?.({ title: "Opening Teams..." });
        setTimeout(() => {
          window.open(deepLink, "_blank");
        }, 300);
      }, 1000);
    }).catch((err) => {
      console.error("Error copying text: ", err);
    });
    setShareMenuOpenId(null);
  }, []);

  // Draft in Outlook
  const handleOutlookDraft = useCallback((text: string) => {
    if (!text) return;
    const body = stripMarkdownForEmail(text);
    const subject = "Shared from MiBuddy";
    try {
      const mailtoLink = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
      window.open(mailtoLink);
    } catch {
      navigator.clipboard.writeText(body).then(() => {
        useAlertStore.getState().setSuccessData?.({ title: "Email body copied to clipboard. Paste it into a new Outlook email." });
      });
    }
    setShareMenuOpenId(null);
  }, [stripMarkdownForEmail]);

  // Start inline editing a user message
  const handleStartEdit = useCallback((msgId: string, currentText: string) => {
    setEditingMsgId(msgId);
    setEditDraft(currentText);
  }, []);

  const handleCancelEdit = useCallback(() => {
    setEditingMsgId(null);
    setEditDraft("");
  }, []);

  // Save the edited prompt — MiBuddy-style in-place UPSERT.
  // Calls PUT /messages/{id}/edit which updates the user msg + next agent msg
  // in the DB (same IDs, new content). Frontend hides messages after the edit
  // pair in the UI (MiBuddy behavior).
  const handleSaveEdit = useCallback(async () => {
    const text = editDraft.trim();
    const msgIdBeingEdited = editingMsgId;
    setEditingMsgId(null);
    setEditDraft("");
    if (!text || !msgIdBeingEdited) return;

    // 1. Optimistic update: set user msg text to edited value, mark agent msg
    // as "thinking" (empty content) and truncate anything after the pair.
    // flushSync runs the updater synchronously so editingAgentMsgId is
    // populated before the setStreamingMsgId call below — without flushSync,
    // React would defer the updater to render time and the closure variable
    // would still be null.
    let editingAgentMsgId: string | null = null;
    let priorWasImage = false;
    flushSync(() => {
      setMessages((prev) => {
        const userIdx = prev.findIndex((m) => m.id === msgIdBeingEdited);
        if (userIdx === -1) return prev;
        // Find the next agent message AFTER this user msg
        let agentIdx = -1;
        for (let i = userIdx + 1; i < prev.length; i++) {
          if (prev[i].sender === "agent") {
            agentIdx = i;
            break;
          }
        }
        const truncateAt = agentIdx === -1 ? userIdx + 1 : agentIdx + 1;
        const updated = [...prev.slice(0, truncateAt)];
        // Update user message content
        updated[userIdx] = { ...updated[userIdx], content: text };
        // Reset agent response to empty to show "Thinking..." state (if it exists)
        if (agentIdx !== -1) {
          editingAgentMsgId = updated[agentIdx].id;
          // Detect whether this was an image-gen reply so the ThinkingIndicator
          // can show the image skeleton (square placeholder + "Generating image"
          // phrases) during the regenerate, instead of the generic text bars.
          priorWasImage = !!updated[agentIdx].content?.includes("![");
          updated[agentIdx] = {
            ...updated[agentIdx],
            content: "",
            reasoningContent: undefined,
            contentBlocks: undefined,
          };
        }
        return updated;
      });
    });
    // Scope the ThinkingIndicator to this exact agent bubble. Without this,
    // the render-loop's `msg.id === streamingMsgId` guard would fail and the
    // empty bubble would render the "Message empty." fallback.
    if (editingAgentMsgId) setStreamingMsgId(editingAgentMsgId);
    // Pre-seed routedMode so the indicator matches the prior reply's modality.
    // For image edits this surfaces the image skeleton immediately, instead
    // of the generic text-bar one until (or if) the backend re-emits a
    // routing event. For non-image edits, clear stale routedMode from prior
    // turns so we fall back to the generic skeleton.
    setRoutedMode(priorWasImage ? "image_gen" : null);

    // 2. Call PUT endpoint to do the in-place update on the backend
    try {
      // Mark THIS session as sending so isSendingThisSession (and therefore
      // ThinkingIndicator) becomes true while the edit's PUT is in flight.
      // Without sendingSessionId, the optimistically-cleared agent bubble
      // would render "Message empty." via MarkdownField's empty fallback.
      setIsSending(true);
      setSendingSessionId(currentSessionId);
      // routedMode was pre-seeded above based on the prior reply's modality;
      // don't overwrite it here.
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
      if (tokenMatch?.[1]) headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;
      const res = await fetch(
        `${getURL("ORCHESTRATOR")}/messages/${msgIdBeingEdited}/edit`,
        {
          method: "PUT",
          headers,
          credentials: "include",
          body: JSON.stringify({
            edited_text: text,
            enable_reasoning: cotReasoning,
            // image_mode is intentionally NOT sent — backend forces
            // image_mode=false on edits so intent classification drives the
            // mode, regardless of the original message's routing.
            model_id: (noAgentMode && selectedAiModel) ? selectedAiModel : undefined,
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // MiBuddy-only carve-out: in model-direct mode (No Agent), the
      // polling-refetch merge's length heuristic can clobber the just-
      // applied edit response with a stale read when new and old content
      // are similar lengths — happens both for image URL edits (identical
      // format) and for text edits where the regenerated essay/answer is
      // close in length to the original.
      // Tag the regenerated agent message + (for image edits) the user
      // message so the merge keeps our authoritative local content.
      // Agent-mode edits are NOT tagged — that flow has its own behavior
      // we don't want to touch.
      if (noAgentMode) {
        const editedAt = Date.now();
        if (data?.agent_message?.id) {
          recentlyEditedRef.current.set(String(data.agent_message.id), editedAt);
        }
        if (priorWasImage && data?.user_message?.id) {
          recentlyEditedRef.current.set(String(data.user_message.id), editedAt);
        }
      }
      // 3. Apply server-returned content for both updated messages
      setMessages((prev) =>
        prev.map((m) => {
          if (data.user_message && m.id === data.user_message.id) {
            return { ...m, content: data.user_message.text };
          }
          if (data.agent_message && m.id === data.agent_message.id) {
            // Filter content_blocks the same way the initial-fetch path does
            // (line ~281) — only keep tool-call blocks; the rest is noise.
            const rawBlocks = (data.agent_message.content_blocks ?? []) as any[];
            const toolBlocks = rawBlocks.filter((block: any) =>
              block?.contents?.some((c: any) =>
                ["tool_use", "tool_result", "media", "code"].includes(c?.type),
              ),
            );
            return {
              ...m,
              content: data.agent_message.text,
              reasoningContent: data.agent_message.reasoning_content || undefined,
              // Sync server-side block state — image-gen edits keep this
              // empty, but mode-flip edits (e.g. agent → model_direct) need
              // the old tool cards cleared. Without this, the optimistic
              // `undefined` would be the only thing keeping stale tool
              // cards from re-appearing on the next React reconciliation.
              contentBlocks: toolBlocks.length > 0 ? toolBlocks : undefined,
              // Sync files so newly-attached images on a regenerated reply
              // (or cleared files when the mode flips away from image_gen)
              // are reflected without a page reload.
              files: data.agent_message.files && data.agent_message.files.length > 0
                ? data.agent_message.files
                : undefined,
              agentName: data.agent_message.sender_name,
            };
          }
          return m;
        }),
      );
      // 4. Sync the top dropdown to whichever model actually answered the
      // edit — backend may have re-routed to a specialist (Nano Banana for
      // image, web search model for news, etc.). Updating selectedAiModel
      // also causes the existing auto-toggle useEffect to flip imageMode
      // off when the new model isn't an image-gen model, which clears the
      // stale "Image" chip at the bottom of the input.
      const newModelId: string | undefined = data?.agent_message?.model_id;
      if (newModelId && noAgentMode && newModelId !== selectedAiModel) {
        setSelectedAiModel(newModelId);
      }
    } catch (err) {
      console.error("[EditSave] Failed:", err);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgIdBeingEdited ? { ...m, content: text } : m,
        ),
      );
      useAlertStore.getState().setErrorData?.({
        title: "Failed to edit message",
        list: [String((err as Error).message || err)],
      });
    } finally {
      setIsSending(false);
      setSendingSessionId(null);
      setRoutedMode(null);
      setStreamingMsgId(null);
    }
  }, [editDraft, editingMsgId, cotReasoning, imageMode]);

  /* ------------------ SEND MESSAGE ------------------ */

  const handleSend = useCallback(async (overrideText?: string) => {
    const hasFiles = uploadFiles.some((f) => f.path && !f.loading && !f.error);
    // Block send if any file is still uploading — otherwise it gets silently
    // dropped (the previous behavior caused agents to reply "no document
    // attached" because the user clicked send before upload completed).
    const hasPendingUploads = uploadFiles.some((f) => f.loading);
    const hasFailedUploads = uploadFiles.some((f) => f.error);
    if (hasPendingUploads) {
      useAlertStore.getState().setErrorData?.({
        title: "Upload still in progress",
        list: ["Wait for the file upload to finish before sending, or remove the file."],
      });
      return;
    }
    if (hasFailedUploads && !hasFiles) {
      useAlertStore.getState().setErrorData?.({
        title: "Upload failed",
        list: ["The file failed to upload. Remove it and try again."],
      });
      return;
    }
    // Accept an optional override text (used by the edit-and-send flow where
    // React state flush timing is tricky). Falls back to the live `input` state.
    const effectiveInput = (typeof overrideText === "string" ? overrideText : input);
    // Only block re-sending in THIS session — let the user send in a different
    // session even while another is streaming (each gets its own SSE stream).
    const sendingThisSession = isSending && sendingSessionId === currentSessionId;
    if (!canInteract || (!effectiveInput.trim() && !hasFiles) || sendingThisSession || hasPendingHitl) return;
    // New turn starts: clear prior routed label override.
    setHeaderModelOverride(null);
    // Hide autocomplete suggestions the moment the user submits, AND cancel any
    // in-flight suggestion fetch so its delayed response can't re-show the dropdown.
    setSuggestions([]);
    setShowSuggestions(false);
    if (suggestionTimerRef.current) clearTimeout(suggestionTimerRef.current);
    if (suggestionAbortRef.current) suggestionAbortRef.current.abort();
    if (isSharedReadOnly) {
      useAlertStore.getState().setErrorData?.({
        title: "This is a shared read-only conversation",
        list: ["Start a new chat to continue with your own account."],
      });
      return;
    }

    // Outlook intent handling moved to the backend: the MiBuddy-ported
    // intent classifier now returns "outlook_query" for email/calendar
    // queries, and the orchestrator's chat-stream handler invokes
    // outlook_agent_node which renders the reply. No frontend precheck
    // needed — normal send path handles everything.

    // Detect explicit @mention — auto-select the agent if user typed @agent_name
    // Sort by name length descending so "rag agent_new" matches before "rag agent".
    const explicitAgent = [...agents]
      .sort((a, b) => b.name.length - a.name.length)
      .find((a) => effectiveInput.includes(`@${a.name}`));

    // If user @mentioned an agent, switch out of noAgentMode and select it
    if (explicitAgent) {
      if (noAgentMode) setNoAgentMode(false);
      if (explicitAgent.id !== selectedModelId) setSelectedModelId(explicitAgent.id);
    }

    // Block send when no agent or model is selected (and no @mention detected)
    if (!explicitAgent) {
      const needsAgent = !noAgentMode && !selectedModelId;
      const needsModel = noAgentMode && !selectedAiModel;
      if (needsAgent || needsModel || (!noAgentMode && agents.length === 0)) {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            sender: "user" as const,
            content: effectiveInput,
            timestamp: timeNow(),
          },
          {
            id: crypto.randomUUID(),
            sender: "agent" as const,
            content: t("Please select an agent or model first to start chatting."),
            timestamp: timeNow(),
          },
        ]);
        setInput("");
        return;
      }
    }

    // Collect uploaded file paths (pure read — clearing the state is deferred
    // until we're sure we're actually sending, so the user doesn't lose their
    // attachments if the message turns out to be empty after sanitisation).
    const filePaths = uploadFiles
      .filter((f) => f.path && !f.loading && !f.error)
      .map((f) => f.path!);

    const fallbackAgent = selectedAgent || agents[0];

    // Target agent: explicit @mention wins, otherwise use sticky (selectedModel)
    const targetAgent = explicitAgent || fallbackAgent;

    // Strip the @agent_name mention so the agent only receives the actual question
    const escapedName = explicitAgent
      ? explicitAgent.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      : "";
    const cleanedInput = explicitAgent
      ? effectiveInput.replace(new RegExp(`@${escapedName}\\s*`, "g"), "").trim()
      : effectiveInput.trim();

    // After stripping the @mention and trimming, the actual question may be
    // empty (e.g. user typed just "@agent_name " with no real prompt). Don't
    // ship a blank message to the backend — bail and let the user finish.
    if (!cleanedInput && filePaths.length === 0) {
      return;
    }

    // From here we're committed to sending — clear the upload previews now.
    setUploadFiles([]);

    // Agent message placeholder — created upfront so "Thinking..." shows inside the bubble
    const agentMsgId = crypto.randomUUID();
    setStreamingMsgId(agentMsgId);

    // Determine display name for the responding entity
    const responderName = (noAgentMode && selectedAiModel)
      ? (aiModels.find((m) => m.id === selectedAiModel)?.name || "AI Model")
      : targetAgent.name;

    // Add both user message AND agent "thinking" placeholder.
    // flushSync commits the DOM update synchronously, then we await a
    // double-rAF to guarantee the browser has actually painted the
    // "Thinking..." indicator before the network request begins.
    const userMessage: Message = {
      id: crypto.randomUUID(),
      sender: "user",
      content: effectiveInput,
      timestamp: timeNow(),
      files: filePaths.length > 0 ? filePaths : undefined,
      canvasEnabled: isCanvasEnabled || undefined,
    };
    flushSync(() => {
      setMessages((prev) => [
        ...prev,
        userMessage,
        {
          id: agentMsgId,
          sender: "agent" as const,
          agentName: responderName,
          content: "",  // empty = "Thinking..." state
          timestamp: timeNow(),
          canvasEnabled: isCanvasEnabled || undefined,
          // Mirror the backend's sender="model" vs "agent" distinction so UI
          // affordances (e.g. Teams/Outlook share menu) are hidden immediately
          // for model replies instead of flashing until the post-send refetch.
          isAgentResponse: !noAgentMode,
        },
      ]);
      setInput("");
      setShowMentions(false);
      setIsSending(true);
      setSendingSessionId(currentSessionId);
      setStreamingAgentName(responderName);
      setRoutedMode(null);
    });

    // Wait for the browser to actually paint the thinking state.
    // Double-rAF: first rAF fires before paint, second fires after paint.
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );

    let accumulated = "";
    let accumulatedReasoning = "";
    let rafHandle: number | null = null;
    let pendingContent: string | null = null;
    let hitlPauseReceived = false;
    let receivedToken = false;
    let latestAgentAddMessageText = "";

    // Flush the latest accumulated content to React state.
    // Called inside a rAF so we update at most once per frame (~60fps),
    // keeping the UI responsive while still showing progressive tokens.
    const flushToReact = () => {
      rafHandle = null;
      if (pendingContent === null) return;
      const content = pendingContent;
      const reasoning = accumulatedReasoning || undefined;
      pendingContent = null;
      flushSync(() => {
        setStreamingAgentName("");
        setMessages((prev) =>
          prev.map((m) =>
            m.id === agentMsgId ? { ...m, content, reasoningContent: reasoning } : m,
          ),
        );
      });
    };

    // Helper: update the agent message bubble content.
    // Tokens arrive very rapidly; we accumulate them and schedule
    // a single React update per animation frame to stay smooth.
    const updateAgentMsg = (content: string, immediate = false) => {
      accumulated = content;
      if (immediate) {
        // For final/error updates, flush synchronously
        if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null; }
        pendingContent = null;
        const reasoning = accumulatedReasoning || undefined;
        console.warn("[Orch][flush] Setting msg with reasoningContent length:", reasoning?.length || 0, "content length:", content.length);
        flushSync(() => {
          setStreamingAgentName("");
          setMessages((prev) =>
            prev.map((m) =>
              m.id === agentMsgId ? { ...m, content, reasoningContent: reasoning } : m,
            ),
          );
        });
        return;
      }
      pendingContent = content;
      if (rafHandle === null) {
        rafHandle = requestAnimationFrame(flushToReact);
      }
    };

    // Build request body: @agent mode sends agent_id, model mode sends model_id.
    const requestBody: any = {
      session_id: currentSessionId,
      input_value: cleanedInput,
    };

    if (explicitAgent || !noAgentMode) {
      // Agent mode: send agent details
      requestBody.agent_id = targetAgent.agent_id;
      requestBody.deployment_id = targetAgent.deploy_id;
      requestBody.version_number = targetAgent.version_number;
      requestBody.env = targetAgent.environment || "uat";
    } else if (noAgentMode && selectedAiModel) {
      // Model mode: send model_id (UUID from registry)
      requestBody.model_id = selectedAiModel;
    }

    // Send COT reasoning preference
    if (cotReasoning) {
      requestBody.enable_reasoning = true;
    }

    // Image mode: explicit flag — backend skips intent classification and routes to image generation
    if (imageMode) {
      requestBody.image_mode = true;
    }

    // Canvas mode (MiBuddy-style): tells the backend the user wants a
    // draft-style response. The outlook_agent also auto-enables this
    // flag for compose_email / reply_email intents and returns
    // `auto_canvas: true` — handled in onData below.
    if (isCanvasEnabled) {
      requestBody.canvas_enabled = true;
    }

    if (filePaths.length > 0) {
      requestBody.files = filePaths;
    }
    console.log("[OrchestratorChat] Request body:", JSON.stringify(requestBody), "| filePaths:", filePaths, "| uploadFiles:", uploadFiles.map(f => ({id: f.id, path: f.path, loading: f.loading, error: f.error})));

    const buildController = new AbortController();

    try {
      await performStreamingRequest({
        method: "POST",
        url: `${getURL("ORCHESTRATOR")}/chat/stream`,
        body: requestBody,
        buildController,
        onData: async (event: any) => {
          const eventType: string = event?.event;
          const data: any = event?.data;

          // MiBuddy-style instant model switch: backend emits a "routing" event
          // IMMEDIATELY after deciding the destination (mode/model), before the
          // actual response is generated. Update the dropdown AND the currently-
          // streaming message's agent name right away so the user sees the switch
          // without waiting for the full response.
          if (eventType === "routing") {
            console.warn("[Orch][routing event]", data);
            const routedMode = String(data?.mode || "").toLowerCase();
            // Drive the ThinkingIndicator's phrase set + skeleton shape.
            // Falsy mode → leave as null so indicator keeps the neutral
            // pre-routing label instead of falling into the "chat" branch.
            setRoutedMode(routedMode || null);
            if (noAgentMode && routedMode === "web_search" && data?.routed_model_name) {
              const nameStr = String(data.routed_model_name);
              const byName = aiModels.find(
                (m) => m.name.toLowerCase() === nameStr.toLowerCase(),
              );
              setHeaderModelOverride({
                name: byName?.name || nameStr,
                icon: byName?.icon,
              });
            } else {
              setHeaderModelOverride(null);
            }
            let routedDisplayName: string | null = null;
            // For image_gen routing, only update the message label (agentName) —
            // do NOT switch the dropdown. Promoting selectedAiModel to nano-banana
            // would auto-enable imageMode (see useEffect at ~line 1542) and force
            // every followup through the image_mode fast-path on the backend, even
            // for plain text questions. Users who want successive image generations
            // can pick the image model explicitly via the dropdown or + → Create image.
            const skipDropdownSwitch = routedMode === "image_gen";
            if (noAgentMode && data?.routed_model_id) {
              const routedId = String(data.routed_model_id);
              const match = aiModels.find((m) => m.id === routedId);
              if (match) {
                routedDisplayName = match.name;
                if (!skipDropdownSwitch && routedId !== selectedAiModel) setSelectedAiModel(routedId);
              }
            }
            if (!routedDisplayName && data?.routed_model_name) {
              const nameStr = String(data.routed_model_name);
              routedDisplayName = nameStr;
              if (noAgentMode && !skipDropdownSwitch) {
                const byName = aiModels.find(
                  (m) => m.name.toLowerCase() === nameStr.toLowerCase(),
                );
                if (byName && byName.id !== selectedAiModel) setSelectedAiModel(byName.id);
              }
            }
            // Update the "Thinking..." placeholder message's agentName so the
            // sender label flips to the routed model immediately.
            if (routedDisplayName) {
              setStreamingAgentName(routedDisplayName);
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId ? { ...m, agentName: routedDisplayName || m.agentName } : m,
                ),
              );
            }
            return true;
          }

          const isHitlEvent =
            eventType === "add_message" &&
            (
              !!data?.properties?.hitl ||
              inferHitlFromText(String(data?.text || data?.message || ""))
            );

          if (isHitlEvent) {
            // HITL pause event — update agent message with HITL metadata
            // so the UI renders approval action buttons.
            hitlPauseReceived = true;
            const actions: string[] = Array.isArray(data?.properties?.actions)
              ? data.properties.actions
              : extractHitlActions(String(data?.text || data?.message || ""));
            const threadId: string = data?.properties?.thread_id ?? currentSessionId ?? "";
            const hitlText: string = data.text || data.message || "";
            const isDeployedRun: boolean = data?.properties?.is_deployed_run ?? false;
            flushSync(() => {
              setStreamingAgentName("");
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId
                    ? {
                        ...m,
                        content: hitlText,
                        hitl: true,
                        hitlActions: actions,
                        hitlThreadId: threadId,
                        hitlIsDeployed: isDeployedRun,
                      }
                    : m,
                ),
              );
            });
            // Don't return false — let the stream continue to consume
            // remaining events (end_vertex, end).
          } else if (eventType === "add_message" && data?.content_blocks?.length) {
            // Only show content_blocks that contain actual tool calls.
            // Each flow node (Chat Input, Worker Node, Chat Output) sends its
            // own add_message event; pipeline nodes only carry plain text steps
            // which would appear as duplicate Input/Output entries. Filtering
            // to tool_use blocks means we only show meaningful agent reasoning.
            const toolBlocks = data.content_blocks.filter((block: any) =>
              block.contents?.some((c: any) => c.type === "tool_use"),
            );
            if (toolBlocks.length > 0) {
              flushSync(() => {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === agentMsgId
                      ? {
                          ...m,
                          // Replace (not append) — each add_message is a
                          // progressive update of the same Worker Node message
                          // (Accessing → Executed), not a new block.
                          contentBlocks: toolBlocks,
                          blocksState: "partial",
                        }
                      : m,
                  ),
                );
              });
            }
          } else if (eventType === "add_message" && (data?.text || data?.message) && !hitlPauseReceived) {
            // Keep add_message text as a fallback, but don't immediately overwrite
            // the thinking bubble. Some graphs emit user/input-node add_message
            // events before AI tokens; rendering those here causes echo + no stream UX.
            const sender = String(data?.sender || data?.sender_name || "").toLowerCase();
            const isUserMessage = sender.includes("user");
            const addMessageText = String(data.text || data.message || "");
            if (!isUserMessage && addMessageText.trim()) {
              latestAgentAddMessageText = addMessageText;
            }
          } else if (eventType === "token" && data?.chunk) {
            // Progressive streaming — append each token chunk (throttled)
            receivedToken = true;
            if (data.type === "reasoning") {
              // CoT reasoning chunk — accumulate separately
              accumulatedReasoning += data.chunk;
              updateAgentMsg(accumulated); // trigger re-render to show reasoning
            } else {
              accumulated += data.chunk;
              updateAgentMsg(accumulated);
            }
          } else if (eventType === "error") {
            // Tag the bubble as category="error" so it renders with the red
            // alert styling immediately — without this, the red treatment
            // would only kick in after a reload (when the persisted DB row
            // is re-fetched with category="error"). Matches the agent row
            // written by `_execute_orchestrator_job`'s error handler.
            const errorText = data?.text || "An error occurred";
            if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null; }
            pendingContent = null;
            flushSync(() => {
              setStreamingAgentName("");
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId
                    ? { ...m, content: errorText, category: "error" }
                    : m,
                ),
              );
            });
            return false;
          } else if (eventType === "end") {
            console.warn("[Orch][end event] reasoning_content length:", (data?.reasoning_content || "").length, "accumulated len:", accumulatedReasoning.length);
            console.warn("[Orch][end event] reasoning preview:", (data?.reasoning_content || "").slice(0, 200));
            // Capture reasoning from end event if provided
            if (data?.reasoning_content) {
              accumulatedReasoning = data.reasoning_content;
            }
            // MiBuddy canvas parity: backend auto-enabled canvas for the
            // user (typically compose_email / reply_email from the
            // Outlook agent). Flip the UI toggle on for future messages
            // AND retroactively mark the current streaming message so
            // its rendering switches to CanvasEditor.
            if (data?.auto_canvas) {
              setIsCanvasEnabled(true);
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId ? { ...m, canvasEnabled: true } : m,
                ),
              );
            }
            // Auto-switch the model dropdown to the model that ACTUALLY produced
            // the response. Happens when smart router or intent classifier routed
            // to a different model than the one the user selected (e.g. user picked
            // "MiBuddy AI" → router picked "gpt-5.1-chat" → dropdown updates to
            // "gpt-5.1-chat" so the user knows subsequent messages will use it).
            //
            // Exception: don't promote to image-gen models. Doing so would auto-
            // enable imageMode and force all followup messages through the
            // image_mode fast-path on the backend, even plain-text queries.
            const isImageModelName = (n: string) =>
              /nano[\s_-]?banana|dall[\s_-]?e|flash[\s_-]?image|image[\s_-]?gen/i.test(n);
            if (noAgentMode && data?.routed_model_id) {
              const routedId = data.routed_model_id;
              if (routedId !== selectedAiModel) {
                const match = aiModels.find((m) => m.id === routedId);
                if (match && !isImageModelName(match.name)) setSelectedAiModel(routedId);
              }
            } else if (noAgentMode && data?.routed_model_name) {
              // Fallback: match by display name if no id is present
              const nameStr = String(data.routed_model_name);
              const byName = aiModels.find(
                (m) => m.name.toLowerCase() === nameStr.toLowerCase(),
              );
              if (byName && byName.id !== selectedAiModel && !isImageModelName(byName.name)) {
                setSelectedAiModel(byName.id);
              }
            }

            // Previously: after a successful image generation, this block
            // forcibly reverted the dropdown to MiBuddy AI, which made the
            // imageMode useEffect at index.tsx:~1741 clear the red Image chip.
            // That hurt the common case of successive image edits — the user
            // would have to re-select Nano Banana every turn. We now leave
            // the dropdown alone: when the user explicitly picks an image
            // model (via the dropdown or + → Create image), they stay on
            // that model and the chip persists until they manually click
            // the X on the chip or pick a different model.
            // End event carries the final complete text — flush immediately.
            // BUT: if we received a HITL pause, do NOT overwrite the HITL
            // message with agent_text — the action buttons must stay visible.
            if (data?.agent_text && !hitlPauseReceived) {
              updateAgentMsg(data.agent_text, true);
              // Re-bind the frontend placeholder's temporary UUID to the
              // real DB id the backend just persisted, so that any later
              // refetch-driven replacement can still match by id (needed
              // for preserving canvas flag, reactions, etc.).
              if (data?.message_id) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === agentMsgId
                      ? { ...m, id: String(data.message_id) }
                      : m,
                  ),
                );
              }
            } else if (!hitlPauseReceived && !receivedToken && latestAgentAddMessageText.trim()) {
              // Fallback for non-token flows where response text came only via
              // add_message and end has no agent_text payload.
              updateAgentMsg(latestAgentAddMessageText, true);
            }
            // Mark content blocks as fully finished
            if (!hitlPauseReceived) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId && m.contentBlocks?.length
                    ? { ...m, blocksState: "complete" }
                    : m,
                ),
              );
            }
            refetchSessions();
            // Force a fast message sync for existing sessions so local streamed
            // content is not replaced by stale polled data.
            if (effectiveSessionId) {
              refetchMessages();
            }
            return false;
          }
          return true;
        },
        onError: (statusCode) => {
          updateAgentMsg(`Error: server returned ${statusCode}`, true);
        },
        onNetworkError: (error) => {
          if (error.name !== "AbortError") {
            updateAgentMsg("Sorry, something went wrong. Please try again.", true);
          }
        },
      });
    } catch {
      if (!accumulated) {
        updateAgentMsg("Sorry, something went wrong. Please try again.", true);
      }
    } finally {
      // Flush any remaining buffered content and clean up
      if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null; }
      if (pendingContent !== null) {
        const finalContent = pendingContent;
        pendingContent = null;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === agentMsgId ? { ...m, content: finalContent } : m,
          ),
        );
      } else if (!hitlPauseReceived && !receivedToken && latestAgentAddMessageText.trim()) {
        // Defensive fallback if stream closes before we get a parsable end event.
        setMessages((prev) =>
          prev.map((m) =>
            m.id === agentMsgId ? { ...m, content: latestAgentAddMessageText } : m,
          ),
        );
      }
      setIsSending(false);
      setSendingSessionId(null);
      setStreamingAgentName("");
      setStreamingMsgId(null);
      setRoutedMode(null);
    }
  }, [canInteract, input, isSending, sendingSessionId, hasPendingHitl, agents, selectedAgent, selectedModelId, noAgentMode, selectedAiModel, currentSessionId, effectiveSessionId, refetchSessions, refetchMessages, imageMode, cotReasoning, uploadFiles, isCanvasEnabled, isSharedReadOnly]);

  // Keep the ref updated so handleSaveEdit can call the latest handleSend
  useEffect(() => {
    handleSendRef.current = handleSend;
  }, [handleSend]);

  /* ------------------ SESSION MANAGEMENT ------------------ */

  const handleNewChat = () => {
    setCurrentSessionId(crypto.randomUUID());
    setActiveSessionId(null);
    setMessages([]);
    setSelectedModelId("");
    setNoAgentMode(true);
    setHeaderModelOverride(null);
    sessionSelectionSyncRef.current = null;
    setShowImageGallery(false);
    setIsSharedReadOnly(false);
    setIsCanvasEnabled(false);
    // Snap the model dropdown back to the default (MiBuddy AI). Otherwise a
    // prior turn that auto-switched to an image model (e.g. Nano Banana) would
    // leak into the new chat. Same priority order as the page-load default.
    if (aiModels.length > 0) {
      const mibuddy = aiModels.find((m) => /mibuddy[\s_-]?ai/i.test(m.name));
      const defaultModel = mibuddy || aiModels.find((m) => m.is_default) || aiModels[0];
      if (defaultModel) setSelectedAiModel(defaultModel.id);
    }
  };

  const handleSelectSession = (sessionId: string) => {
    setActiveSessionId(sessionId);
    setShowImageGallery(false);
    setIsSharedReadOnly(false);
  };

  /* ──────────── Session rename / share (MiBuddy-parity helpers) ────────────
   * Rename is persisted server-side in `orch_conversation.session_title`
   * (migration 95791a21c989). The sessions-list API returns this value and
   * the sidebar display picks it up. `titleOverrides` provides optimistic
   * UI feedback before the API round-trip finishes.
   * Share copies a link to the current session (same URL + ?session=<id>).
   */
  const startRenameSession = (sessionId: string) => {
    const fromApi = (apiSessions || []).find((s) => s.session_id === sessionId);
    const current =
      titleOverrides[sessionId] ??
      fromApi?.session_title ??
      fromApi?.preview ??
      "";
    setRenameDraft(current);
    setRenamingSessionId(sessionId);
  };

  const confirmRenameSession = async () => {
    if (!renamingSessionId) return;
    const title = renameDraft.trim() || null;
    const sessionId = renamingSessionId;
    // Optimistic UI update
    setTitleOverrides((prev) => ({ ...prev, [sessionId]: title }));
    setRenamingSessionId(null);
    setRenameDraft("");
    try {
      await api.post(
        `${getURL("ORCHESTRATOR")}/sessions/${sessionId}/title`,
        { title },
        { withCredentials: true },
      );
      // Refresh sessions so the authoritative title lands in apiSessions
      refetchSessions();
    } catch (err) {
      console.error("Rename session failed:", err);
      // Roll back the override so the old name reappears
      setTitleOverrides((prev) => {
        const { [sessionId]: _, ...rest } = prev;
        return rest;
      });
      useAlertStore.getState().setErrorData({
        title: t("Failed to rename chat"),
        list: [String((err as Error)?.message || err)],
      });
    }
  };

  const cancelRenameSession = () => {
    setRenamingSessionId(null);
    setRenameDraft("");
  };

  const handleShareSession = async (sessionId: string) => {
    // MiBuddy-parity share: the link opens the orchestrator page with
    // `?session=<id>` selected. If the recipient is already signed in,
    // the session loads immediately. If not, ProtectedRoute bounces them
    // to login and returns to the same URL afterwards.
    const url = `${window.location.origin}/orchestrator-chat?session=${encodeURIComponent(sessionId)}`;
    try {
      await navigator.clipboard.writeText(url);
      useAlertStore.getState().setSuccessData?.({
        title: t("Share link copied to clipboard"),
      });
    } catch {
      window.prompt(t("Copy this share link:"), url);
    }
  };

  /** Title to render in the sidebar for a given chat row.
   *  Priority: optimistic override > server-persisted title > preview >
   *  agent name > "New conversation" fallback. */
  const sessionDisplayName = (chat: { session_id: string; preview?: string | null; active_agent_name?: string | null; session_title?: string | null }) => {
    const override = titleOverrides[chat.session_id];
    return (
      (override !== undefined ? override : null) ||
      chat.session_title ||
      chat.preview ||
      chat.active_agent_name ||
      t("New conversation")
    );
  };

  const handleDeleteSession = (sessionId: string) => {
    deleteSession(
      { session_id: sessionId },
      {
        onSuccess: () => {
          if (currentSessionId === sessionId) {
            handleNewChat();
          }
          refetchSessions();
        },
      },
    );
  };

  const handleArchiveSession = async (sessionId: string, isArchived: boolean) => {
    try {
      await api.post(`${getURL("ORCHESTRATOR")}/sessions/${sessionId}/archive`, {
        is_archived: isArchived,
      });
      if (currentSessionId === sessionId && isArchived) {
        handleNewChat();
      }
      refetchSessions();
    } catch (err) {
      console.error("Failed to archive session:", err);
    }
  };

  /* ---- group chat history by date ---- */
  const activeSessions = useMemo(
    () => (apiSessions || []).filter((s) => !s.is_archived).slice(0, 20),
    [apiSessions],
  );
  const archivedSessions = useMemo(
    () => (apiSessions || []).filter((s) => s.is_archived).slice(0, 20),
    [apiSessions],
  );

  // Filter sessions by search query (matches preview text)
  const filteredActiveSessions = useMemo(() => {
    const q = sidebarSearchQuery.trim().toLowerCase();
    if (!q) return activeSessions;
    return activeSessions.filter(
      (s) =>
        (s.preview || "").toLowerCase().includes(q) ||
        (s.active_agent_name || "").toLowerCase().includes(q),
    );
  }, [activeSessions, sidebarSearchQuery]);

  const filteredArchivedSessions = useMemo(() => {
    const q = sidebarSearchQuery.trim().toLowerCase();
    if (!q) return archivedSessions;
    return archivedSessions.filter(
      (s) =>
        (s.preview || "").toLowerCase().includes(q) ||
        (s.active_agent_name || "").toLowerCase().includes(q),
    );
  }, [archivedSessions, sidebarSearchQuery]);

  const grouped = useMemo(
    () => groupSessionsByDate(filteredActiveSessions, t),
    [filteredActiveSessions, t],
  );
  const groupedArchived = useMemo(
    () => groupSessionsByDate(filteredArchivedSessions, t),
    [filteredArchivedSessions, t],
  );
  const visibleAgents = useMemo(() => agents.slice(0, 5), [agents]);
  const hiddenAgentsCount = Math.max(0, agents.length - visibleAgents.length);

  /* ------------------ RENDER ------------------ */

  return (
    <div className="relative flex h-screen w-full overflow-hidden bg-background text-foreground">
      {/* ================ SIDEBAR ================ */}
      <div
        className={`relative z-30 flex flex-col overflow-visible border-r border-border bg-muted transition-all duration-200 ${
          sidebarOpen ? "w-64 min-w-[16rem]" : "w-14 min-w-[3.5rem]"
        }`}
      >
        {/* Second sidebar collapse toggle (fixed seam anchor) */}
        <div className="absolute right-[-12px] top-[56px] z-[260] -translate-y-1/2">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="pointer-events-auto flex h-6 w-6 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-700 shadow-md hover:bg-gray-100"
            title={sidebarOpen ? t("Collapse sidebar") : t("Expand sidebar")}
          >
            {sidebarOpen ? (
              <FaChevronLeft className="h-3.5 w-3.5" />
            ) : (
              <FaChevronRight className="h-3.5 w-3.5" />
            )}
          </button>
        </div>

        {/* Sidebar Header */}
        <div className="flex h-12 items-center px-3" />

        {/* ---- Single scrollable region containing nav + apps + info + agents.
              Without this, expanding "Chat history" pushed the Applications
              and Agents sections off-screen because the sidebar itself is
              overflow-hidden. */}
        <div
          className="flex min-h-0 flex-1 flex-col overflow-y-auto scroll-smooth"
          style={{ scrollbarWidth: "thin" }}
        >
        {/* ---- Addon: Sidebar Navigation Items ---- */}
        <div className="flex flex-col gap-0.5 px-2 pb-2">
          {/* New chat */}
          <button
            onClick={() => {
              setShowNotebookLM(false);
              setShowImageGallery(false);
              handleNewChat();
            }}
            className={`flex w-full items-center rounded-lg py-2 text-sm text-foreground hover:bg-accent ${sidebarOpen ? "gap-3 px-3" : "justify-center px-0"}`}
            title={t("New chat")}
          >
            <SidebarMaskIcon src={miNewChatIcon} />
            {sidebarOpen && <span>{t("New chat")}</span>}
          </button>

          {/* Search chats */}
          <button
            onClick={() => {
              setShowSearchInput(true);
              setSidebarSearchQuery("");
            }}
            className={`flex w-full items-center rounded-lg py-2 text-sm text-foreground hover:bg-accent ${sidebarOpen ? "gap-3 px-3" : "justify-center px-0"}`}
            title={t("Search chats")}
          >
            <SidebarMaskIcon src={miSearchIcon} />
            {sidebarOpen && <span>{t("Search chats")}</span>}
          </button>

          {/* Search overlay moved to top-level so backdrop covers sidebar */}

          {/* Image — toggles gallery view in main area */}
          <button
            onClick={() => {
              setShowImageGallery(!showImageGallery);
              setShowNotebookLM(false);
            }}
            className={`flex w-full items-center rounded-lg py-2 text-sm text-foreground hover:bg-accent ${showImageGallery ? "bg-accent" : ""} ${sidebarOpen ? "gap-3 px-3" : "justify-center px-0"}`}
            title={t("Image")}
          >
            <SidebarMaskIcon src={imageLibraryLogo} />
            {sidebarOpen && <span>{t("Image")}</span>}
          </button>

          {/* Chat history (collapsible) — contains all conversations */}
          <button
            onClick={() => { if (sidebarOpen) setShowChatHistoryExpand(!showChatHistoryExpand); else setSidebarOpen(true); }}
            className={`flex w-full items-center rounded-lg py-2 text-sm text-foreground hover:bg-accent ${sidebarOpen ? "gap-3 px-3" : "justify-center px-0"}`}
            title={t("Chat history")}
          >
            <SidebarMaskIcon src={miChatHistoryIcon} />
            {sidebarOpen && <span className="flex-1 text-left">{t("Chat history")}</span>}
            {sidebarOpen && <ChevronRight size={14} className={`text-muted-foreground transition-transform ${showChatHistoryExpand ? "rotate-90" : ""}`} />}
          </button>
          {sidebarOpen && showChatHistoryExpand && (
            <div className="ml-4 max-h-[9rem] overflow-y-auto border-l border-border pl-1">
              {Object.entries(grouped).map(([date, chats]) => (
                <div key={date} className="mb-2">
                  <div className="px-3 pb-1 pt-2 text-xxs font-semibold uppercase tracking-wide text-muted-foreground">
                    {date}
                  </div>
                  {chats.map((chat) => (
                    <div
                      key={chat.session_id}
                      className="group relative flex items-center"
                    >
                      {renamingSessionId === chat.session_id ? (
                        /* Inline rename input (MiBuddy-parity) */
                        <div className="flex min-w-0 flex-1 items-center gap-1 rounded-lg bg-accent px-2 py-1">
                          <input
                            autoFocus
                            value={renameDraft}
                            onChange={(e) => setRenameDraft(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") confirmRenameSession();
                              if (e.key === "Escape") cancelRenameSession();
                            }}
                            className="min-w-0 flex-1 rounded border border-border bg-background px-2 py-1 text-sm text-foreground outline-none"
                          />
                          <button
                            onClick={(e) => { e.stopPropagation(); confirmRenameSession(); }}
                            className="rounded p-1 text-green-600 hover:bg-background"
                            title={t("Save")}
                          >
                            <Check size={14} />
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); cancelRenameSession(); }}
                            className="rounded p-1 text-muted-foreground hover:bg-background"
                            title={t("Cancel")}
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => handleSelectSession(chat.session_id)}
                          className={`flex min-w-0 flex-1 items-center gap-2 truncate rounded-lg px-3 py-2 pr-8 text-left text-sm text-foreground hover:bg-accent ${
                            currentSessionId === chat.session_id ? "bg-accent" : ""
                          }`}
                        >
                          <MessageSquare size={14} className="shrink-0 opacity-50" />
                          <span className="truncate">{sessionDisplayName(chat)}</span>
                        </button>
                      )}
                      {/* Three-dot menu button — visible on hover */}
                      {renamingSessionId !== chat.session_id && (
                        <button
                          data-chat-menu
                          onClick={(e) => {
                            e.stopPropagation();
                            if (chatMenuOpenId === chat.session_id) {
                              setChatMenuOpenId(null);
                            } else {
                              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                              setChatMenuPos({ top: rect.bottom + 4, left: rect.right - 160 });
                              setChatMenuContext("active");
                              setChatMenuOpenId(chat.session_id);
                            }
                          }}
                          className="invisible absolute right-1 shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground group-hover:visible"
                          title={t("Options")}
                        >
                          <MoreVertical size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* Archive Chat (collapsible) */}
          <button
            onClick={() => { if (sidebarOpen) setShowArchiveChatExpand(!showArchiveChatExpand); else setSidebarOpen(true); }}
            className={`flex w-full items-center rounded-lg py-2 text-sm text-foreground hover:bg-accent ${sidebarOpen ? "gap-3 px-3" : "justify-center px-0"}`}
            title={t("Archive Chat")}
          >
            <SidebarMaskIcon src={miArchiveIcon} />
            {sidebarOpen && <span className="flex-1 text-left">{t("Archive Chat")}</span>}
            {sidebarOpen && <ChevronRight size={14} className={`text-muted-foreground transition-transform ${showArchiveChatExpand ? "rotate-90" : ""}`} />}
          </button>
          {sidebarOpen && showArchiveChatExpand && (
            <div className="ml-4 max-h-[9rem] overflow-y-auto border-l border-border pl-1">
              {archivedSessions.length === 0 ? (
                <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                  {t("No archived chats")}
                </div>
              ) : (
                Object.entries(groupedArchived).map(([date, chats]) => (
                  <div key={date} className="mb-2">
                    <div className="px-3 pb-1 pt-2 text-xxs font-semibold uppercase tracking-wide text-muted-foreground">
                      {date}
                    </div>
                    {chats.map((chat) => (
                      <div
                        key={chat.session_id}
                        className="group relative flex items-center"
                      >
                        <button
                          onClick={() => handleSelectSession(chat.session_id)}
                          className={`flex min-w-0 flex-1 items-center gap-2 truncate rounded-lg px-3 py-2 pr-8 text-left text-sm text-muted-foreground hover:bg-accent ${
                            currentSessionId === chat.session_id ? "bg-accent" : ""
                          }`}
                        >
                          <Archive size={14} className="shrink-0 opacity-50" />
                          <span className="truncate">{sessionDisplayName(chat)}</span>
                        </button>
                        {/* Three-dot menu — Unarchive + Delete */}
                        <button
                          data-chat-menu
                          onClick={(e) => {
                            e.stopPropagation();
                            if (chatMenuOpenId === chat.session_id) {
                              setChatMenuOpenId(null);
                            } else {
                              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                              setChatMenuPos({ top: rect.bottom + 4, left: rect.right - 160 });
                              setChatMenuContext("archived");
                              setChatMenuOpenId(chat.session_id);
                            }
                          }}
                          className="invisible absolute right-1 shrink-0 rounded p-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground group-hover:visible"
                          title={t("Options")}
                        >
                          <MoreVertical size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* ---- Addon: Applications Section ---- */}
        <div className="border-t border-border px-2 pb-2 pt-2">
          {sidebarOpen ? (
            <>
              <div className="px-3 pb-1 text-xxs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("Applications")}
              </div>
              <div
                className="flex max-h-[11.25rem] flex-col gap-0.5 overflow-y-auto scroll-smooth"
                style={{ scrollbarWidth: "thin" }}
              >
                {/* <button
                  onClick={() => window.open("https://translator.ai.motherson.com", "_blank")}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                >
                  <img src={translatorLogo} alt="" className="h-4 w-4 shrink-0 object-contain" />
                  <span>{t("AI Translator")}</span>
                </button>
                <button
                  onClick={() => window.open("https://genai.motherson.com/do33", "_blank")}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                >
                  <img src={do33Logo} alt="" className="h-4 w-4 shrink-0 object-contain" />
                  <span>{t("DO33")}</span>
                </button>
                <button
                  onClick={() => {
                    setShowNotebookLM(true);
                    setShowImageGallery(false);
                  }}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent ${showNotebookLM ? "bg-accent" : ""}`}
                >
                  <img src={notebookLMLogo} alt="" className="h-4 w-4 shrink-0 object-contain" />
                  <span>{t("NotebookLM")}</span>
                </button> */}
                <button
                                  onClick={() => window.open("https://mmnext.services.ailifebot.com/", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("MMNext")}
                                >
                                  <img src={MMNextIcon} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("MMNext")}</span>
                                </button>
                                <button
                                  onClick={() => window.open("https://talentai.motherson.com/", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("Talent AI")}
                                >
                                  <img src={talentaiIcon} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("Talent AI")}</span>
                                </button>
                                <button
                                  onClick={() => window.open("https://genai.motherson.com/do33", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("DO33")}
                                >
                                  <img src={do33Logo} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("DO33")}</span>
                                </button>
                                <button
                                  onClick={() => window.open("https://translator.ai.motherson.com", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("AI Motherson Translator")}
                                >
                                  <img src={translatorLogo} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("AI Motherson Translator")}</span>
                                </button>
                                <button
                                  onClick={() => window.open("https://genai.motherson.com/capex-forecasting", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("Capex Forecasting")}
                                >
                                  <img src={capexIcon} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("Capex Forecasting")}</span>
                                </button>
                                <button
                                  onClick={() => window.open("https://genai.motherson.com/yachiyo", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("Yachio Bot")}
                                >
                                  <img src={yachioIcon} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("Yachio Bot")}</span>
                                </button>
                                <button
                                  onClick={() => window.open("https://genai.motherson.com/kip", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("KIP Bot")}
                                >
                                  <img src={KIPIcon} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("KIP Bot")}</span>
                                </button>
                                <button
                                  onClick={() => window.open("https://spendanalytics-hmcqbkd4f6etbseu.centralindia-01.azurewebsites.net/", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("Spend Analytics")}
                                >
                                  <img src={spendanalyticsIcon} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("Spend Analytics")}</span>
                                </button>
                                {/* <button
                                  onClick={() => window.open("https://mibuddy.motherson.com/", "_blank")}
                                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent"
                                  title={t("MiBuddy")}
                                >
                                  <img src={translatorLogo} alt="" className="h-4 w-4 shrink-0 object-contain" />
                                  <span>{t("MiBuddy")}</span>
                                </button> */}
                              </div>
            </>
          ) : (
            <div data-apps-popover className="relative flex justify-center">
              <button
                onClick={(e) => {
                  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  setAppsPopoverPos({ top: rect.top, left: rect.right + 8 });
                  setShowAppsPopover(!showAppsPopover);
                }}
                className="flex items-center justify-center rounded-lg p-2 text-muted-foreground hover:bg-accent hover:text-foreground"
                title={t("Applications")}
              >
                <LayoutGrid size={18} />
              </button>
            </div>
          )}
        </div>

        {/* ---- Addon: Information & Help (wired same as MiBuddy) ----
              Information → opens the MiBuddy user-manual PDF in a new tab.
              Help → opens the user's mail client pre-populated to the
              MiBuddy support distribution lists. */}
        <div className="border-t border-border px-2 pb-3 pt-2">
          <button
            onClick={() =>
              window.open(
                "https://mibuddystorageaccount.blob.core.windows.net/genieusermanual/MIBuddyusermanual.pdf",
                "_blank",
              )
            }
            className={`flex w-full items-center rounded-lg py-2 text-sm text-foreground hover:bg-accent ${sidebarOpen ? "gap-3 px-3" : "justify-center px-0"}`}
            title={t("Information")}
          >
            <SidebarMaskIcon src={miInformationIcon} />
            {sidebarOpen && <span>{t("Information")}</span>}
          </button>
          <button
            onClick={() => {
              const subject = encodeURIComponent(
                "MiBuddy : Please detail the support required",
              );
              window.location.href = `mailto:support.mtsl@motherson.com,MiBuddy.Feedback@motherson.com?subject=${subject}`;
            }}
            className={`flex w-full items-center rounded-lg py-2 text-sm text-foreground hover:bg-accent ${sidebarOpen ? "gap-3 px-3" : "justify-center px-0"}`}
            title={t("Help")}
          >
            <SidebarMaskIcon src={miHelpIcon} />
            {sidebarOpen && <span>{t("Help")}</span>}
          </button>
        </div>
        </div>
      </div>

      {/* ---- Apps popover (collapsed sidebar) ---- */}
      {showAppsPopover && (
        <div
          data-apps-popover
          className="fixed z-[100] min-w-[200px] rounded-xl border border-border bg-popover p-1.5 shadow-lg"
          style={{ top: appsPopoverPos.top, left: appsPopoverPos.left }}
        >
          {/* <button
            onClick={() => { setShowAppsPopover(false); window.open("https://translator.motherson.com", "_blank"); }}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
          >
            <img src={translatorLogo} alt="" className="h-5 w-5 shrink-0 object-contain" />
            <span>{t("AI Translator")}</span>
          </button>
          <button
            onClick={() => { setShowAppsPopover(false); window.open("https://genai.motherson.com/do33", "_blank"); }}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
          >
            <img src={do33Logo} alt="" className="h-5 w-5 shrink-0 object-contain" />
            <span>{t("DO33")}</span>
          </button>
          <button
            onClick={() => { setShowAppsPopover(false); setShowNotebookLM(true); setShowImageGallery(false); }}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent ${showNotebookLM ? "bg-accent" : ""}`}
          >
            <img src={notebookLMLogo} alt="" className="h-5 w-5 shrink-0 object-contain" />
            <span>{t("NotebookLM")}</span>
          </button> */}

          <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://mmnext.services.ailifebot.com/", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={MMNextIcon} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("MMNext")}</span>
                    </button>
                    <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://talentai.motherson.com/", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={talentaiIcon} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("Talent AI")}</span>
                    </button>
                    <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://genai.motherson.com/do33", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={translatorLogo} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("DO33")}</span>
                    </button>
                    <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://translator.ai.motherson.com/", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={translatorLogo} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("AI Motherson Translator")}</span>
                    </button>
                    <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://genai.motherson.com/capex-forecasting", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={capexIcon} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("Capex Forecasting")}</span>
                    </button>
                    <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://genai.motherson.com/yachiyo", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={yachioIcon} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("Yachio Bot")}</span>
                    </button>
                    <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://genai.motherson.com/kip", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={KIPIcon} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("KIP Bot")}</span>
                    </button>
                    <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://spendanalytics-hmcqbkd4f6etbseu.centralindia-01.azurewebsites.net/", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={spendanalyticsIcon} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("Spend Analytics")}</span>
                    </button>
                    {/* <button
                      onClick={() => { setShowAppsPopover(false); window.open("https://mibuddy.motherson.com/", "_blank"); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                    >
                      <img src={translatorLogo} alt="" className="h-5 w-5 shrink-0 object-contain" />
                      <span>{t("MiBuddy")}</span>
                    </button> */}

        </div>
      )}
      {showAgentsPopover && (
        <div
          data-agents-popover
          className="fixed z-[100] min-w-[220px] rounded-xl border border-border bg-popover p-1.5 shadow-lg"
          style={{ top: agentsPopoverPos.top, left: agentsPopoverPos.left }}
        >
          <div className="px-2 py-1 text-xxs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("Agents")}
          </div>
          <div className="max-h-[260px] overflow-y-auto">
            {agents.map((agent) => (
              <button
                key={agent.id}
                onClick={() => {
                  setSelectedModelId(agent.id);
                  setShowModelPicker(false);
                  setShowAgentsPopover(false);
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-foreground hover:bg-accent ${
                  selectedModelId === agent.id ? "bg-accent" : ""
                }`}
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: agent.online ? agent.color : undefined }}
                />
                <span className="min-w-0 truncate">{agent.name}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ---- Addon: Plus menu dropdown — rendered fixed to escape input overflow ---- */}
      {showPlusMenu && (
        <div
          data-plus-menu
          className="fixed z-[100] min-w-[220px] rounded-xl border border-border bg-popover p-1 shadow-lg"
          style={{ bottom: plusMenuPos.bottom, left: plusMenuPos.left }}
        >
          <button
            onClick={() => {
              setShowPlusMenu(false);
              setImageMode(true);
              setIsCanvasEnabled(false);
              // Auto-switch to the image-generation model (Nano Banana / DALL-E / etc.)
              const imageModel = aiModels.find((m) =>
                /nano[\s_-]?banana|dall[\s_-]?e|flash[\s_-]?image|image[\s_-]?gen/i.test(m.name)
              );
              if (imageModel) setSelectedAiModel(imageModel.id);
            }}
            className="flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
          >
            <div className="flex items-center gap-3">
              <Paintbrush size={16} className={imageMode ? "text-red-500" : "text-muted-foreground"} />
              <span>{t("Create image")}</span>
            </div>
            {imageMode && (
              <span className="text-xs font-medium text-red-500">ON</span>
            )}
          </button>
          <button
            onClick={() => {
              setShowPlusMenu(false);
              const next = !isCanvasEnabled;
              setIsCanvasEnabled(next);
              // Canvas + image generation are mutually exclusive in MiBuddy.
              if (next) setImageMode(false);
            }}
            className="flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
          >
            <div className="flex items-center gap-3">
              <BookOpen size={16} className={isCanvasEnabled ? "text-red-500" : "text-muted-foreground"} />
              <span>{t("Canvas")}</span>
            </div>
            {isCanvasEnabled && (
              <span className="text-xs font-medium text-red-500">ON</span>
            )}
          </button>
          <button
            onClick={() => {
              setShowPlusMenu(false);
              fileInputRef.current?.click();
            }}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
          >
            <Upload size={16} className="text-muted-foreground" />
            <span>{t("Upload from this device")}</span>
          </button>
          <button
            onClick={() => {
              setShowPlusMenu(false);
              setSpPickerOpen(true);
            }}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
          >
            <FileUp size={16} className="text-green-500" />
            <span>{t("Upload from SharePoint")}</span>
          </button>
          
          <div className="my-1 h-px bg-border" />
          {(() => {
            const selectedModel = noAgentMode && selectedAiModel ? aiModels.find((m) => m.id === selectedAiModel) : null;
            // Restrict COT to Gemini models only (the only provider with reliable
            // visible thinking support in our current setup). Matches names like
            // "Gemini 3 Pro", "gemini-3.1-pro-preview", "Google 3.1 Pro", "Gemini 2.5 Flash".
            const isGeminiName = (n: string) => {
              const ln = (n || "").toLowerCase();
              return /\b(gemini|google)\b/.test(ln) && /\b(2\.5|3|3\.\d+)\b/.test(ln);
            };
            const isGeminiModel = isGeminiName(selectedModel?.name || "");
            // Find the best Gemini reasoning model in the registry — Option A:
            // Pro + is_default → Pro → default → first available.
            const geminiCandidates = aiModels.filter((m) => isGeminiName(m.name));
            const bestGemini =
              geminiCandidates.find((m) => /\bpro\b/i.test(m.name) && m.is_default) ||
              geminiCandidates.find((m) => /\bpro\b/i.test(m.name)) ||
              geminiCandidates.find((m) => m.is_default) ||
              geminiCandidates[0] ||
              null;
            // Disabled only if not in model mode, or no Gemini model exists
            // in the registry to switch to. Otherwise the button is always
            // clickable: toggling on auto-switches to the best Gemini, mirror-
            // ing how "Create image" auto-switches to an image-gen model.
            const cotDisabled = !noAgentMode || !bestGemini;
            const willAutoSwitch = !cotDisabled && !cotReasoning && !isGeminiModel && !!bestGemini;
            return (
          <button
            onClick={() => {
              if (cotDisabled) return;
              const turningOn = !cotReasoning;
              if (turningOn && !isGeminiModel && bestGemini) {
                // Switch to a reasoning-capable Gemini first, then enable COT.
                setSelectedAiModel(bestGemini.id);
                setNoAgentMode(true);
              }
              setCotReasoning(turningOn);
            }}
            className={`flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm ${
              cotDisabled ? "cursor-not-allowed text-muted-foreground/50" : "text-foreground hover:bg-accent"
            }`}
            title={
              cotDisabled
                ? (!noAgentMode
                    ? "COT reasoning is only available in model (No Agent) mode"
                    : "No Gemini reasoning model is registered")
                : willAutoSwitch && bestGemini
                  ? `Will switch to ${bestGemini.name} (Gemini reasoning)`
                  : undefined
            }
          >
            <div className="flex items-center gap-3">
              <Lightbulb size={16} className={cotDisabled ? "text-muted-foreground/30" : "text-muted-foreground"} />
              <span>{t("COT reasoning")}</span>
              {willAutoSwitch && bestGemini && (
                <span className="text-xxs text-muted-foreground/70">
                  ({t("switches to")} {bestGemini.name})
                </span>
              )}
              {cotDisabled && noAgentMode && (
                <span className="text-xxs text-muted-foreground/50">({t("no Gemini model")})</span>
              )}
            </div>
            <div
              className={`relative h-5 w-9 rounded-full transition-colors ${
                cotDisabled ? "bg-muted-foreground/10" : cotReasoning ? "bg-primary" : "bg-muted-foreground/30"
              }`}
            >
              <div
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${cotReasoning ? "translate-x-4" : "translate-x-0.5"}`}
              />
            </div>
          </button>
            );
          })()}

          {/* ---- Outlook Connector toggle (orchestrator) ---- */}
          <button
            onClick={async () => {
              setShowPlusMenu(false);
              if (isOutlookOrchConnected) {
                await disconnectOutlookOrch();
                setIsOutlookOrchConnected(false);
              } else {
                setShowOutlookOrch(true);
              }
            }}
            className="flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
          >
            <div className="flex items-center gap-3">
              <span
                className="inline-flex h-4 w-4 items-center justify-center rounded-sm text-[10px] font-bold text-white"
                style={{ background: "#0078D4" }}
              >
                O
              </span>
              <span>{t("Outlook Connector")}</span>
            </div>
            <div
              className={`relative h-5 w-9 rounded-full transition-colors ${
                isOutlookOrchConnected ? "bg-red-500" : "bg-muted-foreground/30"
              }`}
            >
              <div
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                  isOutlookOrchConnected ? "translate-x-4" : "translate-x-0.5"
                }`}
              />
            </div>
          </button>
        </div>
      )}

      {/* Three-dot chat menu dropdown — rendered fixed to escape scroll
          container. Context-aware:
            - "active"   → Rename, Share, Archive, Delete (MiBuddy parity)
            - "archived" → Unarchive, Delete                               */}
      {chatMenuOpenId && (
        <div
          data-chat-menu
          className="fixed z-[100] min-w-[160px] rounded-lg border border-border bg-popover p-1 shadow-lg"
          style={{ top: chatMenuPos.top, left: chatMenuPos.left }}
        >
          {chatMenuContext === "active" && (
            <>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  const sessionId = chatMenuOpenId;
                  setChatMenuOpenId(null);
                  startRenameSession(sessionId);
                }}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-foreground hover:bg-accent"
              >
                <Pencil size={14} />
                <span>{t("Rename")}</span>
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  const sessionId = chatMenuOpenId;
                  setChatMenuOpenId(null);
                  handleShareSession(sessionId);
                }}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-foreground hover:bg-accent"
              >
                <Upload size={14} />
                <span>{t("Share")}</span>
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setChatMenuOpenId(null);
                  handleArchiveSession(chatMenuOpenId!, true);
                }}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-foreground hover:bg-accent"
              >
                <Archive size={14} />
                <span>{t("Archive")}</span>
              </button>
            </>
          )}
          {chatMenuContext === "archived" && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setChatMenuOpenId(null);
                handleArchiveSession(chatMenuOpenId!, false);
              }}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-foreground hover:bg-accent"
            >
              <ArrowLeft size={14} />
              <span>{t("Unarchive")}</span>
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              const sessionId = chatMenuOpenId;
              setChatMenuOpenId(null);
              handleDeleteSession(sessionId);
            }}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-red-500 hover:bg-accent"
          >
            <Trash2 size={14} />
            <span>{t("Delete")}</span>
          </button>
        </div>
      )}

      {/* ================ SEARCH OVERLAY ================ */}
      {showSearchInput && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 pt-[10vh]" onClick={() => { setShowSearchInput(false); setSidebarSearchQuery(""); }}>
          <div
            className="w-full max-w-lg rounded-xl bg-background shadow-2xl border border-border"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Search input header */}
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <input
                type="text"
                value={sidebarSearchQuery}
                onChange={(e) => setSidebarSearchQuery(e.target.value)}
                placeholder={t("Search chats...")}
                className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
                autoFocus
              />
              <button
                onClick={() => { setShowSearchInput(false); setSidebarSearchQuery(""); }}
                className="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X size={16} />
              </button>
            </div>

            {/* New chat button */}
            <button
              onClick={() => { setShowSearchInput(false); setSidebarSearchQuery(""); handleNewChat(); }}
              className="flex w-full items-center gap-3 px-4 py-3 text-sm font-medium text-foreground hover:bg-accent"
            >
              <SquarePen size={16} className="shrink-0 text-muted-foreground" />
              <span>{t("New-chat")}</span>
            </button>

            {/* Recent sessions list */}
            <div className="max-h-[50vh] overflow-y-auto px-2 pb-3" style={{ scrollbarWidth: "thin" }}>
              {Object.entries(grouped).length === 0 && sidebarSearchQuery.trim() ? (
                <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                  {t("No matching chats")}
                </div>
              ) : (
                Object.entries(grouped).map(([date, chats]) => (
                  <div key={date} className="mb-1">
                    <div className="px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {date}
                    </div>
                    {chats.map((chat) => (
                      <button
                        key={chat.session_id}
                        onClick={() => { setShowSearchInput(false); setSidebarSearchQuery(""); handleSelectSession(chat.session_id); }}
                        className={`flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-accent ${
                          currentSessionId === chat.session_id ? "bg-accent" : ""
                        }`}
                      >
                        <MessageSquare size={14} className="mt-0.5 shrink-0 opacity-50" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium text-foreground">
                            {chat.active_agent_name || t("Chat")}
                            {chat.active_agent_name ? ` - ${chat.active_agent_name}` : ""}
                          </div>
                          <div className="mt-0.5 truncate text-xs text-muted-foreground">
                            {sessionDisplayName(chat)}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* ================ MAIN AREA ================ */}
      {showNotebookLM ? (
        /* ---- NotebookLM panel (inline, like image gallery) ---- */
        <NotebookLMPanel onBack={() => setShowNotebookLM(false)} />
      ) : showImageGallery ? (
        /* ---- Image Gallery View ---- */
        <ImageGalleryView
          onBack={() => setShowImageGallery(false)}
          selectedImage={selectedGalleryImage}
          onSelectImage={setSelectedGalleryImage}
          onClosePreview={() => setSelectedGalleryImage(null)}
        />
      ) : (
      <div className="relative flex flex-1 flex-col">
        {/* Top Bar */}
        <div className="flex h-[52px] shrink-0 items-center gap-2 border-b border-border px-4">
          {/* Agent selector */}
          <div ref={modelPickerRef} className="relative">
            <button
              onClick={() => setShowModelPicker(!showModelPicker)}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[15px] font-semibold text-foreground hover:bg-accent"
            >
              <Sparkles size={16} style={{ color: noAgentMode ? "#6b7280" : (selectedAgent?.color || "#10a37f") }} />
              {noAgentMode ? (
                <span className="text-muted-foreground">{t("No Agent")}</span>
              ) : selectedAgent ? (
                <span className="flex items-center">
                  <span>{selectedAgent.name}</span>
                  {versionBadge(selectedAgent.version_label)}
                  {uatBadge(selectedAgent.environment)}
                </span>
              ) : (
                t("Select Agent")
              )}
              <ChevronDown size={14} className="opacity-50" />
            </button>

            {showModelPicker && (
              <div className="absolute left-0 top-full z-50 mt-1 flex max-h-[60vh] min-w-[240px] flex-col overflow-hidden rounded-xl border border-border bg-popover p-1 shadow-lg">
                {/* No Agent option */}
                <button
                  onClick={() => {
                    setNoAgentMode(true);
                    setSelectedModelId("");
                    setShowModelPicker(false);
                    if (!selectedAiModel) {
                      const defaultModel = aiModels.find((m) => m.is_default) || aiModels[0];
                      if (defaultModel) setSelectedAiModel(defaultModel.id);
                    }
                  }}
                  className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent ${
                    noAgentMode ? "bg-accent" : ""
                  }`}
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted">
                    <User size={14} className="text-muted-foreground" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{t("No Agent")}</div>
                    <div className="text-xs text-muted-foreground">{t("Chat with AI model directly")}</div>
                  </div>
                  {noAgentMode && (
                    <span className="ml-auto text-primary"><Check size={14} /></span>
                  )}
                </button>
                <div className="my-1 h-px bg-border" />
                {/* Scrollable agent list — keeps "No Agent" pinned above */}
                <div className="flex-1 overflow-y-auto">
                  {agents.map((agent) => (
                    <button
                      key={agent.id}
                      onClick={() => {
                        setSelectedModelId(agent.id);
                        setNoAgentMode(false);
                        setSelectedAiModel(null);
                        setShowModelPicker(false);
                      }}
                      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent ${
                        !noAgentMode && selectedModelId === agent.id ? "bg-accent" : ""
                      }`}
                    >
                      <span
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                        style={{ background: agent.color }}
                      >
                        <Sparkles size={14} color="white" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center font-medium">
                          <span>{agent.name}</span>
                          {versionBadge(agent.version_label)}
                          {uatBadge(agent.environment)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {agent.description}
                        </div>
                      </div>
                      {!noAgentMode && selectedModelId === agent.id && (
                        <span className="ml-auto text-primary">
                          <Check size={14} />
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ---- Addon: AI Model selector (beside agent dropdown) ----
               Disabled whenever an agent is selected; agents carry their
               own models, so a top-level model pick is meaningless then.
               When Model mode is active, users can still type @ in the
               input to switch to an agent — `handleSend` already detects
               that and swaps modes accordingly. */}
          <div ref={aiModelPickerRef} className="relative">
            {(() => {
              const selectedModelOption =
                noAgentMode && selectedAiModel
                  ? aiModels.find((m) => m.id === selectedAiModel)
                  : null;
              const headerDisplayName =
                noAgentMode
                  ? (headerModelOverride?.name || selectedModelOption?.name || t("Choose AI Model"))
                  : t("Choose AI Model");
              const headerDisplayIcon =
                noAgentMode
                  ? (headerModelOverride?.icon || selectedModelOption?.icon)
                  : undefined;
              return (
            <button
              disabled={!noAgentMode}
              onClick={() => {
                if (!noAgentMode) return;
                setShowAiModelPicker(!showAiModelPicker);
                setShowMoreModels(false);
              }}
              title={
                !noAgentMode
                  ? t("An agent is selected — model picker disabled.")
                  : undefined
              }
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[15px] font-semibold hover:bg-accent ${
                !noAgentMode
                  ? "cursor-not-allowed opacity-40 hover:bg-transparent"
                  : noAgentMode
                    ? "text-foreground"
                    : "text-muted-foreground"
              }`}
            >
              {headerDisplayIcon ? (
                <img
                  src={resolveDisplayIcon(headerDisplayIcon, isDark)}
                  alt=""
                  className="h-4 w-4 shrink-0 object-contain"
                />
              ) : (
                <span className="h-3 w-3 shrink-0 rounded-full bg-muted-foreground/40" />
              )}
              <span>{headerDisplayName}</span>
              <ChevronDown size={14} className="opacity-50" />
            </button>
              );
            })()}

            {showAiModelPicker && (
              <div className="absolute left-0 top-full z-50 mt-1 min-w-[220px] rounded-xl border border-border bg-popover p-1 shadow-lg">
                <div className="px-3 pb-1 pt-2 text-xxs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("Choose Your AI Model")}
                </div>
                {aiModels.filter((m) => m.group === "main").map((model) => (
                  <button
                    key={model.id}
                    disabled={!noAgentMode}
                    onClick={() => {
                      if (!noAgentMode) return;
                      setSelectedAiModel(model.id);
                      setHeaderModelOverride(null);
                      setShowAiModelPicker(false);
                    }}
                    className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm ${
                      !noAgentMode
                        ? "cursor-not-allowed text-muted-foreground/50"
                        : selectedAiModel === model.id
                          ? "bg-accent text-foreground"
                          : "text-foreground hover:bg-accent"
                    }`}
                  >
                    <img
                      src={resolveDisplayIcon(model.icon, isDark)}
                      alt=""
                      className={`h-5 w-5 shrink-0 object-contain ${!noAgentMode ? "opacity-30" : ""}`}
                    />
                    <span className="flex-1">{model.name}</span>
                    {noAgentMode && selectedAiModel === model.id && (
                      <Check size={14} className="text-primary" />
                    )}
                  </button>
                ))}
                {/* More submenu — only show if there are "more" models */}
                {aiModels.some((m) => m.group === "more") && <div className="relative">
                  <button
                    disabled={!noAgentMode}
                    onClick={() => {
                      if (!noAgentMode) return;
                      setShowMoreModels(!showMoreModels);
                    }}
                    className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm ${
                      !noAgentMode
                        ? "cursor-not-allowed text-muted-foreground/50"
                        : "text-foreground hover:bg-accent"
                    }`}
                  >
                    <MoreVertical size={14} className={!noAgentMode ? "opacity-30" : ""} />
                    <span className="flex-1">{t("More")}</span>
                    <ChevronRight size={14} className="opacity-50" />
                  </button>
                  {showMoreModels && noAgentMode && (
                    <div className="absolute left-full top-0 z-50 ml-1 min-w-[180px] rounded-xl border border-border bg-popover p-1 shadow-lg">
                      {aiModels.filter((m) => m.group === "more").map((model) => (
                        <button
                          key={model.id}
                          onClick={() => {
                            setSelectedAiModel(model.id);
                            setHeaderModelOverride(null);
                            setShowAiModelPicker(false);
                            setShowMoreModels(false);
                          }}
                          className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm ${
                            selectedAiModel === model.id
                              ? "bg-accent text-foreground"
                              : "text-foreground hover:bg-accent"
                          }`}
                        >
                          <img
                            src={resolveDisplayIcon(model.icon, isDark)}
                            alt=""
                            className="h-5 w-5 shrink-0 object-contain"
                          />
                          <span className="flex-1">{model.name}</span>
                          {selectedAiModel === model.id && (
                            <Check size={14} className="text-primary" />
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>}
              </div>
            )}
          </div>
        </div>

        {/* ================ MESSAGES ================ */}
        <div className="flex flex-1 flex-col items-center overflow-y-auto">
          <div className="w-full max-w-3xl px-6 pb-44 pt-6">
            {isSharedReadOnly && (
              <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
                {t("Shared conversation — read only. Start a new chat to continue on your own account.")}
              </div>
            )}
            {messages.map((msg, idx) => {
              // Context reset divider
              if (msg.category === "context_reset") {
                return (
                  <div key={msg.id} className="flex items-center gap-3 py-4">
                    <div className="h-px flex-1 bg-border" />
                    <span className="text-xs font-medium text-muted-foreground">
                      {msg.content}
                    </span>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                );
              }

              const isUser = msg.sender === "user";
              // Show ThinkingIndicator only when there is NOTHING to display yet —
              // no text content, no tool-call cards, and no reasoning tokens yet.
              // Once any of those arrive (Gemini/Anthropic emit reasoning before
              // the user-facing answer; tool agents emit content_blocks during
              // tool calls), render the body so the streaming UX is visible.
              const hasContentBlocks = !!(msg.contentBlocks && msg.contentBlocks.length > 0);
              const hasReasoning = !!(msg.reasoningContent && msg.reasoningContent.length > 0);
              // Image-gen path: backend streams "Generating image..." as a token
              // BEFORE the actual image markdown arrives. Without this carve-out,
              // that placeholder text would unmount the ThinkingIndicator (and its
              // image skeleton) the instant streaming begins. Keep showing the
              // indicator until real image markdown ("![...](...)") appears.
              // Scope to the currently-streaming message — routedMode is global,
              // so without `msg.id === streamingMsgId` an in-flight image_gen send
              // would retroactively flip prior plain-text replies into the image
              // skeleton state and hide their real content.
              const hasImageMarkdown = !!msg.content && msg.content.includes("![");
              const isCurrentlyStreaming = msg.id === streamingMsgId;
              const isImageGenStreaming =
                isCurrentlyStreaming && routedMode === "image_gen" && !hasImageMarkdown;
              const isThinking =
                msg.sender === "agent" &&
                isCurrentlyStreaming &&
                (msg.content === "" || isImageGenStreaming) &&
                !hasContentBlocks &&
                !hasReasoning &&
                isSendingThisSession;
              const isInlineEditingUserMessage =
                isUser && editingMsgId === msg.id && noAgentMode;

              // Canvas: any agent message can be edited via canvas
              const isEditingThis = canvasEditingId === msg.id;
              const hasFollowupAgentReply = messages
                .slice(idx + 1)
                .some(
                  (nextMsg) =>
                    nextMsg.sender === "agent" &&
                    !nextMsg.hitl &&
                    (!!nextMsg.content?.trim() || !!nextMsg.contentBlocks?.length),
                );
              const explicitHitlStatus = hitlDoneMap[msg.id];
              const hitlResolved = msg.hitlIsDeployed
                ? !!explicitHitlStatus
                : (!!explicitHitlStatus || hasFollowupAgentReply);
              const resolvedLabel = explicitHitlStatus || (!msg.hitlIsDeployed && hasFollowupAgentReply ? "Completed" : "");
              const isRejectedResolution = resolvedLabel.toLowerCase().includes("reject");
              // Figure out the right avatar for an AI response.
              // - If the message's sender_name matches a known AI model
              //   (e.g. "Gemini 2.5 Pro"), render that model's icon.
              // - Else if it matches an agent, keep the existing colored
              //   badge with the Sparkles glyph (agent branding).
              // - Fallback: generic Sparkles badge.
              const matchedModel =
                !isUser && msg.agentName
                  ? aiModels.find(
                      (m) =>
                        m.name === msg.agentName ||
                        msg.agentName?.toLowerCase().includes(m.name.toLowerCase()),
                    )
                  : undefined;
              return (
                <div key={msg.id} className={`flex py-5 ${isUser ? "justify-end" : "items-start gap-4"}`}>
                  {/* Avatar — only for agent messages */}
                  {!isUser && (
                  <div
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden ${
                      matchedModel
                          ? "rounded-lg bg-muted"
                          : "rounded-lg"
                    }`}
                    style={
                      !matchedModel
                        ? { background: getAgentColor(msg.agentName) }
                        : undefined
                    }
                  >
                    {matchedModel?.icon ? (
                      <img
                        src={resolveDisplayIcon(matchedModel.icon, isDark)}
                        alt=""
                        className="h-5 w-5 object-contain"
                      />
                    ) : (
                      <Sparkles size={16} color="white" />
                    )}
                  </div>
                  )}

                  {/* Content */}
                  <div
                    className={
                      isUser
                        ? isInlineEditingUserMessage
                          ? "w-full max-w-full"
                          : "max-w-[80%]"
                        : "min-w-0 flex-1"
                    }
                  >
                    {!isUser && (
                    <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-foreground">
                      {msg.agentName}
                      <span className="text-xs font-normal text-muted-foreground">
                        {msg.timestamp}
                      </span>
                    </div>
                    )}
                    {isThinking ? (
                      // Look up the user message that triggered this agent
                      // placeholder so we can show file-aware stages.
                      (() => {
                        const prevUser = idx > 0 ? messages[idx - 1] : null;
                        const triggerFiles = (prevUser?.files || []).map(
                          (p: string) => p.split(/[/\\]/).pop() || p,
                        );
                        return <ThinkingIndicator fileNames={triggerFiles} routedMode={routedMode} />;
                      })()
                    ) : isUser ? (
                      <>
                      <div
                        className={`group/usermsg rounded-lg bg-[#edf5fd] px-4 py-2.5 text-[15px] leading-relaxed text-foreground/80 shadow-sm dark:bg-accent ${
                          isInlineEditingUserMessage ? "w-full" : ""
                        }`}
                      >
                        {editingMsgId === msg.id && noAgentMode ? (
                          // Inline editor — matches MiBuddy's UX: textarea + Cancel/Send buttons
                          <div className="rounded-xl border border-border bg-muted/30 p-3">
                            <textarea
                              value={editDraft}
                              onChange={(e) => setEditDraft(e.target.value)}
                              autoFocus
                              rows={3}
                              className="w-full resize-none border-none bg-transparent text-[15px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0"
                              placeholder={t("Edit your prompt...")}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.shiftKey) {
                                  e.preventDefault();
                                  handleSaveEdit();
                                } else if (e.key === "Escape") {
                                  e.preventDefault();
                                  handleCancelEdit();
                                }
                              }}
                            />
                            <div className="mt-2 flex justify-end gap-2">
                              <button
                                onClick={handleCancelEdit}
                                className="rounded-lg bg-gray-100 px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                              >
                                {t("Cancel")}
                              </button>
                              <button
                                onClick={handleSaveEdit}
                                disabled={!editDraft.trim() || isSending}
                                className="rounded-lg bg-red-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                {t("Send")}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            {highlightMentions(msg.content)}
                            {msg.files && msg.files.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-2">
                                {msg.files.map((filePath, idx) => {
                                  const ext = filePath.split(".").pop()?.toLowerCase() || "";
                                  const isImage = ["png", "jpg", "jpeg", "gif", "webp", "bmp"].includes(ext);
                                  // Split on either separator — Windows Path
                                  // stringifies with backslashes on the backend.
                                  const fileName = filePath.split(/[/\\]/).pop() || filePath;
                                  return isImage ? (
                                    <img
                                      key={idx}
                                      src={`${BASE_URL_API}files/images/${filePath}`}
                                      alt="uploaded"
                                      className="max-h-48 max-w-xs rounded-lg border border-border object-contain"
                                    />
                                  ) : (
                                    <div
                                      key={idx}
                                      className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground"
                                    >
                                      <FileText size={16} />
                                      <span className="max-w-[200px] truncate" title={fileName}>{fileName}</span>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </>
                        )}
                      </div>
                      {/* Prompt action buttons — Copy (always) + Edit (no-agent mode only).
                          Edit stays gated because re-sending in agent mode would
                          re-trigger the agent run; copy is harmless in any mode. */}
                      {msg.content && !isSending && (
                        <div className="mt-1 flex items-center justify-end gap-2">
                          {msg.timestamp && (
                            <span className="text-xs font-normal text-muted-foreground">
                              {msg.timestamp}
                            </span>
                          )}
                          <button
                            onClick={() => handleCopyMessage(msg.content, msg.id)}
                            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                            title={copiedMsgId === msg.id ? t("Copied!") : t("Copy")}
                          >
                            {copiedMsgId === msg.id ? <Check size={13} className="text-green-600" /> : <Copy size={13} />}
                          </button>
                          {noAgentMode && (
                            <button
                              onClick={() => handleStartEdit(msg.id, msg.content)}
                              className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                              title={t("Edit prompt")}
                            >
                              <Pencil size={13} />
                            </button>
                          )}
                        </div>
                      )}
                      </>
                    ) : msg.category === "error" ? (
                      // Error rows (persisted with category="error", e.g. model
                      // rate-limit failures) render as a red alert card instead
                      // of the regular markdown bubble. Skips reasoning / tool
                      // cards / action buttons — none apply to an error reply.
                      <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[15px] leading-relaxed text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
                        <AlertCircle size={16} className="mt-0.5 shrink-0" />
                        <span className="whitespace-pre-wrap break-words">{msg.content}</span>
                      </div>
                    ) : (
                      <div className="text-[15px] leading-relaxed text-foreground/80">
                        {/* CoT Reasoning — collapsible pill + panel */}
                        {msg.reasoningContent && (
                          <ReasoningBlock
                            reasoning={msg.reasoningContent}
                            streaming={isSending && msg.id === streamingMsgId}
                          />
                        )}
                        {msg.contentBlocks && msg.contentBlocks.length > 0 && (
                          <ContentBlockDisplay
                            contentBlocks={msg.contentBlocks}
                            chatId={msg.id}
                            state={msg.blocksState}
                            isLoading={isSending && msg.id === streamingMsgId}
                          />
                        )}
                        {msg.canvasEnabled && msg.content ? (
                          /* Canvas mode — render in editable card (MiBuddy parity) */
                          <CanvasEditor
                            messageId={msg.id}
                            content={msg.content}
                            sessionId={currentSessionId || undefined}
                            showDraftButton={false}
                            onContentChange={(updated) => {
                              setMessages((prev) =>
                                prev.map((m) =>
                                  m.id === msg.id ? { ...m, content: updated } : m,
                                ),
                              );
                            }}
                          />
                        ) : msg.content || (!hasContentBlocks && !hasReasoning) ? (
                          // Render the markdown body if there is text to show, or
                          // (as a fallback) when there are no tool cards AND no
                          // reasoning panel either — that fallback case is what
                          // the "Message empty." string covers. While tool blocks
                          // or reasoning are streaming with no answer text yet,
                          // render nothing so the empty placeholder doesn't flash
                          // between them and the first answer token.
                          <MarkdownField
                            chat={{}}
                            isEmpty={!msg.content}
                            chatMessage={msg.content}
                            editedFlag={null}
                          />
                        ) : null}
                        {/* Action buttons row — show on every assistant message,
                            including image-generation replies. Thumbs/copy/share
                            all operate on the accompanying text (captions like
                            "Here is your generated image."); download + share
                            naturally apply to the image itself because the image
                            URL lives in the same markdown. */}
                        {msg.content && !isSending && (
                          <div className="mt-1.5 flex items-center gap-1">
                            <button
                              onClick={() => handleThumbClick(msg, "up")}
                              className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
                                msg.feedbackRating === "up"
                                  ? "text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30"
                                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
                              }`}
                              title={msg.feedbackRating === "up" ? t("Remove rating") : t("Good response")}
                            >
                              <ThumbsUp
                                size={13}
                                fill={msg.feedbackRating === "up" ? "currentColor" : "none"}
                              />
                            </button>
                            <button
                              onClick={() => handleThumbClick(msg, "down")}
                              className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
                                msg.feedbackRating === "down"
                                  ? "text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30"
                                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
                              }`}
                              title={msg.feedbackRating === "down" ? t("Remove rating") : t("Bad response")}
                            >
                              <ThumbsDown
                                size={13}
                                fill={msg.feedbackRating === "down" ? "currentColor" : "none"}
                              />
                            </button>
                            <button
                              onClick={() => handleCopyMessage(msg.content, msg.id)}
                              className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                              title={copiedMsgId === msg.id ? t("Copied!") : t("Copy")}
                            >
                              {copiedMsgId === msg.id ? <Check size={13} className="text-green-600" /> : <Copy size={13} />}
                            </button>
                            <button
                              onClick={() => handleSpeak(msg.content)}
                              className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                              title={t("Read aloud")}
                            >
                              <AudioLines size={13} />
                            </button>
                            <div className="relative" data-export-menu>
                              <button
                                onClick={() => setExportMenuOpenId(exportMenuOpenId === msg.id ? null : msg.id)}
                                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                                title={t("Export")}
                              >
                                <Download size={13} />
                              </button>
                              {exportMenuOpenId === msg.id && (
                                <div className="absolute left-0 top-full z-50 mt-1 min-w-[140px] rounded-lg border border-border bg-popover p-1 shadow-lg">
                                  <button
                                    onClick={() => { handleExportDocx(msg.content); setExportMenuOpenId(null); }}
                                    className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm text-foreground hover:bg-accent"
                                  >
                                    <FileText size={14} className="text-blue-600" />
                                    <span>{t("Word")}</span>
                                  </button>
                                  <button
                                    onClick={() => { handleExportPdf(msg.content); setExportMenuOpenId(null); }}
                                    className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm text-foreground hover:bg-accent"
                                  >
                                    <FileText size={14} className="text-red-600" />
                                    <span>{t("PDF")}</span>
                                  </button>
                                  <button
                                    onClick={() => { handleExportText(msg.content); setExportMenuOpenId(null); }}
                                    className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm text-foreground hover:bg-accent"
                                  >
                                    <FileIcon size={14} className="text-muted-foreground" />
                                    <span>{t("Text")}</span>
                                  </button>
                                </div>
                              )}
                            </div>
                            {/* Share / More options menu — model replies only.
                                Hidden on agent-deployment responses per product
                                decision (Teams/Outlook share is a model feature). */}
                            {!msg.isAgentResponse && (
                              <div className="relative" data-share-menu>
                                <button
                                  onClick={() => setShareMenuOpenId(shareMenuOpenId === msg.id ? null : msg.id)}
                                  className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                                  title={t("More options")}
                                >
                                  <MoreVertical size={13} />
                                </button>
                                {shareMenuOpenId === msg.id && (
                                  <div className="absolute left-0 top-full z-50 mt-1 min-w-[180px] rounded-lg border border-border bg-popover p-1 shadow-lg">
                                    <button
                                      onClick={() => handleShareTeams(msg.content)}
                                      className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm text-foreground hover:bg-accent"
                                    >
                                      <img src={shareTeamsIcon} alt="Teams" className="h-4 w-4 object-contain" />
                                      <span>{t("Share on MsTeams")}</span>
                                    </button>
                                    <button
                                      onClick={() => handleOutlookDraft(msg.content)}
                                      className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm text-foreground hover:bg-accent"
                                    >
                                      <img src={outlookIcon} alt="Outlook" className="h-4 w-4 object-contain" />
                                      <span>{t("Draft in Outlook")}</span>
                                    </button>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                        {/* HITL action buttons */}
                        {msg.hitl && (
                          msg.hitlIsDeployed ? (
                            /* Deployed runs: approval goes to dept admin via HITL page */
                            hitlResolved ? (
                              <div
                                className={[
                                  "mt-3 flex items-center gap-2 rounded-md border px-4 py-2.5 text-sm",
                                  isRejectedResolution
                                    ? "border-red-300 bg-red-50 text-red-700 dark:border-red-700 dark:bg-red-950/30 dark:text-red-300"
                                    : "border-green-300 bg-green-50 text-green-700 dark:border-green-700 dark:bg-green-950/30 dark:text-green-300",
                                ].join(" ")}
                              >
                                <span className="font-medium">Human review status:</span>
                                <span>{resolvedLabel}</span>
                              </div>
                            ) : (
                              <div className="mt-3 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm dark:border-amber-700 dark:bg-amber-950/30">
                                <Clock size={16} className="shrink-0 text-amber-600 dark:text-amber-400" />
                                <span className="text-amber-700 dark:text-amber-300">
                                  Pending department admin approval. The assigned admin can approve or reject from the{" "}
                                  <a
                                    href="/hitl-approvals"
                                    className="font-medium underline hover:text-amber-900 dark:hover:text-amber-100"
                                  >
                                    HITL Approvals
                                  </a>{" "}
                                  page.
                                </span>
                              </div>
                            )
                          ) : (
                          (msg.hitlActions && msg.hitlActions.length > 0) ? (
                          <div className="mt-3 flex flex-col gap-2.5">
                            <div className="flex flex-wrap gap-2">
                            {msg.hitlActions.map((action) => {
                              const done = hitlDoneMap[msg.id];
                              const isLoading = hitlLoadingId === msg.id;
                              const isThisAction = hitlLoadingAction === action;
                              const isReject = action.toLowerCase().includes("reject");
                              return (
                                <button
                                  key={action}
                                  onClick={() =>
                                    handleHitlAction(msg.id, msg.hitlThreadId ?? "", action)
                                  }
                                  disabled={!!done || isLoading}
                                  className={[
                                    "inline-flex items-center gap-1.5 rounded-md border px-4 py-1.5 text-sm font-medium transition-colors",
                                    done === action
                                      ? isReject
                                        ? "border-red-500 bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                                        : "border-green-500 bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                                      : done
                                        ? "cursor-not-allowed border-border bg-muted/30 text-muted-foreground opacity-50"
                                        : isLoading && isThisAction
                                          ? isReject
                                            ? "cursor-wait border-red-400 bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400"
                                            : "cursor-wait border-green-400 bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400"
                                          : isLoading
                                            ? "cursor-not-allowed border-border bg-muted/30 text-muted-foreground opacity-50"
                                            : isReject
                                              ? "cursor-pointer border-red-300 text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-950/30"
                                              : "cursor-pointer border-border text-foreground hover:bg-muted",
                                  ].join(" ")}
                                >
                                  {isLoading && isThisAction && (
                                    <Loader2 size={14} className="animate-spin" />
                                  )}
                                  {isLoading && isThisAction
                                    ? "Submitting..."
                                    : done === action
                                      ? `\u2713 ${action}`
                                      : action}
                                </button>
                              );
                            })}
                            </div>
                            {hitlDoneMap[msg.id] && (
                              <span className="text-xs text-muted-foreground">
                                Decision submitted — agent continued.
                              </span>
                            )}
                          </div>
                          ) : null
                          )
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* ================ INPUT AREA ================
             When the chat is empty, the input + heading sit centered in
             the viewport (MiBuddy-style landing). After the first message
             they drop to the bottom and the messages scroll above them. */}
        <div
          className={
            messages.length === 0 && !isSending
              ? "pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-6 px-6"
              : "pointer-events-none absolute bottom-0 left-0 right-0 flex justify-center bg-gradient-to-t from-background from-40% to-transparent px-6 pb-10 transition-all"
          }
        >
          {messages.length === 0 && !isSending && (
            <h1 className="text-3xl font-semibold tracking-tight text-red-600 md:text-4xl">
              {t("How can I assist you today?")}
            </h1>
          )}
          <div className="pointer-events-auto relative w-full max-w-3xl">
            {/* Mention dropdown */}
            {showMentions && (
              <div className="absolute bottom-full left-0 z-50 mb-2 max-h-64 min-w-[240px] overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-lg">
                {filteredAgents.map((agent) => (
                  <button
                    key={agent.id}
                    onClick={() => handleSelectAgent(agent)}
                    className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                  >
                    <span
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
                      style={{ background: agent.color }}
                    >
                      <Sparkles size={12} color="white" />
                    </span>
                    <div className="min-w-0">
                      <div className="flex items-center font-medium">
                        <span>@{agent.name}</span>
                        {versionBadge(agent.version_label)}
                        {uatBadge(agent.environment)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {agent.description}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Text Input — pill-style. In light mode uses a very subtle
                pink horizontal wash; in dark mode just the card color (the
                MiBuddy-style gradient looks silvery/off in dark). */}
            <div className="overflow-hidden rounded-[28px] border border-red-100 bg-gradient-to-r from-red-50/60 via-white to-red-50/60 shadow-md shadow-red-100/30 transition-all focus-within:border-red-300 focus-within:shadow-lg dark:border-border dark:from-card dark:via-card dark:to-card dark:shadow-none dark:focus-within:border-red-800/60">
              {/* File previews */}
              {uploadFiles.length > 0 && (
                <div className="flex flex-wrap gap-2 px-4 pt-3">
                  {uploadFiles.map((f) => (
                    <div
                      key={f.id}
                      className="relative flex items-center gap-1.5 rounded-lg border border-border bg-muted px-2.5 py-1.5 text-xs"
                    >
                      {f.loading ? (
                        <Loader2 size={14} className="animate-spin text-muted-foreground" />
                      ) : f.error ? (
                        <span className="text-destructive">Failed</span>
                      ) : ["png", "jpg", "jpeg", "gif", "webp", "bmp"].includes(
                          f.file.name.split(".").pop()?.toLowerCase() || ""
                        ) ? (
                        <ImagePlus size={14} className="text-muted-foreground" />
                      ) : (
                        <FileText size={14} className="text-muted-foreground" />
                      )}
                      <span className="max-w-[120px] truncate">{f.file.name}</span>
                      <button
                        onClick={() => removeFile(f.id)}
                        className="ml-0.5 rounded-full p-0.5 text-muted-foreground hover:bg-background hover:text-foreground"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {/* Autocomplete suggestions dropdown — hide while response is generating */}
              {showSuggestions && suggestions.length > 0 && noAgentMode && !isSending && (
                <div className="border-b border-border px-2 py-1.5">
                  {suggestions.map((s, i) => (
                    <div
                      key={i}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        handleSelectSuggestion(s);
                      }}
                      className={`flex w-full cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors ${
                        i === selectedSuggestionIdx
                          ? "bg-accent text-foreground"
                          : "text-muted-foreground hover:bg-accent hover:text-foreground"
                      }`}
                    >
                      <Search size={12} className="shrink-0 opacity-50" />
                      <span className="truncate">{s}</span>
                    </div>
                  ))}
                </div>
              )}
              {/* Indicator pills (Canvas / Image / COT) — stacked above the
                  single-line input row, same as before. */}
              {isCanvasEnabled && (
                <div className="flex items-center px-4 pt-2">
                  <div className="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-3 py-1 dark:border-red-800 dark:bg-red-950/30">
                    <Pencil size={12} className="text-red-500" />
                    <span className="text-xs font-semibold text-red-500">{t("Canvas")}</span>
                    <button
                      onClick={() => setIsCanvasEnabled(false)}
                      className="ml-0.5 rounded-full p-0.5 text-red-400 hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-900/50"
                    >
                      <X size={10} />
                    </button>
                  </div>
                </div>
              )}
              {imageMode && (
                <div className="flex items-center px-4 pt-2">
                  <div className="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-3 py-1 dark:border-red-800 dark:bg-red-950/30">
                    <Image size={12} className="text-red-500" />
                    <span className="text-xs font-semibold text-red-500">{t("Image")}</span>
                    <button
                      onClick={() => {
                        // Dismiss the Image chip and revert the dropdown from the
                        // image-gen model (Nano Banana / DALL-E) back to MiBuddy AI.
                        const mibuddy = aiModels.find((m) => /mibuddy[\s_-]?ai/i.test(m.name));
                        if (mibuddy) setSelectedAiModel(mibuddy.id);
                        setImageMode(false);
                      }}
                      className="ml-0.5 rounded-full p-0.5 text-red-400 hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-900/50"
                    >
                      <X size={10} />
                    </button>
                  </div>
                </div>
              )}
              {cotReasoning && (
                <div className="flex items-center px-4 pt-2">
                  <div className="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-3 py-1 dark:border-red-800 dark:bg-red-950/30">
                    <Lightbulb size={12} className="text-red-500" />
                    <span className="text-xs font-semibold text-red-500">{t("COT")}</span>
                    <button
                      onClick={() => setCotReasoning(false)}
                      className="ml-0.5 rounded-full p-0.5 text-red-400 hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-900/50"
                    >
                      <X size={10} />
                    </button>
                  </div>
                </div>
              )}

              {/* Single-line input row: [+] [img] [textarea grows] [mic] [send] */}
              <div className="flex items-end gap-1 px-3 py-2">
                {/* ---- Addon: Plus menu button ----
                    In AGENT mode: directly opens the file picker (simpler UX).
                    In MODEL (No Agent) mode: opens the full menu with Create image, Canvas, etc. */}
                <div data-plus-menu className="shrink-0">
                  <button
                    onClick={(e) => {
                      // Agent mode — open file explorer directly
                      if (!noAgentMode) {
                        fileInputRef.current?.click();
                        return;
                      }
                      // Model mode — toggle the options menu
                      if (!showPlusMenu) {
                        const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                        setPlusMenuPos({ bottom: window.innerHeight - rect.top + 8, left: rect.left });
                      }
                      setShowPlusMenu(!showPlusMenu);
                    }}
                    disabled={isSendingThisSession || !canInteract || isSharedReadOnly || hasPendingHitl}
                    className={`flex h-9 w-9 items-center justify-center rounded-full text-muted-foreground transition-colors ${(isSendingThisSession || !canInteract || isSharedReadOnly || hasPendingHitl) ? "cursor-not-allowed opacity-50" : "hover:bg-accent hover:text-foreground"}`}
                    title={noAgentMode ? t("More options") : t("Upload files")}
                  >
                    <Plus size={18} />
                  </button>
                </div>

                {/* Upload image button — hidden when a model or agent is active;
                    upload in those modes goes through the + menu instead. */}
                {!((noAgentMode && selectedAiModel) || (!noAgentMode && selectedModelId)) && (
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isSendingThisSession || !canInteract || isSharedReadOnly || hasPendingHitl}
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors ${(isSendingThisSession || !canInteract || isSharedReadOnly || hasPendingHitl) ? "cursor-not-allowed opacity-50" : "hover:bg-accent hover:text-foreground"}`}
                    title={t("Upload image")}
                  >
                    <ImagePlus size={18} />
                  </button>
                )}

                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => handleInputChange(e.target.value)}
                  onPaste={handlePaste}
                  disabled={isSendingThisSession || !canInteract || isSharedReadOnly || hasPendingHitl}
                  onKeyDown={(e) => {
                    if (showSuggestions && suggestions.length > 0) {
                      if (e.key === "ArrowDown") {
                        e.preventDefault();
                        setSelectedSuggestionIdx((prev) => (prev + 1) % suggestions.length);
                        return;
                      }
                      if (e.key === "ArrowUp") {
                        e.preventDefault();
                        setSelectedSuggestionIdx((prev) => (prev <= 0 ? suggestions.length - 1 : prev - 1));
                        return;
                      }
                      if (e.key === "Enter" && !e.shiftKey && selectedSuggestionIdx >= 0) {
                        e.preventDefault();
                        handleSelectSuggestion(suggestions[selectedSuggestionIdx]);
                        return;
                      }
                      if (e.key === "Escape") {
                        setSuggestions([]);
                        setShowSuggestions(false);
                        return;
                      }
                    }
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      setSuggestions([]); setShowSuggestions(false);
                      handleSend();
                    }
                  }}
                  placeholder={
                    isSharedReadOnly
                      ? t("Read-only shared conversation")
                      : !canInteract
                        ? t("You do not have permission to interact with agents.")
                        : hasPendingHitl
                          ? t("Waiting for human review — approve or reject to continue")
                          : isSendingThisSession
                            ? t("Waiting for response...")
                            : noAgentMode && messages.length > 0
                              ? t("Start typing to chat with the Model")
                              : t("Start typing with @ to chat with an agent")
                  }
                  rows={1}
                  style={{ maxHeight: TEXTAREA_MAX_HEIGHT }}
                  className={`min-w-0 flex-1 resize-none overflow-y-hidden border-none bg-transparent px-2 py-1.5 text-[15px] leading-6 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0 ${(isSendingThisSession || !canInteract || isSharedReadOnly || hasPendingHitl) ? "cursor-not-allowed opacity-50" : ""}`}
                />

                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(",")}
                  className="hidden"
                  onChange={handleFileChange}
                />

                {/* Mic */}
                <button
                  onClick={handleMicClick}
                  disabled={isSendingThisSession || !canInteract || isSharedReadOnly || hasPendingHitl}
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors ${
                    isListening
                      ? "bg-red-500 text-white animate-pulse"
                      : (isSendingThisSession || !canInteract || isSharedReadOnly || hasPendingHitl)
                        ? "cursor-not-allowed text-muted-foreground opacity-50"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  }`}
                  title={isListening ? t("Stop listening") : t("Voice input")}
                >
                  {isListening ? <AudioLines size={18} /> : <Mic size={18} />}
                </button>

                {/* Send — wrap in arrow fn so React's MouseEvent isn't passed as the override text.
                    Disabled while any file is still uploading so the user can't accidentally send
                    a message before the file is attached (causing "no document" agent replies). */}
                {(() => {
                  const anyUploading = uploadFiles.some((f) => f.loading);
                  const sendDisabled =
                    (!input.trim() && !uploadFiles.some((f) => f.path)) ||
                    isSendingThisSession ||
                    !canInteract ||
                    isSharedReadOnly ||
                    hasPendingHitl ||
                    anyUploading;
                  const sendActive =
                    (input.trim() || uploadFiles.some((f) => f.path)) &&
                    !isSendingThisSession &&
                    canInteract &&
                    !isSharedReadOnly &&
                    !hasPendingHitl &&
                    !anyUploading;
                  return (
                    <button
                      onClick={() => handleSend()}
                      disabled={sendDisabled}
                      title={anyUploading ? t("Waiting for upload to finish…") : undefined}
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors ${
                        sendActive
                          ? "bg-foreground text-background hover:opacity-90"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {anyUploading ? (
                        <Loader2 size={16} className="animate-spin" />
                      ) : (
                        <Send size={16} className="-ml-px -mt-px" />
                      )}
                    </button>
                  );
                })()}
              </div>
            </div>

          </div>
        </div>

        {/* Disclaimer — bottom-left, matching MiBuddy style */}
        <div className="pointer-events-none absolute bottom-1 left-5 text-xs text-muted-foreground">
          {t("Generative AI may display inaccurate information, including about people, so double-check its responses.")}
        </div>
      </div>
      )}
      {/* ---- Thumbs up/down feedback popup (MiBuddy-parity) ---- */}
      {feedbackPopup && (
        <FeedbackPopup
          mode={feedbackPopup.mode}
          initialReasons={feedbackPopup.initialReasons}
          initialComment={feedbackPopup.initialComment}
          onSubmit={handleSubmitFeedback}
          onClose={() => setFeedbackPopup(null)}
        />
      )}

      {/* ---- Addon: SharePoint File Picker (MSAL-based) ---- */}
      <SharePointFilePicker
        isOpen={spPickerOpen}
        onDismiss={() => setSpPickerOpen(false)}
        onFilesSelected={handleSpFilesSelected}
      />

      {/* ---- Outlook (orchestrator) connector ---- */}
      <OutlookOrchConnector
        isOpen={showOutlookOrch}
        onDismiss={() => setShowOutlookOrch(false)}
        onConnected={() => setIsOutlookOrchConnected(true)}
      />
      {/* Old OutlookConnector modal removed — OutlookOrchConnector above
          is the single Outlook integration going forward. */}
      {false && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50">
          <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-2xl border border-border bg-popover shadow-2xl">
            {/* Modal header */}
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div className="flex items-center gap-3">
                {!spShowConsent && spFolderStack.length > 0 && (
                  <button
                    onClick={spGoBack}
                    className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <ArrowLeft size={18} />
                  </button>
                )}
                <div>
                  <h2 className="text-base font-semibold text-foreground">
                    {spShowConsent ? t("Connect to SharePoint") : t("SharePoint Files")}
                  </h2>
                  {!spShowConsent && spFolderStack.length > 0 && (
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <span>{t("OneDrive")}</span>
                      {spFolderStack.map((f) => (
                        <span key={f.id}>
                          <span className="mx-0.5">/</span>
                          <span>{f.name}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <button
                onClick={() => { setSpModalOpen(false); setSpShowConsent(false); }}
                className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X size={18} />
              </button>
            </div>

            {spShowConsent ? (
              <div className="flex flex-1 flex-col px-6 py-6">
                <div className="mb-5 flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-100 dark:bg-blue-900/30">
                    <Shield size={24} className="text-blue-600 dark:text-blue-400" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">{t("Permissions Required")}</h3>
                    <p className="text-xs text-muted-foreground">{t("This app needs access to your Microsoft account")}</p>
                  </div>
                </div>

                <p className="mb-4 text-sm text-muted-foreground">
                  {t("To browse and upload files from SharePoint, the following permissions are required:")}
                </p>

                <div className="mb-6 flex flex-col gap-3">
                  <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 px-4 py-3">
                    <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-green-500" />
                    <div>
                      <div className="text-sm font-medium text-foreground">{t("Read your profile")}</div>
                      <div className="text-xs text-muted-foreground">{t("View your basic account information")}</div>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 px-4 py-3">
                    <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-green-500" />
                    <div>
                      <div className="text-sm font-medium text-foreground">{t("Access your files")}</div>
                      <div className="text-xs text-muted-foreground">{t("Read files from your OneDrive and SharePoint")}</div>
                    </div>
                  </div>
                  <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 px-4 py-3">
                    <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-green-500" />
                    <div>
                      <div className="text-sm font-medium text-foreground">{t("Access SharePoint sites")}</div>
                      <div className="text-xs text-muted-foreground">{t("Browse SharePoint sites you have access to")}</div>
                    </div>
                  </div>
                </div>

                {spError && (
                  <div className="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700 dark:bg-red-950/30 dark:text-red-300">
                    {spError}
                  </div>
                )}

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => { setSpModalOpen(false); setSpShowConsent(false); }}
                    className="flex-1 rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent"
                  >
                    {t("Cancel")}
                  </button>
                  <button
                    onClick={handleSharePointConsent}
                    disabled={spLoading}
                    className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {spLoading ? (
                      <>
                        <Loader2 size={16} className="animate-spin" />
                        {t("Connecting...")}
                      </>
                    ) : (
                      t("Allow & Connect")
                    )}
                  </button>
                </div>

                <p className="mt-4 text-center text-xs text-muted-foreground">
                  {t("You will be redirected to Microsoft to sign in and grant access.")}
                </p>
              </div>
            ) : (
            <div className="flex-1 overflow-y-auto px-2 py-2" style={{ scrollbarWidth: "thin" }}>
              {spError && (
                <div className="mx-3 mb-3 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700 dark:bg-red-950/30 dark:text-red-300">
                  {spError}
                  {!spAccessToken && (
                    <button
                      onClick={handleSharePointAuth}
                      className="ml-2 font-medium underline"
                    >
                      {t("Try again")}
                    </button>
                  )}
                </div>
              )}

              {spLoading && (
                <div className="flex items-center justify-center py-12">
                  <Loader2 size={24} className="animate-spin text-muted-foreground" />
                  <span className="ml-3 text-sm text-muted-foreground">{t("Loading...")}</span>
                </div>
              )}

              {!spLoading && !spError && spItems.length === 0 && spAccessToken && (
                <div className="py-12 text-center text-sm text-muted-foreground">
                  {t("No files found in this location")}
                </div>
              )}

              {!spLoading && spItems.map((item) => (
                <button
                  key={item.id}
                  onClick={() => {
                    if (item.type === "folder") {
                      spOpenFolder(item);
                    } else {
                      spSelectFile(item);
                    }
                  }}
                  className="flex w-full items-center gap-3 rounded-lg px-4 py-3 text-left text-sm text-foreground hover:bg-accent"
                >
                  {item.type === "folder" ? (
                    <Folder size={20} className="shrink-0 text-blue-500" />
                  ) : (
                    <FileIcon size={20} className="shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{item.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.type === "folder"
                        ? `${item.childCount ?? 0} items`
                        : item.size
                          ? `${(item.size / 1024).toFixed(1)} KB`
                          : ""}
                    </div>
                  </div>
                  {item.type === "folder" && (
                    <ChevronRight size={16} className="shrink-0 text-muted-foreground" />
                  )}
                </button>
              ))}
            </div>
            )}

            {/* Modal footer */}
            <div className="border-t border-border px-5 py-3 text-xs text-muted-foreground">
              {!spShowConsent && spAccessToken
                ? t("Click a file to attach it, or open a folder to browse")
                : t("Authenticate with your Microsoft account to browse files")}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

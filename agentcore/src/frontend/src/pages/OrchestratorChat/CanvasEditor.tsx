/**
 * Canvas editor — port of MiBuddy's canvas UI.
 *
 * Renders an assistant message inside a bordered, editable card. The
 * user can click the "Edit" action to modify the content inline
 * (contentEditable div); edits auto-save to the backend with a debounce.
 * A "DRAFT" action opens the user's mail client pre-populated with
 * the content — matches MiBuddy's Outlook-draft hand-off.
 *
 * Floating panel + reading-level slider matches MiBuddy exactly.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Pencil, Check, Mail } from "lucide-react";

// MiBuddy SVG icons
import emojiActWord from "@/assets/emojiAct_word.svg";
import emojiActRemove from "@/assets/emojiAct_remove.svg";
import readingLavelWhite from "@/assets/reading-lavel-white.svg";
import readingLavel from "@/assets/reading-lavel.svg";

// Reading levels — matches MiBuddy's READING_LEVELS constant.
const READING_LEVELS = [
  "kindergarten",
  "middle school",
  "high school",
  "reading level",
  "college",
  "graduate",
] as const;
const NON_CLICKABLE_INDEX = READING_LEVELS.indexOf(
  "reading level" as (typeof READING_LEVELS)[number],
);

interface CanvasEditorProps {
  messageId: string;
  /** Full markdown / HTML text of the assistant reply. */
  content: string;
  /** Session id so the backend can scope persisted canvas edits. */
  sessionId?: string;
  /** Whether to show the DRAFT (mailto:) button — MiBuddy shows it
   *  only when Outlook is connected & the content looks email-ish. */
  showDraftButton?: boolean;
  /** Called when content changes and is persisted to the backend. */
  onContentChange?: (newContent: string) => void;
}

/* Minimal markdown → HTML for the initial render */
function mdToHtml(md: string): string {
  const esc = (s: string) =>
    s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  const lines = md.split(/\r?\n/);
  const out: string[] = [];
  let inUl = false;
  let inOl = false;
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (inOl) { out.push("</ol>"); inOl = false; }
      out.push("");
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (inOl) { out.push("</ol>"); inOl = false; }
      const level = h[1].length;
      out.push(`<h${level}>${esc(h[2])}</h${level}>`);
      continue;
    }
    const ul = line.match(/^[-*+]\s+(.*)$/);
    if (ul) {
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (!inUl) { out.push("<ul>"); inUl = true; }
      out.push(`<li>${esc(ul[1])}</li>`);
      continue;
    }
    const ol = line.match(/^\d+\.\s+(.*)$/);
    if (ol) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (!inOl) { out.push("<ol>"); inOl = true; }
      out.push(`<li>${esc(ol[1])}</li>`);
      continue;
    }
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
    let body = esc(line)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
    out.push(`<p>${body}</p>`);
  }
  if (inUl) out.push("</ul>");
  if (inOl) out.push("</ol>");
  return out.join("\n");
}

function looksLikeHtml(s: string): boolean {
  return /<(h[1-6]|p|ul|ol|li|div|span|strong|em|code|pre|blockquote|br)\b[^>]*>/i.test(s);
}

/** Very small HTML → plain text for the DRAFT mailto: body. */
function htmlToPlain(html: string): string {
  return html
    .replace(/<br\s*\/?>(\n)?/gi, "\n")
    .replace(/<\/p>\s*<p[^>]*>/gi, "\n\n")
    .replace(/<\/(h\d|li|p|div)>/gi, "\n")
    .replace(/<li[^>]*>/gi, "• ")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function extractSubjectBody(text: string): { subject?: string; body: string } {
  const m = text.match(/^Subject:\s*(.+?)\r?\n\r?\n([\s\S]*)$/i);
  if (m) return { subject: m[1].trim(), body: m[2].trim() };
  return { body: text };
}

export default function CanvasEditor({
  messageId,
  content,
  sessionId,
  showDraftButton = false,
  onContentChange,
}: CanvasEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [current, setCurrent] = useState<string>(content);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  // Reading-level + emoji state (MiBuddy parity)
  const [showReadingLevel, setShowReadingLevel] = useState(false);
  const [activeReadingIndex, setActiveReadingIndex] = useState<number>(
    NON_CLICKABLE_INDEX,
  );
  const [emojiAction, setEmojiAction] = useState<"words" | "remove">("remove");
  const [panelLoading, setPanelLoading] = useState<null | "emoji" | "reading">(null);
  const [hasSelectedReadingLevel, setHasSelectedReadingLevel] = useState(false);

  const editorRef = useRef<HTMLDivElement>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const readingLevelRef = useRef<HTMLDivElement>(null);

  // Keep `current` in sync when a new message streams in
  useEffect(() => {
    if (!isEditing) setCurrent(content);
  }, [content, isEditing]);

  const resetReadingLevel = () => {
    setActiveReadingIndex(NON_CLICKABLE_INDEX);
    setHasSelectedReadingLevel(false);
  };

  // Close reading level panel on click outside (MiBuddy behaviour)
  useEffect(() => {
    if (!showReadingLevel && !hasSelectedReadingLevel) {
      resetReadingLevel();
    }
    if (!showReadingLevel && hasSelectedReadingLevel) {
      setHasSelectedReadingLevel(false);
    }
    const handleClickOutside = (event: MouseEvent) => {
      if (
        readingLevelRef.current &&
        !readingLevelRef.current.contains(event.target as Node)
      ) {
        setShowReadingLevel(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showReadingLevel]);

  // Set contentEditable innerHTML exactly once when entering edit mode.
  // We intentionally do NOT pass dangerouslySetInnerHTML in edit mode so that
  // React never resets innerHTML (and the cursor) on re-renders triggered by
  // saveState / panelLoading / emojiAction state changes.
  useLayoutEffect(() => {
    if (!isEditing || !editorRef.current) return;
    editorRef.current.innerHTML = looksLikeHtml(current) ? current : mdToHtml(current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing]);

  const _canvasCall = (body: Record<string, unknown>) => {
    const tokenMatch = document.cookie.match(/(?:^|;\s*)access_token_ag=([^;]*)/);
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (tokenMatch?.[1]) {
      headers["Authorization"] = `Bearer ${decodeURIComponent(tokenMatch[1])}`;
    }
    return fetch("/api/orchestrator/canvas/edit", {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify({ message_id: messageId, session_id: sessionId, ...body }),
    });
  };

  const persist = (html: string) => {
    setSaveState("saving");
    _canvasCall({ content: html, operation: "manual" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then(() => {
        setSaveState("saved");
        onContentChange?.(html);
        window.setTimeout(() => setSaveState("idle"), 1200);
      })
      .catch(() => setSaveState("idle"));
  };

  /** Reading-level rewrite via backend LLM. */
  const handleReadingLevel = async (index: number) => {
    if (index === NON_CLICKABLE_INDEX) return;
    setActiveReadingIndex(index);
    setHasSelectedReadingLevel(true);
    setShowReadingLevel(false);
    setPanelLoading("reading");
    try {
      const html = editorRef.current?.innerHTML ?? current;
      const res = await _canvasCall({
        content: html,
        operation: "reading_level",
        level: READING_LEVELS[index],
        emoji_action: emojiAction,
      });
      const data = await res.json();
      const newContent = data?.data?.[0]?.content;
      if (newContent) {
        if (editorRef.current) editorRef.current.innerHTML = newContent;
        setCurrent(newContent);
        onContentChange?.(newContent);
      }
    } catch (e) {
      console.error("reading_level failed:", e);
    } finally {
      setPanelLoading(null);
    }
  };

  /** Toggle add/remove emojis via backend. */
  const handleEmoji = async () => {
    const next: "words" | "remove" = emojiAction === "remove" ? "words" : "remove";
    setEmojiAction(next);
    setPanelLoading("emoji");
    try {
      const html = editorRef.current?.innerHTML ?? current;
      const res = await _canvasCall({
        content: html,
        operation: "emoji",
        emoji_action: next,
      });
      const data = await res.json();
      const newContent = data?.data?.[0]?.content;
      if (newContent) {
        if (editorRef.current) editorRef.current.innerHTML = newContent;
        setCurrent(newContent);
        onContentChange?.(newContent);
      }
    } catch (e) {
      console.error("emoji action failed:", e);
    } finally {
      setPanelLoading(null);
    }
  };

  // Drag-based reading level (MiBuddy's updateValueFromY)
  const updateValueFromY = (clientY: number) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    const offsetY = rect.bottom - clientY;
    const percentage = Math.min(Math.max(offsetY / rect.height, 0), 1);
    const newIndex = Math.round(percentage * (READING_LEVELS.length - 1));
    setActiveReadingIndex(newIndex);
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    updateValueFromY(e.clientY);
    const onMove = (ev: MouseEvent) => updateValueFromY(ev.clientY);
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const handleTrackClick = (e: React.MouseEvent) => {
    updateValueFromY(e.clientY);
  };

  const handleInput = (e: React.FormEvent<HTMLDivElement>) => {
    const html = e.currentTarget.innerHTML;
    // Do NOT call setCurrent here — it triggers a re-render which resets
    // dangerouslySetInnerHTML and moves the cursor to position 0 on every keystroke.
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(() => persist(html), 800);
  };

  const toggleEdit = () => {
    if (isEditing) {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
      const html = editorRef.current?.innerHTML ?? current;
      persist(html);
      setCurrent(html); // sync state now so view mode re-renders with the latest content
    }
    setIsEditing((v) => !v);
  };

  const handleDraft = () => {
    const plain = htmlToPlain(current || content);
    const { subject, body } = extractSubjectBody(plain);
    try {
      const mailto =
        `mailto:?subject=${encodeURIComponent(subject || "Draft")}` +
        `&body=${encodeURIComponent(body)}`;
      window.open(mailto);
    } catch {
      navigator.clipboard.writeText(body).then(() => {
        alert("Email body copied to clipboard. Paste it into a new email.");
      });
    }
  };

  const initialHtml = looksLikeHtml(current || "")
    ? (current || "")
    : mdToHtml(current || "");

  return (
    <div className="ac_canvas_wrapper">
      <div
        ref={editorRef}
        key={`${messageId}-${isEditing ? "edit" : "view"}`}
        className="ac_canvas_answer"
        contentEditable={isEditing}
        suppressContentEditableWarning
        onInput={handleInput}
        {...(!isEditing ? { dangerouslySetInnerHTML: { __html: initialHtml } } : {})}
      />
      <div className="ac_canvas_actions">
        {saveState !== "idle" && (
          <span className="ac_canvas_save_indicator">
            {saveState === "saving" ? "saving\u2026" : "saved \u2713"}
          </span>
        )}
        {showDraftButton && (
          <button
            type="button"
            className="ac_canvas_draft_btn"
            onClick={handleDraft}
            title="Open in a new email"
          >
            <Mail size={14} />
            DRAFT
          </button>
        )}
        <button
          type="button"
          className={`ac_canvas_btn ${isEditing ? "active" : ""}`}
          onClick={toggleEdit}
          title={isEditing ? "Save" : "Edit"}
        >
          {isEditing ? <Check size={14} /> : <Pencil size={14} />}
          {isEditing ? "Save" : "Edit"}
        </button>
      </div>

      {/* Floating panel — MiBuddy exact port */}
      {isEditing && (
        <div className="canvas_editor_wrapper">
          <div className="canvas_floating_panel">
            {/* Emoji toggle */}
            <div
              className="emoji_lavel canvas_icon_wrapper"
              onClick={() => { if (!panelLoading) handleEmoji(); }}
              style={{
                opacity: panelLoading === "emoji" ? 0.6 : 1,
                pointerEvents: panelLoading === "emoji" ? "none" : "auto",
                cursor: panelLoading === "emoji" ? "not-allowed" : "pointer",
              }}
            >
              <img
                src={emojiAction === "words" ? emojiActRemove : emojiActWord}
                alt={emojiAction}
              />
              {panelLoading === "emoji" && <div className="canvas_icon_loader" />}
            </div>

            {/* Reading level toggle */}
            <div
              className="reading_level canvas_icon_wrapper"
              onClick={() => {
                if (panelLoading) return;
                setShowReadingLevel((prev) => !prev);
              }}
              style={{
                opacity: panelLoading === "reading" ? 0.6 : 1,
                pointerEvents: panelLoading === "reading" ? "none" : "auto",
                cursor: panelLoading === "reading" ? "not-allowed" : "pointer",
              }}
            >
              <img src={readingLavelWhite} alt="reading level" />
              {panelLoading === "reading" && <div className="canvas_icon_loader" />}
            </div>
          </div>

          {/* Reading level vertical slider — MiBuddy exact port */}
          {showReadingLevel && (
            <div className="reading_level_wrapper" ref={readingLevelRef}>
              <div className="reading_level_label">
                {READING_LEVELS[activeReadingIndex]}
              </div>
              <div className="slider-wrapper reading_track">
                <div
                  className="slider-track"
                  ref={trackRef}
                  onMouseDown={handleMouseDown}
                  onClick={handleTrackClick}
                >
                  <div
                    className="slider-fill"
                    style={{
                      height: `${(activeReadingIndex / (READING_LEVELS.length - 1)) * 100}%`,
                    }}
                  />
                  <div
                    className="slider-thumb"
                    style={{
                      bottom: `${(activeReadingIndex / (READING_LEVELS.length - 1)) * 100}%`,
                    }}
                  />
                  {READING_LEVELS.map((_, index) => {
                    const isDisabled = index === NON_CLICKABLE_INDEX;
                    const isActive = index === activeReadingIndex;
                    return (
                      <div
                        key={index}
                        className={`track-dot ${isActive ? "active" : ""} ${isDisabled ? "disabled" : ""}`}
                        style={{
                          bottom: `${(index / (READING_LEVELS.length - 1)) * 100}%`,
                          pointerEvents: isDisabled ? "auto" : "auto",
                          opacity: isDisabled ? 1 : 1,
                          cursor: isDisabled ? "pointer" : "pointer",
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (panelLoading === "reading") return;
                          handleReadingLevel(index);
                          setShowReadingLevel(false);
                        }}
                      >
                        {isActive && (
                          <div className="reading_lavel_icon">
                            <img src={readingLavel} alt="reading level" />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

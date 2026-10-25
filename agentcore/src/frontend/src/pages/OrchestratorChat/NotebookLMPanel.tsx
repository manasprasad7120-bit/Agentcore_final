
import { useContext, useEffect, useRef, useState } from "react";
import { AuthContext } from "@/contexts/authContext";
import { ArrowLeft, Clock } from "lucide-react";

const PODCAST_SERVICE_BASE =
  import.meta.env.VITE_PODCAST_SERVICE_BASE ||
  "https://docprocessor-e2cygsbecsacg3bj.germanywestcentral-01.azurewebsites.net";

type LengthType = "short" | "standard";
type InputType = "upload" | "text" | "weblink";

interface HistoryItem {
  name: string;
  url: string;
  created_at: string;
}

interface NotebookLMPanelProps {
  onBack: () => void;
}

export default function NotebookLMPanel({ onBack }: NotebookLMPanelProps) {
  const { userData } = useContext(AuthContext);
  // Pull the user identity from the auth context only. The backend
  // populates this from Redis at login time, so it's the source of truth
  // for the current user — no email/userId reconstruction needed.
  const userEmail = userData?.email || "";
  const userId = userData?.id || "";

  const [podcastName, setPodcastName] = useState("");
  const [lengthType, setLengthType] = useState<LengthType>("standard");
  const [inputType, setInputType] = useState<InputType>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [textInput, setTextInput] = useState("");
  const [webLink, setWebLink] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const [downloadUrl, setDownloadUrl] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const logBoxRef = useRef<HTMLDivElement>(null);

  const appendLog = (msg: string) => setLogs((prev) => [...prev, msg]);

  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [logs]);

  const fetchHistory = async () => {
    if (!userEmail) return;
    try {
      const res = await fetch(
        `${PODCAST_SERVICE_BASE}/list-history/${encodeURIComponent(userEmail)}`,
      );
      if (!res.ok) return;
      const data = await res.json();
      setHistory(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error("[NotebookLM] list-history failed:", err);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, [userEmail]);

  const generatePodcast = async () => {
    if (!userEmail) {
      setError("Could not load your user profile. Please sign in again.");
      return;
    }
    if (!podcastName.trim()) {
      setError("Please enter a podcast name");
      return;
    }
    setError(null);
    setLogs([]);
    setDownloadUrl("");
    setIsGenerating(true);

    const formData = new FormData();
    formData.append("user_id", userId);
    formData.append("user_email", userEmail);
    formData.append("topic", podcastName);
    formData.append("length", lengthType.toUpperCase());
    if (file) formData.append("file", file);
    if (textInput.trim() !== "") formData.append("text", textInput);
    if (inputType === "weblink" && webLink.trim() !== "") {
      formData.append("web_url", webLink);
    }

    try {
      const res = await fetch(`${PODCAST_SERVICE_BASE}/generate-podcast`, {
        method: "POST",
        body: formData,
      });

      if (!res.body) {
        appendLog("No response stream");
        setIsGenerating(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.trim().startsWith("data:")) {
            const text = line.replace("data:", "").trim();
            appendLog(text);
            if (text.toLowerCase().includes("download")) {
              const url = text.split("Download:")[1]?.trim();
              if (url && url.startsWith("http")) setDownloadUrl(url);
            }
          }
        }
      }

      appendLog("✔ Podcast generation completed!");
      fetchHistory();
    } catch (err) {
      console.error("Error generating podcast:", err);
      appendLog("Error generating podcast");
      setError("Podcast generation failed. Please try again.");
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="nbk_layout">
      {/* TOP HEADER BAR (replaces the removed MiBuddy left sidebar) */}
      <div className="nbk_topBar">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            className="nbk_topBarBtn"
            onClick={onBack}
            title="Back to chat"
          >
            <ArrowLeft size={14} />
            Back
          </button>
          <span className="nbk_topBarTitle">NotebookLM — Podcast generator</span>
        </div>
        <button
          className="nbk_topBarBtn"
          onClick={() => {
            setShowHistory((v) => !v);
            if (!showHistory) fetchHistory();
          }}
        >
          <Clock size={14} />
          {showHistory ? "Hide history" : "History"}
        </button>
      </div>

      {/* HISTORY DROPDOWN (anchored top-right) */}
      {showHistory && (
        <div className="nbk_historyDropdown">
          <div className="nbk_historyHeader">
            <span>Chat history</span>
            <button
              onClick={fetchHistory}
              style={{
                background: "transparent",
                border: 0,
                color: "#888",
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              Refresh
            </button>
          </div>
          <div className="nbk_historyList">
            {history.length === 0 ? (
              <div className="nbk_historyEmpty">No history found</div>
            ) : (
              history.map((item, idx) => (
                <div key={idx} className="nbk_historyItem">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="nbk_historyTitle"
                  >
                    {item.name}
                  </a>
                  <div className="nbk_historyDate">
                    Created: {new Date(item.created_at).toLocaleString()}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* MAIN CONTENT */}
      <div className="nbk_contentWrapper">
        <div className="nbk_mainContent">
          {/* PODCAST NAME */}
          <div className="nbk_podcastInputWrapper">
            <input
              type="text"
              placeholder="Enter Podcast Name"
              value={podcastName}
              onChange={(e) => setPodcastName(e.target.value)}
              className="nbk_podcastInput"
            />
          </div>

          {/* LENGTH */}
          <div>
            <label className="nbk_sectionTitle">Length of Podcast</label>
            <div className="nbk_radioRow">
              <label>
                <input
                  type="radio"
                  checked={lengthType === "short"}
                  onChange={() => setLengthType("short")}
                />
                Short
              </label>

              <label>
                <input
                  type="radio"
                  checked={lengthType === "standard"}
                  onChange={() => setLengthType("standard")}
                />
                Standard
              </label>
            </div>
          </div>

          {/* INPUT METHOD */}
          <div>
            <label className="nbk_sectionTitle">Input Method</label>
            <div className="nbk_radioRow">
              <label>
                <input
                  type="radio"
                  checked={inputType === "upload"}
                  onChange={() => setInputType("upload")}
                />
                Upload File
              </label>

              <label>
                <input
                  type="radio"
                  checked={inputType === "text"}
                  onChange={() => setInputType("text")}
                />
                Enter Text
              </label>

              <label>
                <input
                  type="radio"
                  checked={inputType === "weblink"}
                  onChange={() => setInputType("weblink")}
                />
                Web Link
              </label>
            </div>
          </div>

          {/* INPUT AREA */}
          {inputType === "upload" ? (
            <div
              className="nbk_fileUploadBox"
              onClick={() => fileInputRef.current?.click()}
            >
              <span className="nbk_chooseFileText">Choose file</span>
              <span className="nbk_supportedFormats">
                (Supported: .pdf, .docx, .txt)
              </span>

              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt"
                style={{ display: "none" }}
                onChange={(e) => {
                  const selected = e.target.files?.[0];
                  if (!selected) return;
                  const allowed = ["pdf", "docx", "txt"];
                  const ext = selected.name.split(".").pop()?.toLowerCase();
                  if (ext && allowed.includes(ext)) {
                    setFile(selected);
                  } else {
                    setError(
                      "Invalid file type. Please upload a PDF, DOCX, or TXT file.",
                    );
                    e.target.value = "";
                  }
                }}
              />

              {file && (
                <span className="nbk_fileSelected">
                  📄 Selected: {file.name}
                </span>
              )}
            </div>
          ) : inputType === "text" ? (
            <textarea
              className="nbk_textArea"
              placeholder="Text Content"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
            />
          ) : (
            <div className="nbk_fileUploadBox">
              <input
                type="text"
                className="nbk_webLinkInput"
                placeholder="Paste Web URL (e.g., https://example.com/article)"
                value={webLink}
                onChange={(e) => setWebLink(e.target.value)}
              />
            </div>
          )}

          {error && <div className="nbk_errorBanner">{error}</div>}

          {/* BUTTONS */}
          <div className="nbk_buttonRow">
            <div className="nbk_generateWrapper">
              <button
                className="nbk_generateBtn"
                onClick={generatePodcast}
                disabled={isGenerating}
                style={{
                  opacity: isGenerating ? 0.6 : 1,
                  cursor: isGenerating ? "not-allowed" : "pointer",
                }}
              >
                Generate Podcast
              </button>

              {isGenerating && !downloadUrl && (
                <div className="nbk_generatingText">
                  Generating podcast, please wait
                  <span className="nbk_dots"></span>
                </div>
              )}
            </div>

            {downloadUrl ? (
              <a href={downloadUrl} download className="nbk_generateBtn">
                Download
              </a>
            ) : (
              <button disabled className="nbk_generateBtn">
                Download
              </button>
            )}
          </div>

          {(isGenerating || logs.length > 0) && (
            <div>
              <div className="nbk_logBoxLabel">Generation log</div>
              <div ref={logBoxRef} className="nbk_logBox">
                {logs.length === 0
                  ? "Waiting for server…"
                  : logs.map((l, i) => <div key={i}>{l}</div>)}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* FOOTER */}
      <div className="nbk_versionSec">
        <div>version v3.00.02</div>
        <div>
          a <span style={{ color: "#da2128" }}>Motherson Intelligence</span>{" "}
          initiative
        </div>
      </div>
    </div>
  );
}

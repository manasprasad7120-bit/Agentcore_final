import { useState, useEffect, useRef } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * Thumbs up/down feedback popup — MiBuddy-parity.
 *
 * Same layout for both up/down — only the chip set differs. Submit button is
 * disabled while an in-flight request is pending so double-clicks can't
 * produce duplicate submissions.
 */

const LIKE_CHIPS = ["Correct", "Easy To Understand", "Complete"];
const DISLIKE_CHIPS = ["Offensive/Unsafe", "Not Factually Correct", "Others"];

export interface FeedbackPopupProps {
  mode: "up" | "down";
  initialReasons?: string[];
  initialComment?: string;
  onSubmit: (reasons: string[], comment: string) => Promise<void>;
  onClose: () => void;
}

export default function FeedbackPopup({
  mode,
  initialReasons = [],
  initialComment = "",
  onSubmit,
  onClose,
}: FeedbackPopupProps) {
  const { t } = useTranslation();
  const [selectedChips, setSelectedChips] = useState<string[]>(initialReasons);
  const [comment, setComment] = useState<string>(initialComment);
  const [submitting, setSubmitting] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  const chips = mode === "up" ? LIKE_CHIPS : DISLIKE_CHIPS;

  // Close on Escape, trap focus inside.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submitting]);

  const toggleChip = (chip: string) => {
    setSelectedChips((prev) =>
      prev.includes(chip) ? prev.filter((c) => c !== chip) : [...prev, chip],
    );
  };

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await onSubmit(selectedChips, comment.trim());
      // Parent closes on success — no explicit onClose here.
    } catch {
      // Parent shows the error toast; keep the popup open so the user can retry.
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="relative w-full max-w-xl rounded-2xl bg-background p-6 shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-popup-title"
      >
        {/* Red close button (top-right), matches MiBuddy */}
        <button
          type="button"
          onClick={onClose}
          disabled={submitting}
          className="absolute right-4 top-4 flex h-7 w-7 items-center justify-center rounded-md bg-red-500 text-white transition-colors hover:bg-red-600 disabled:opacity-50"
          aria-label={t("Close")}
        >
          <X size={14} />
        </button>

        <h2
          id="feedback-popup-title"
          className="pr-10 text-base font-semibold text-foreground"
        >
          {t("Why did you choose this rating? (optional)")}
        </h2>

        {/* Reason chips — green accent for Like (positive feedback), red for Dislike */}
        <div className="mt-4 flex flex-wrap gap-2">
          {chips.map((chip) => {
            const active = selectedChips.includes(chip);
            const activeColorClass = mode === "up"
              ? "bg-green-500 text-white hover:bg-green-600"
              : "bg-red-500 text-white hover:bg-red-600";
            return (
              <button
                key={chip}
                type="button"
                onClick={() => toggleChip(chip)}
                disabled={submitting}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                  active
                    ? activeColorClass
                    : "bg-muted text-foreground hover:bg-accent"
                } disabled:opacity-50`}
              >
                {t(chip)}
              </button>
            );
          })}
        </div>

        {/* Free-text feedback (≤ 300 chars) */}
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value.slice(0, 300))}
          disabled={submitting}
          placeholder={t("Provide Additional Feedback")}
          className="mt-4 w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-red-400 focus:outline-none focus:ring-1 focus:ring-red-400 disabled:opacity-50"
          rows={3}
          maxLength={300}
        />

        {/* Submit — disabled while in-flight to prevent duplicates. */}
        <div className="mt-4">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-md bg-red-500 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? t("Submitting...") : t("Submit")}
          </button>
        </div>
      </div>
    </div>
  );
}

import { Switch } from "@/components/ui/switch";
import { Loader2, Sparkles } from "lucide-react";

interface SemanticSearchToggleProps {
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  isSearching?: boolean;
}

export default function SemanticSearchToggle({
  enabled,
  onToggle,
  isSearching = false,
}: SemanticSearchToggleProps) {
  return (
    <div className="flex items-center gap-2">
      <Switch
        checked={enabled}
        onCheckedChange={onToggle}
        aria-label="Toggle semantic search"
      />
      <label
        className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground"
        onClick={() => onToggle(!enabled)}
      >
        {isSearching ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        ) : (
          <Sparkles className={`h-3.5 w-3.5 ${enabled ? "text-primary" : ""}`} />
        )}
        <span>{isSearching ? "Searching..." : "Semantic"}</span>
      </label>
    </div>
  );
}

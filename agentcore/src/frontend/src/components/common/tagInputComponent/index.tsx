import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { useGetPredefinedTags } from "@/controllers/API/queries/tags/use-get-predefined-tags";
import type { TagItem } from "@/controllers/API/queries/tags/use-get-predefined-tags";
import { cn } from "@/utils/utils";

// Category colors for predefined tags
const CATEGORY_COLORS: Record<string, string> = {
  architecture: "bg-blue-100 text-blue-800 border-blue-200",
  use_case: "bg-purple-100 text-purple-800 border-purple-200",
  lifecycle: "bg-amber-100 text-amber-800 border-amber-200",
  domain: "bg-green-100 text-green-800 border-green-200",
  custom: "bg-zinc-100 text-zinc-800 border-zinc-200",
};

interface TagInputProps {
  selectedTags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  maxTags?: number;
  disabled?: boolean;
}

export default function TagInput({
  selectedTags,
  onChange,
  placeholder = "Add tags...",
  maxTags = 10,
  disabled = false,
}: TagInputProps) {
  const [inputValue, setInputValue] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const { data: predefinedTags } = useGetPredefinedTags();

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const addTag = (tagName: string) => {
    const normalized = tagName.trim().toLowerCase().replace(/[^a-z0-9-]/g, "-");
    if (
      !normalized ||
      normalized.length < 2 ||
      normalized.length > 30 ||
      selectedTags.includes(normalized) ||
      selectedTags.length >= maxTags
    ) {
      return;
    }
    onChange([...selectedTags, normalized]);
    setInputValue("");
  };

  const removeTag = (tagName: string) => {
    onChange(selectedTags.filter((t) => t !== tagName));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      if (inputValue.trim()) {
        addTag(inputValue);
      }
    }
    if (e.key === "Backspace" && !inputValue && selectedTags.length > 0) {
      removeTag(selectedTags[selectedTags.length - 1]);
    }
    if (e.key === "Escape") {
      setShowDropdown(false);
    }
  };

  // Filter suggestions: predefined tags not yet selected, matching input
  const suggestions: TagItem[] = (predefinedTags ?? []).filter(
    (tag) =>
      !selectedTags.includes(tag.name) &&
      tag.name.includes(inputValue.toLowerCase()),
  );

  // Group suggestions by category
  const groupedSuggestions = suggestions.reduce<Record<string, TagItem[]>>(
    (acc, tag) => {
      const cat = tag.category || "custom";
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(tag);
      return acc;
    },
    {},
  );

  const getCategoryLabel = (cat: string) => {
    const labels: Record<string, string> = {
      architecture: "Architecture",
      use_case: "Use Case",
      lifecycle: "Lifecycle",
      domain: "Domain",
      custom: "Custom",
    };
    return labels[cat] || cat;
  };

  const getTagColor = (tagName: string) => {
    const found = predefinedTags?.find((t) => t.name === tagName);
    if (found) return CATEGORY_COLORS[found.category] || CATEGORY_COLORS.custom;
    return CATEGORY_COLORS.custom;
  };

  return (
    <div ref={containerRef} className="relative w-full">
      {/* Selected tags + input */}
      <div
        className={cn(
          "flex flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-3 py-2 text-sm min-h-[40px] cursor-text",
          disabled && "opacity-50 cursor-not-allowed",
        )}
        onClick={() => !disabled && inputRef.current?.focus()}
      >
        {selectedTags.map((tag) => (
          <Badge
            key={tag}
            variant="outline"
            size="sm"
            className={cn("gap-1 pr-1", getTagColor(tag))}
          >
            {tag}
            {!disabled && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removeTag(tag);
                }}
                className="ml-0.5 rounded-full hover:bg-black/10 p-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </Badge>
        ))}
        {!disabled && selectedTags.length < maxTags && (
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value);
              setShowDropdown(true);
            }}
            onFocus={() => setShowDropdown(true)}
            onKeyDown={handleKeyDown}
            placeholder={selectedTags.length === 0 ? placeholder : ""}
            className="flex-1 min-w-[120px] bg-transparent outline-none text-sm placeholder:text-muted-foreground"
            disabled={disabled}
          />
        )}
      </div>

      {/* Dropdown */}
      {showDropdown && !disabled && Object.keys(groupedSuggestions).length > 0 && (
        <div className="absolute z-50 mt-1 w-full max-h-60 overflow-y-auto rounded-md border bg-popover p-1 shadow-md">
          {Object.entries(groupedSuggestions).map(([category, tags]) => (
            <div key={category}>
              <div className="px-2 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                {getCategoryLabel(category)}
              </div>
              {tags.map((tag) => (
                <button
                  key={tag.id}
                  type="button"
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground cursor-pointer"
                  onClick={() => {
                    addTag(tag.name);
                    setShowDropdown(false);
                  }}
                >
                  <Badge
                    variant="outline"
                    size="sm"
                    className={CATEGORY_COLORS[tag.category] || CATEGORY_COLORS.custom}
                  >
                    {tag.name}
                  </Badge>
                  {tag.description && (
                    <span className="text-xs text-muted-foreground truncate">
                      {tag.description}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
          {inputValue.trim() &&
            !suggestions.some((s) => s.name === inputValue.trim().toLowerCase()) && (
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent border-t"
                onClick={() => {
                  addTag(inputValue);
                  setShowDropdown(false);
                }}
              >
                <span className="text-muted-foreground">Create:</span>
                <Badge variant="outline" size="sm" className={CATEGORY_COLORS.custom}>
                  {inputValue.trim().toLowerCase()}
                </Badge>
              </button>
            )}
        </div>
      )}

      {/* Hint / Limit message */}
      {!disabled && selectedTags.length === 0 && !showDropdown && (
        <p className="mt-1 text-xs text-muted-foreground">
          Type to search or create custom tags. Press Enter or comma to add.
        </p>
      )}
      {!disabled && selectedTags.length >= maxTags && (
        <p className="mt-1 text-xs text-amber-600">
          Tag limit reached ({maxTags}/{maxTags})
        </p>
      )}
    </div>
  );
}

"use client";

import * as React from "react";
import { format, parse, isValid, startOfDay } from "date-fns";
import { Calendar } from "./calendar";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import { Button } from "./button";
import { cn } from "../../utils/utils";
import ForwardedIconComponent from "../common/genericIconComponent";

interface DateTimePickerProps {
  value: string; // ISO datetime-local string: "YYYY-MM-DDTHH:mm"
  onChange: (value: string) => void;
  min?: string;
  placeholder?: string;
  className?: string;
}

export function DateTimePicker({
  value,
  onChange,
  min,
  placeholder = "Pick a date & time",
  className,
}: DateTimePickerProps) {
  const [open, setOpen] = React.useState(false);

  const selectedDate = React.useMemo(() => {
    if (!value) return undefined;
    const d = new Date(value);
    return isValid(d) ? d : undefined;
  }, [value]);

  const minDate = React.useMemo(() => {
    if (!min) return undefined;
    const d = new Date(min);
    return isValid(d) ? startOfDay(d) : undefined;
  }, [min]);

  const hours = selectedDate ? format(selectedDate, "HH") : "00";
  const minutes = selectedDate ? format(selectedDate, "mm") : "00";

  function handleDateSelect(day: Date | undefined) {
    if (!day) return;
    const h = selectedDate ? selectedDate.getHours() : 0;
    const m = selectedDate ? selectedDate.getMinutes() : 0;
    const newDate = new Date(day);
    newDate.setHours(h, m, 0, 0);
    onChange(format(newDate, "yyyy-MM-dd'T'HH:mm"));
  }

  function handleTimeChange(type: "hours" | "minutes", val: string) {
    const num = parseInt(val, 10);
    if (isNaN(num)) return;
    const base = selectedDate ? new Date(selectedDate) : new Date();
    if (!selectedDate) {
      base.setSeconds(0, 0);
    }
    if (type === "hours") {
      base.setHours(Math.max(0, Math.min(23, num)));
    } else {
      base.setMinutes(Math.max(0, Math.min(59, num)));
    }
    onChange(format(base, "yyyy-MM-dd'T'HH:mm"));
  }

  function handleClear(e: React.MouseEvent) {
    e.stopPropagation();
    onChange("");
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className={cn(
            "w-full justify-start text-left font-normal h-10",
            !value && "text-muted-foreground",
            className,
          )}
        >
          <ForwardedIconComponent
            name="Calendar"
            className="mr-2 h-4 w-4 shrink-0 opacity-70"
          />
          {selectedDate ? (
            <span className="truncate">
              {format(selectedDate, "MMM d, yyyy")} at{" "}
              {format(selectedDate, "HH:mm")}
            </span>
          ) : (
            <span>{placeholder}</span>
          )}
          {value && (
            <span
              role="button"
              tabIndex={0}
              onClick={handleClear}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") handleClear(e as any);
              }}
              className="ml-auto shrink-0 rounded-full p-0.5 opacity-50 hover:opacity-100 transition-opacity"
            >
              <ForwardedIconComponent name="X" className="h-3.5 w-3.5" />
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={selectedDate}
          onSelect={handleDateSelect}
          disabled={minDate ? { before: minDate } : undefined}
          autoFocus
        />
        <div className="border-t border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <ForwardedIconComponent
              name="Clock"
              className="h-4 w-4 text-muted-foreground"
            />
            <span className="text-sm text-muted-foreground">Time</span>
            <div className="ml-auto flex items-center gap-1">
              <input
                type="number"
                min={0}
                max={23}
                value={hours}
                onChange={(e) => handleTimeChange("hours", e.target.value)}
                className="h-8 w-14 rounded-md border border-input bg-background px-2 text-center text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                aria-label="Hours"
              />
              <span className="text-sm font-medium text-muted-foreground">
                :
              </span>
              <input
                type="number"
                min={0}
                max={59}
                value={minutes}
                onChange={(e) => handleTimeChange("minutes", e.target.value)}
                className="h-8 w-14 rounded-md border border-input bg-background px-2 text-center text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                aria-label="Minutes"
              />
            </div>
          </div>
        </div>
        <div className="border-t border-border px-4 py-2 flex justify-end">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setOpen(false)}
            className="text-xs"
          >
            Done
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

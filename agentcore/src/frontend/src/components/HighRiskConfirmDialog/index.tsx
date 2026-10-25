import { ShieldAlert } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { McpRiskFinding } from "@/types/mcp";

type Props = {
  open: boolean;
  highFindings: McpRiskFinding[];
  actionLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
};

export default function HighRiskConfirmDialog({
  open,
  highFindings,
  actionLabel,
  onCancel,
  onConfirm,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onCancel(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-700 dark:text-red-400">
            <ShieldAlert className="h-5 w-5" />
            High-risk configuration detected
          </DialogTitle>
          <DialogDescription>
            The following high-severity findings were flagged for this MCP
            configuration. Proceeding will spawn the configured server (or
            submit it for approval) despite these risks.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-72 overflow-auto rounded-md border border-red-300 bg-red-50/60 p-3 dark:border-red-900 dark:bg-red-950/30">
          <ul className="flex flex-col gap-2 text-sm">
            {highFindings.map((f) => (
              <li key={f.rule_id + ":" + f.title} className="text-red-800 dark:text-red-300">
                <div className="font-medium">{f.title}</div>
                <div className="text-xs opacity-90">{f.detail}</div>
              </li>
            ))}
          </ul>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onCancel}>
            Cancel & edit
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            data-testid="high-risk-confirm-button"
          >
            I understand the risk - {actionLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

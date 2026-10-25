import { DialogClose } from "@radix-ui/react-dialog";
import { Trash2 } from "lucide-react";
import { Button } from "../../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/ui/dialog";

export default function DeleteConfirmationModal({
  children,
  onConfirm,
  description,
  asChild,
  open,
  setOpen,
  note = "",
  errorMessage,
  closeOnConfirm = true,
  loading = false,
}: {
  children?: JSX.Element;
  onConfirm: (e: React.MouseEvent<HTMLButtonElement, MouseEvent>) => void;
  description?: string;
  asChild?: boolean;
  open?: boolean;
  setOpen?: (open: boolean) => void;
  note?: string;
  errorMessage?: string;
  closeOnConfirm?: boolean;
  loading?: boolean;
}) {
  // While a delete is in flight, ignore Esc / overlay-click / X-button close
  // attempts so the user can't dismiss (and re-trigger) the action mid-request.
  const handleOpenChange = (nextOpen: boolean) => {
    if (loading && !nextOpen) return;
    setOpen?.(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild={asChild ?? true} tabIndex={-1}>
        {children ?? <></>}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            <div className="flex items-center">
              <Trash2
                className="h-6 w-6 pr-1 text-foreground"
                strokeWidth={1.5}
              />
              <span className="pl-2">Delete</span>
            </div>
          </DialogTitle>
        </DialogHeader>
        <span className="pb-3 text-sm">
          This will permanently delete the {description ?? "agent"}
          {note ? " " + note : ""}.<br />
          <br />
          This can't be undone.
        </span>
        {errorMessage ? (
          <div className="rounded-md border border-status-red/30 bg-error-background/40 px-3 py-2 text-sm text-error-foreground">
            {errorMessage}
          </div>
        ) : null}
        <DialogFooter>
          <DialogClose asChild>
            <Button
              onClick={(e) => e.stopPropagation()}
              className="mr-1"
              variant="outline"
              disabled={loading}
              data-testid="btn_cancel_delete_confirmation_modal"
            >
              Cancel
            </Button>
          </DialogClose>
          {closeOnConfirm && !loading ? (
            <DialogClose asChild>
              <Button
                type="submit"
                variant="destructive"
                onClick={(e) => {
                  onConfirm(e);
                }}
                data-testid="btn_delete_delete_confirmation_modal"
              >
                Delete
              </Button>
            </DialogClose>
          ) : (
            <Button
              type="submit"
              variant="destructive"
              loading={loading}
              onClick={(e) => {
                onConfirm(e);
              }}
              data-testid="btn_delete_delete_confirmation_modal"
            >
              Delete
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

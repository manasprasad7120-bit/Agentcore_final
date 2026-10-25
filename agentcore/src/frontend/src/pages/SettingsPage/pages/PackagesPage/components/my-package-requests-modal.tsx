import { useMemo } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { useGetMyPackageRequests } from "@/controllers/API/queries/packages/use-package-requests";

interface MyPackageRequestsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatStatus(status: string) {
  if (status === "pending") return "Pending";
  if (status === "approved") return "Approved";
  if (status === "rejected") return "Rejected";
  if (status === "deployed") return "Deployed";
  if (status === "cancelled") return "Cancelled";
  return status;
}

function statusBadgeClass(status: string) {
  if (status === "approved" || status === "deployed") return "border-green-500/50 text-green-600";
  if (status === "rejected" || status === "cancelled") return "border-red-500/50 text-red-600";
  return "border-yellow-500/50 text-yellow-600";
}

export default function MyPackageRequestsModal({
  open,
  onOpenChange,
}: MyPackageRequestsModalProps) {
  const { data: requests = [], isLoading } = useGetMyPackageRequests(undefined, {
    enabled: open,
  });

  const sorted = useMemo(
    () =>
      [...requests].sort(
        (a, b) => new Date(b.requested_at).getTime() - new Date(a.requested_at).getTime(),
      ),
    [requests],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <div className="space-y-2">
          <h2 className="text-lg font-semibold">My Package Requests</h2>
          <p className="text-sm text-muted-foreground">
            Track approval status and deployment decisions for your package requests.
          </p>
        </div>

        <div className="mt-4 overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full">
            <thead>
              <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                <th className="px-4 py-3 text-left font-medium">Service</th>
                <th className="px-4 py-3 text-left font-medium">Package</th>
                <th className="px-4 py-3 text-left font-medium">Requested Version</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Requested At</th>
                <th className="px-4 py-3 text-left font-medium">Review Notes</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-sm text-muted-foreground">
                    Loading requests...
                  </td>
                </tr>
              ) : sorted.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-sm text-muted-foreground">
                    No package requests submitted yet.
                  </td>
                </tr>
              ) : (
                sorted.map((request) => (
                  <tr
                    key={request.id}
                    className="border-b last:border-0 transition-colors hover:bg-muted/30"
                  >
                    <td className="px-4 py-3 text-sm">{request.service_name}</td>
                    <td className="px-4 py-3 font-mono text-sm">{request.package_name}</td>
                    <td className="px-4 py-3 text-sm">{request.requested_version}</td>
                    <td className="px-4 py-3 text-sm">
                      <Badge variant="outline" size="sm" className={statusBadgeClass(request.status)}>
                        {formatStatus(request.status)}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">
                      {new Date(request.requested_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">
                      {request.review_comments || request.deployment_notes || "-"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </DialogContent>
    </Dialog>
  );
}

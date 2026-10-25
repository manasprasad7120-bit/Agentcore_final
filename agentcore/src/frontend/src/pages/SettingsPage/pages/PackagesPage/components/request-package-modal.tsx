import { useEffect, useMemo, useState } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreatePackageRequest } from "@/controllers/API/queries/packages/use-package-requests";
import useAlertStore from "@/stores/alertStore";

interface RequestPackageModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  services: string[];
}

export default function RequestPackageModal({
  open,
  onOpenChange,
  services,
}: RequestPackageModalProps) {
  const [serviceName, setServiceName] = useState("backend");
  const [packageName, setPackageName] = useState("");
  const [requestedVersion, setRequestedVersion] = useState("");
  const [justification, setJustification] = useState("");
  const [justificationError, setJustificationError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const createRequestMutation = useCreatePackageRequest();
  const setSuccessData = useAlertStore((s) => s.setSuccessData);
  const setErrorData = useAlertStore((s) => s.setErrorData);

  const serviceOptions = useMemo(
    () => services.filter((service) => service !== "all"),
    [services],
  );

  useEffect(() => {
    if (open && serviceOptions.length > 0 && !serviceOptions.includes(serviceName)) {
      setServiceName(serviceOptions[0]);
    }
  }, [open, serviceOptions, serviceName]);

  const resetForm = () => {
    setPackageName("");
    setRequestedVersion("");
    setJustification("");
    setJustificationError("");
  };

  const handleClose = () => {
    onOpenChange(false);
    resetForm();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!packageName.trim() || !requestedVersion.trim() || !justification.trim()) {
      setErrorData({
        title: "Package name, version, and justification are required.",
      });
      if (!justification.trim()) setJustificationError("Justification is required.");
      return;
    }
    if (justification.trim().length < 5) {
      setJustificationError("Justification must be at least 5 characters.");
      return;
    }
    setIsSubmitting(true);
    try {
      await createRequestMutation.mutateAsync({
        service_name: serviceName || serviceOptions[0] || "backend",
        package_name: packageName.trim(),
        requested_version: requestedVersion.trim(),
        justification: justification.trim(),
      });
      setSuccessData({
        title: "Package request submitted for approval.",
      });
      handleClose();
    } catch (err: any) {
      setErrorData({
        title: "Failed to submit package request.",
        list: [err?.message ?? String(err)],
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold">Request Package</h2>
            <p className="text-sm text-muted-foreground">
              Requests go to Review & Approval for root-admin action.
            </p>
          </div>

          <div className="space-y-2">
            <Label>Service</Label>
            <Select value={serviceName} onValueChange={setServiceName}>
              <SelectTrigger className="w-full bg-card">
                <SelectValue placeholder="Select service" />
              </SelectTrigger>
              <SelectContent>
                {serviceOptions.map((service) => (
                  <SelectItem key={service} value={service}>
                    {service}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Package Name</Label>
            <Input
              value={packageName}
              onChange={(e) => setPackageName(e.target.value)}
              placeholder="fastapi"
            />
          </div>

          <div className="space-y-2">
            <Label>Requested Version</Label>
            <Input
              value={requestedVersion}
              onChange={(e) => setRequestedVersion(e.target.value)}
              placeholder=">=0.115.0,<1.0.0"
            />
          </div>

          <div className="space-y-2">
            <Label>Justification</Label>
            <Textarea
              value={justification}
              onChange={(e) => {
                setJustification(e.target.value);
                if (justificationError) setJustificationError("");
              }}
              placeholder="Business justification for this package"
              className={`min-h-[110px]${justificationError ? " border-destructive focus-visible:ring-destructive" : ""}`}
            />
            {justificationError && (
              <p className="text-sm text-destructive">{justificationError}</p>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" type="button" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || createRequestMutation.isPending}>
              {isSubmitting ? "Submitting..." : "Submit Request"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

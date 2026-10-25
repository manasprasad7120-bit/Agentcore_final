import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/cjs/styles/prism";
import { useDarkStore } from "@/stores/darkStore";
import useAlertStore from "@/stores/alertStore";
import useAgentStore from "@/stores/agentStore";
import IconComponent from "../../components/common/genericIconComponent";
import { Button } from "../../components/ui/button";
import getWidgetCode from "../apiModal/utils/get-widget-code";
import BaseModal from "../baseModal";

interface EmbedModalProps {
  open: boolean;
  setOpen: (open: boolean) => void;
  agentId: string;
  agentName: string;
  environment?: "dev" | "uat" | "prod";
  version?: string;
  isAuth: boolean;
  tweaksBuildedObject: {};
  activeTweaks: boolean;
}

export default function EmbedModal({
  open,
  setOpen,
  agentId,
  agentName,
  environment,
  version,
  isAuth,
  tweaksBuildedObject,
  activeTweaks,
}: EmbedModalProps) {
  const isDark = useDarkStore((state) => state.dark);
  const activePublishedVersion = useAgentStore(
    (state) => state.activePublishedVersion,
  );
  const [isCopied, setIsCopied] = useState<boolean>(false);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const widgetProps = {
    agentId: agentId,
    agentName: agentName,
    isAuth: isAuth,
    env: environment ?? activePublishedVersion?.environment ?? "dev",
    version: version ?? activePublishedVersion?.versionNumber ?? "v1",
    tweaksBuildedObject: tweaksBuildedObject,
    activeTweaks: activeTweaks,
  };
  const embedCode = getWidgetCode({ ...widgetProps, copy: false });
  const copyCode = getWidgetCode({ ...widgetProps, copy: true });
  const copyToClipboard = () => {
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
      return;
    }

    navigator.clipboard.writeText(copyCode).then(() => {
      setIsCopied(true);
      setSuccessData({ title: "Widget code copied" });

      setTimeout(() => {
        setIsCopied(false);
      }, 2000);
    });
  };

  const downloadWidgetCode = () => {
    const htmlContent = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${agentName} Widget</title>
  </head>
  <body>
${copyCode}
  </body>
</html>`;

    const safeName = (agentName || "agent")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    const blob = new Blob([htmlContent], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${safeName || "agent"}-widget.html`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setSuccessData({ title: "Widget file downloaded" });
  };

  return (
    <BaseModal open={open} setOpen={setOpen} size="retangular">
      <BaseModal.Header>
        <div className="flex items-center gap-2 text-base font-semibold">
          <IconComponent name="Columns2" className="icon-size" />
          Export as Widget
        </div>
      </BaseModal.Header>
      <BaseModal.Content className="">
        <div className="relative flex h-full w-full">
          <div className="absolute right-2 top-2 z-10 flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={downloadWidgetCode}
              data-testid="btn-download-widget"
              className="group"
            >
              <IconComponent
                name="Download"
                className="!h-5 !w-5 text-muted-foreground"
              />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={copyToClipboard}
              data-testid="btn-copy-code"
              className="group"
            >
              {isCopied ? (
                <IconComponent
                  name="Check"
                  className="h-5 w-5 text-muted-foreground"
                />
              ) : (
                <IconComponent
                  name="Copy"
                  className="!h-5 !w-5 text-muted-foreground"
                />
              )}
            </Button>
          </div>
          <SyntaxHighlighter
            showLineNumbers={true}
            wrapLongLines={true}
            language="html"
            style={isDark ? oneDark : oneLight}
            className="!mt-0 h-full w-full overflow-scroll !rounded-b-md border border-border text-left !custom-scroll"
          >
            {embedCode}
          </SyntaxHighlighter>
        </div>
      </BaseModal.Content>
    </BaseModal>
  );
}

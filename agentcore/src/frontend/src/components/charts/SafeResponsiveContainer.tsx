import { useEffect, useRef, useState, type CSSProperties } from "react";
import { ResponsiveContainer, type ResponsiveContainerProps } from "recharts";

type SafeResponsiveContainerProps = ResponsiveContainerProps & {
  minWidth?: number;
  minHeight?: number;
  className?: string;
  style?: CSSProperties;
};

function resolveSize(value: ResponsiveContainerProps["width" | "height"]) {
  if (typeof value === "number" || typeof value === "string") return value;
  return "100%";
}

export function SafeResponsiveContainer({
  width = "100%",
  height = "100%",
  minWidth = 1,
  minHeight = 1,
  className,
  style,
  children,
  ...rest
}: SafeResponsiveContainerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const updateReady = () => {
      const { width: w, height: h } = el.getBoundingClientRect();
      setReady(w > 0 && h > 0);
    };

    updateReady();
    const ro = new ResizeObserver(updateReady);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        width: resolveSize(width),
        height: resolveSize(height),
        minWidth,
        minHeight,
        ...style,
      }}
    >
      {ready && (
        <ResponsiveContainer width="100%" height="100%" {...rest}>
          {children}
        </ResponsiveContainer>
      )}
    </div>
  );
}


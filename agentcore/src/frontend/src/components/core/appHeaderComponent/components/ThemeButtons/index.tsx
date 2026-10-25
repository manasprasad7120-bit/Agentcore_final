import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import useTheme from "@/customization/hooks/use-custom-theme";

type ThemeOption = "light" | "dark" | "system";

export const ThemeButtons = () => {
  const { systemTheme, dark, setThemePreference } = useTheme();
  const [selectedTheme, setSelectedTheme] = useState<ThemeOption>(
    systemTheme ? "system" : dark ? "dark" : "light",
  );
  const [hasInteracted, setHasInteracted] = useState(false); // Track user interaction

  useEffect(() => {
    if (!hasInteracted) {
      // Set initial theme without triggering the animation
      if (systemTheme) {
        setSelectedTheme("system");
      } else if (dark) {
        setSelectedTheme("dark");
      } else {
        setSelectedTheme("light");
      }
    }
  }, [systemTheme, dark, hasInteracted]);

  const handleThemeChange = (theme: ThemeOption) => {
    setHasInteracted(true); // Mark that a button has been clicked
    setSelectedTheme(theme);
    setThemePreference(theme);
  };

  const options: Array<{
    testId: string;
    value: ThemeOption;
  }> = [
    { value: "light", testId: "menu_light_button" },
    { value: "dark", testId: "menu_dark_button" },
    { value: "system", testId: "menu_system_button" },
  ];

  const activeIndex = options.findIndex((option) => option.value === selectedTheme);

  return (
    <div className="relative inline-grid h-8 grid-cols-3 rounded-full border border-border bg-muted/40 p-0.5 shadow-sm">
      <div
        className={`absolute bottom-0.5 left-0.5 top-0.5 w-[calc((100%-0.25rem)/3)] rounded-full bg-amber-400 shadow-sm dark:bg-purple-500 ${
          hasInteracted ? "transition-all duration-300" : ""
        }`}
        style={{
          transform: `translateX(${Math.max(activeIndex, 0) * 100}%)`,
        }}
      />

      {options.map((option) => (
        <Button
          key={option.value}
          unstyled
          className={`relative z-10 inline-flex h-7 w-7 items-center justify-center rounded-full text-foreground transition-colors ${
            selectedTheme === option.value
              ? "text-amber-950 dark:text-white"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => handleThemeChange(option.value)}
          data-testid={option.testId}
          id={option.testId}
          aria-label={`${option.value} theme`}
          title={`${option.value} theme`}
        >
          {option.value === "light" ? (
            <Sun className="h-4 w-4" strokeWidth={2} />
          ) : option.value === "dark" ? (
            <Moon className="h-4 w-4" strokeWidth={2} />
          ) : (
            <Monitor className="h-4 w-4" strokeWidth={2} />
          )}
        </Button>
      ))}
    </div>
  );
};

export default ThemeButtons;

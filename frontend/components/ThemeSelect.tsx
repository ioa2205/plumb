"use client";

import { useEffect, useState } from "react";

type Theme = "system" | "day" | "night";
const choices = ["system", "day", "night"] as const;
const storageKey = "plumb-workbench-theme";

export function ThemeSelect() {
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved === "day" || saved === "night") {
        setTheme(saved);
        document.documentElement.dataset.theme = saved;
      }
    } catch { /* System theme remains usable when storage is unavailable. */ }
  }, []);

  function select(value: Theme) {
    setTheme(value);
    if (value === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = value;
    try { localStorage.setItem(storageKey, value); } catch { /* Still changes this page. */ }
  }

  return <fieldset className="theme-select">
    <legend>Appearance</legend>
    <div>{choices.map(value => <label key={value}>
      <input type="radio" name="theme" value={value} checked={theme === value} onChange={() => select(value)} />
      <span>{value === "system" ? "System" : value === "day" ? "Day" : "Night"}</span>
    </label>)}</div>
  </fieldset>;
}

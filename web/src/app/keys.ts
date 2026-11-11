import { useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { placeStore } from "../features/write/place";
import { collapseAll, treePick } from "./shell/folderTree";

function inField(el: Element | null) {
  return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || (el as HTMLElement).isContentEditable);
}

/** Клавиши оболочки (разд. 5.13): по event.code, работают в русской раскладке. */
export function useHotkeys(h: { focusSearch: () => void }) {
  const navigate = useNavigate();
  useEffect(() => {
    let g = false;
    let gTimer: ReturnType<typeof setTimeout> | undefined;
    function onKey(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.code === "KeyK") {
        e.preventDefault();
        h.focusSearch();
        return;
      }
      if (mod && e.code === "Comma") {
        e.preventDefault();
        navigate({ to: "/settings" });
        return;
      }
      if (inField(document.activeElement) || mod || e.altKey) return;
      if (e.code === "Slash") {
        e.preventDefault();
        h.focusSearch();
      } else if (e.code === "KeyN") {
        e.preventDefault();
        placeStore.openQuick(true);
      } else if (e.code === "KeyC" && e.shiftKey) {
        // Shift+C — свернуть все папки в панели
        e.preventDefault();
        collapseAll();
      } else if (e.code === "Escape") {
        treePick.clear();
      } else if (e.code === "KeyG") {
        g = true;
        clearTimeout(gTimer);
        gTimer = setTimeout(() => (g = false), 1200);
      } else if (g) {
        g = false;
        if (e.code === "KeyH") navigate({ to: "/" });
        if (e.code === "KeyR") navigate({ to: "/review" });
        if (e.code === "KeyC") navigate({ to: "/changes" });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [h, navigate]);
}

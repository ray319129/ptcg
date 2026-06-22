// 全域狀態：使用者身分與主題。用 zustand + localStorage 持久化。
import { create } from "zustand";

type Theme = "dark" | "light";
export type PriceLang = "tw" | "jp"; // 繁體中文版 / 日文版卡價

interface AppState {
  userId: string;
  username: string;
  theme: Theme;
  priceLang: PriceLang;
  login: (userId: string, username: string) => void;
  logout: () => void;
  toggleTheme: () => void;
  setPriceLang: (l: PriceLang) => void;
}

function initialTheme(): Theme {
  const saved = localStorage.getItem("theme") as Theme | null;
  return saved ?? "dark";
}

export const useApp = create<AppState>((set, get) => ({
  userId: localStorage.getItem("user_id") ?? "",
  username: localStorage.getItem("username") ?? "",
  theme: initialTheme(),
  priceLang: (localStorage.getItem("price_lang") as PriceLang) ?? "tw",
  login: (userId, username) => {
    localStorage.setItem("user_id", userId);
    localStorage.setItem("username", username);
    set({ userId, username });
  },
  logout: () => {
    localStorage.removeItem("user_id");
    localStorage.removeItem("username");
    set({ userId: "", username: "" });
  },
  toggleTheme: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", next);
    document.documentElement.setAttribute("data-theme", next);
    set({ theme: next });
  },
  setPriceLang: (l) => {
    localStorage.setItem("price_lang", l);
    set({ priceLang: l });
  },
}));

// 啟動時把主題寫到 <html data-theme>
document.documentElement.setAttribute("data-theme", initialTheme());

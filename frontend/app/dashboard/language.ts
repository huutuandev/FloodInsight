"use client";
import { createContext, useContext } from "react";
import { vi } from "./vi";

export type Language = "vi" | "en";
export const LanguageContext = createContext<Language>("vi");
export const useLanguage = () => useContext(LanguageContext);
export function useText() {
  const language = useLanguage();
  return (text: string) => language === "vi" ? vi[text] ?? text : text;
}

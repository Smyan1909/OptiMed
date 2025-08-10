import type { Locale } from "./config";

export async function getMessages(locale: Locale) {
  switch (locale) {
    case "sv":
      return (await import("./sv.json")).default;
    case "en":
    default:
      return (await import("./en.json")).default;
  }
}



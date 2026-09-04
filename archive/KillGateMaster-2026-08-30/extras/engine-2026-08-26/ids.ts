export function nowIso(at?: Date): string {
  return (at ?? new Date()).toISOString();
}

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `kg_${Math.random().toString(16).slice(2)}_${Date.now().toString(16)}`;
}

export function identityKey(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase();
}

export function normalizeText(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

export function canonicalPrice(value: number | string): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "0";
  let s = n.toFixed(8);
  s = s.replace(/\.?0+$/, "");
  return s === "-0" ? "0" : s;
}

export function domainFromUrl(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

import { describe, expect, it } from "vitest";
import { companyOf, COMPANY_ORDER } from "./consoleCompanies";

describe("companyOf", () => {
  it.each([
    ["NES", "Nintendo"],
    ["Genesis/Mega Drive", "Sega"],
    ["PS1", "Sony"],
    ["Atari 2600", "Atari"],
    ["Neo Geo Pocket", "SNK"],
    ["Pc Fx", "NEC"],
  ] as const)("maps %s to %s", (consoleName, company) => {
    expect(companyOf(consoleName)).toBe(company);
  });

  it("falls back to Otros for an unmapped console", () => {
    expect(companyOf("Some New Console")).toBe("Otros");
  });

  it("only returns companies that are part of COMPANY_ORDER", () => {
    expect(COMPANY_ORDER).toContain(companyOf("NES"));
    expect(COMPANY_ORDER).toContain(companyOf("Some New Console"));
  });
});

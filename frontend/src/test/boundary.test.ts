import { readFileSync, readdirSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = join(process.cwd(), "src");
const forbiddenModules = ["candidature", "application_assist", "worker", "firebase", "preparer"];
const forbiddenCommands = ["candidature", "application_assist", "worker", "firebase", "prepare", "preparer"];

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return [".ts", ".tsx", ".js", ".jsx"].includes(extname(entry.name)) ? [path] : [];
  });
}

describe("frontière de l'édition publique", () => {
  it("refuse les modules et commandes privées sans censurer le texte informatif", () => {
    const violations: string[] = [];

    for (const path of sourceFiles(sourceRoot)) {
      const source = readFileSync(path, "utf8");
      const imports = [...source.matchAll(/(?:from\s+|import\s*\(|require\s*\()\s*["']([^"']+)["']/g)];
      for (const match of imports) {
        if (forbiddenModules.some((name) => match[1].toLowerCase().includes(name))) {
          violations.push(`${relative(sourceRoot, path)}: import ${match[1]}`);
        }
      }
      const identifiers = [...source.matchAll(/\b([A-Za-z_$][\w$]*)\s*\(/g)].map((match) =>
        match[1].toLowerCase(),
      );
      for (const command of forbiddenCommands) {
        if (identifiers.includes(command)) {
          violations.push(`${relative(sourceRoot, path)}: command ${command}`);
        }
      }
    }

    expect(violations).toEqual([]);
  });
});

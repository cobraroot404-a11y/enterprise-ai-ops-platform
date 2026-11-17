// Builds the UI, then starts the isolated, seeded end-to-end stack (see scripts/e2e_stack.py). Stops it when terminated.
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const win = process.platform === "win32";
const venvPython = path.join(root, ".venv", win ? "Scripts/python.exe" : "bin/python");
const python = process.env.E2E_PYTHON ?? (existsSync(venvPython) ? venvPython : "python");

const build = spawnSync("npm", ["run", "build"], { cwd: path.join(root, "frontend"), stdio: "inherit", shell: win });
if (build.status !== 0) process.exit(build.status ?? 1);

const args = [path.join(root, "scripts", "e2e_stack.py"), ...(process.env.E2E_REAL_AI === "1" ? ["--real-ai"] : [])];
const child = spawn(python, args, { cwd: root, stdio: "inherit" });
const stop = () => { child.kill(win ? undefined : "SIGTERM"); };
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
process.on("exit", stop);
child.on("exit", (code) => process.exit(code ?? 0));

import { defineConfig } from "@playwright/test";

const ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const E2E = `${ROOT}/.e2e`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: { baseURL: "http://localhost:5174" },
  webServer: [
    {
      command: [
        `rm -rf ${E2E} && mkdir -p ${E2E}/data`,
        `${ROOT}/backend/.venv/bin/python ${ROOT}/backend/tests/make_sample_pdf.py ${E2E}/sample.pdf`,
        `cd ${ROOT}/backend && PAPER_NOTES_DATA=${E2E}/data PAPER_NOTES_CLAUDE_BIN=${ROOT}/backend/tests/fake_cli.py ` +
          `PAPER_NOTES_CODEX_BIN=${ROOT}/backend/tests/fake_cli.py FAKE_AI_RESPONSES=${ROOT}/frontend/e2e/fixtures/ai-responses.json ` +
          `FAKE_AI_STATE=${E2E}/state .venv/bin/uvicorn paper_notes.main:app --port 8765`,
      ].join(" && "),
      url: "http://127.0.0.1:8765/api/health",
      reuseExistingServer: false,
    },
    {
      command: "VITE_API_TARGET=http://127.0.0.1:8765 npx vite --port 5174 --strictPort",
      url: "http://localhost:5174",
      reuseExistingServer: false,
    },
  ],
});

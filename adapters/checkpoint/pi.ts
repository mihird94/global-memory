import { execFile } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export default function checkpointPilot(pi: ExtensionAPI) {
  const python = process.env.GM_CHECKPOINT_PYTHON;
  if (process.env.GM_CHECKPOINT_PILOT !== "1" || !python || !process.env.GM_HOME) return;

  type HookResult = { hookSpecificOutput?: { additionalContext?: string }; reminder?: string };
  type EventFields = { prompt?: string; source?: string; can_continue?: boolean };
  function hook(event: string, ctx: ExtensionContext, options: EventFields = {}): Promise<HookResult> {
    return new Promise((resolve) => {
      const args = ["-m", "gm.checkpoint_hooks", "--surface", "pi-cli"];
      if (process.env.GM_CHECKPOINT_REMINDER === "1") args.push("--reminder");
      const child = execFile(python!, args,
        { timeout: 3000, maxBuffer: 64 * 1024 }, (error, stdout) => {
          if (!error) {
            try {
              return resolve(JSON.parse(stdout));
            } catch { /* Invalid output must not interrupt the agent. */ }
          }
          resolve({});
        });
      child.stdin?.on("error", () => {});
      child.stdin?.end(JSON.stringify({
        hook_event_name: event,
        session_id: ctx.sessionManager.getSessionId(),
        cwd: ctx.cwd,
        ...options,
      }));
    });
  }

  let startup = "";
  pi.on("session_start", async (event, ctx) => {
    const result = await hook("session_start", ctx, { source: event.reason });
    startup = result.hookSpecificOutput?.additionalContext ?? "";
  });
  pi.on("before_agent_start", async (event, ctx) => {
    if (event.messageType !== "user") return;
    const result = await hook("before_agent_start", ctx, { prompt: event.prompt });
    const context = result.hookSpecificOutput?.additionalContext;
    const content = [startup, context].filter(Boolean).join("\n\n");
    startup = "";
    if (content) return { message: { customType: "brain-checkpoint", content, display: false } };
  });
  pi.on("agent_before_settle", async (event, ctx) => {
    const result = await hook("agent_before_settle", ctx, {
      can_continue: event.outcome === "completed" && !event.continue,
    });
    if (result.reminder) {
      return { continue: true, entries: [...event.entries, {
        type: "custom_message", customType: "brain-checkpoint", content: result.reminder, display: false,
      }] };
    }
  });
  pi.on("agent_settled", async (_event, ctx) => {
    await hook("agent_settled", ctx);
  });
  pi.on("session_before_compact", async (_event, ctx) => {
    await hook("session_before_compact", ctx);
  });
}

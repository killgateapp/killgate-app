import { GATE_COPY, THRESHOLDS, type AdaptiveGateEvaluation, type SystemState } from "@/lib/killgate/types.ts";
import { activeIdeaProfile, profileLabel } from "@/lib/killgate/evaluator.ts";
import { cn } from "@/lib/utils";

const toneSurface: Record<string, string> = {
  go: "border-go/40 bg-go/10",
  wait: "border-border-strong bg-card",
  pivot: "border-pivot/40 bg-pivot/10",
  kill: "border-kill/40 bg-kill/10",
  stop: "border-border-strong bg-card-2",
};

const toneText: Record<string, string> = {
  go: "text-go",
  wait: "text-foreground",
  pivot: "text-pivot",
  kill: "text-kill",
  stop: "text-muted",
};

function Meter({
  label,
  value,
  max,
}: {
  label: string;
  value: number;
  max: number;
}) {
  const ratio = max > 0 ? Math.min(1, value / max) : 0;
  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-muted">{label}</span>
        <span className="font-mono tabular-nums text-foreground">
          {value}/{max}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-card-2">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-200"
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
    </div>
  );
}

export function GateBoard({
  state,
  evaluation,
}: {
  state: SystemState;
  evaluation: AdaptiveGateEvaluation;
}) {
  const copy = GATE_COPY[evaluation.recommendation];
  const profile = activeIdeaProfile(state);
  const thresholds = profile ? THRESHOLDS[profile.systemProfile] : null;
  const c = evaluation.evidenceCompleteness;

  return (
    <section className={cn("rounded-xl border p-5 sm:p-7", toneSurface[copy.tone])}>
      <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted">
        Evaluator {evaluation.evaluatorVersion}
        {profile ? ` · ${profileLabel(profile.systemProfile)}` : ""}
        {state.archivedAt ? " · archived" : ""}
      </p>
      <h1 className={cn("mt-3 font-display text-3xl", toneText[copy.tone])}>
        {copy.label}
      </h1>
      <p className="mt-3 max-w-2xl text-base text-foreground/90">
        {evaluation.nextAction.instruction}
      </p>
      <p className="mt-2 max-w-full font-mono text-xs uppercase tracking-[0.16em] text-muted break-words">
        Next · {evaluation.nextAction.actionType.replaceAll("_", " ")}
      </p>

      {thresholds ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Meter
            label="Qualified buyers"
            value={Number(c.qualified_buyer_count ?? 0)}
            max={thresholds.minBuyers}
          />
          <Meter
            label="Strong pain"
            value={Number(c.strong_pain_count ?? 0)}
            max={thresholds.minStrongPain}
          />
          <Meter
            label="Verified sources"
            value={Number(c.verified_source_count ?? 0)}
            max={3}
          />
          <Meter
            label={state.phase === "build" ? "Hands-on trials" : "Commercial signals"}
            value={
              state.phase === "build"
                ? Number(c.hands_on_trial_count ?? 0)
                : Number(
                    c.combined_commercial_signal_count ??
                      c.price_positive_count ??
                      0,
                  )
            }
            max={
              state.phase === "build"
                ? thresholds.minTrials
                : thresholds.minPricePositive
            }
          />
        </div>
      ) : null}

      {evaluation.blockers.length ? (
        <ul className="mt-5 grid gap-1.5 text-sm text-foreground/85">
          {evaluation.blockers.map((blocker) => (
            <li key={blocker} className="border-l-2 border-kill/70 pl-3">
              {blocker}
            </li>
          ))}
        </ul>
      ) : null}

      {evaluation.passedGates.length ? (
        <ul className="mt-4 grid gap-1 text-sm text-muted">
          {evaluation.passedGates.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      ) : null}

      {evaluation.scaleReady ? (
        <p className="mt-4 font-mono text-xs uppercase tracking-[0.14em] text-go">
          Scale signal · verified payments met
        </p>
      ) : null}
    </section>
  );
}

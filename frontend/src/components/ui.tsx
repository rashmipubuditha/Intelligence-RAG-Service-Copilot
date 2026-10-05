/**
 * UI primitives.
 *
 * Hand-rolled rather than pulling in shadcn/ui + Radix. The component set this app needs is
 * small (button, card, badge, pill, skeleton, dialog, tabs), and the one genuinely hard
 * primitive — a modal with focus trapping and Escape handling — is solved by the native
 * `<dialog>` element, which gets that behaviour from the platform rather than from 40 KB of
 * JavaScript. Accessibility is therefore standards-based: real `<button>`s, real
 * `aria-*`/`role` attributes, and visible focus rings from the global stylesheet.
 */

import {
  forwardRef,
  useEffect,
  useRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { AlertTriangle, Check, Info, Loader2, X } from "lucide-react";
import { cn } from "../lib/format";

// --- Button -----------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

const buttonVariants: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white hover:bg-accent-hover disabled:bg-ink-3 disabled:text-surface shadow-sm",
  secondary:
    "bg-surface text-ink border border-border-strong hover:bg-surface-2 disabled:text-ink-3",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink disabled:text-ink-3",
  danger: "bg-danger text-white hover:brightness-110 disabled:bg-ink-3",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors",
        "disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-4 text-sm",
        buttonVariants[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

// --- Card -------------------------------------------------------------------

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-card border border-border bg-surface", className)}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
      <div className="min-w-0">
        <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] text-ink-3">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

// --- Badge ------------------------------------------------------------------

type Tone = "neutral" | "accent" | "ok" | "warn" | "caution" | "danger";

const toneStyles: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2 border-border",
  accent: "bg-accent-soft text-accent border-accent/25",
  ok: "bg-ok-soft text-ok border-ok/25",
  warn: "bg-warn-soft text-warn border-warn/30",
  caution: "bg-caution-soft text-caution border-caution/30",
  danger: "bg-danger-soft text-danger border-danger/25",
};

export function Badge({
  tone = "neutral",
  icon,
  className,
  children,
}: {
  tone?: Tone;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        toneStyles[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

// --- Skeleton ---------------------------------------------------------------

/** Skeletons, never a spinner on a blank page: the layout should not jump when data lands. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4 w-full", className)} aria-hidden />;
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} className={index === lines - 1 ? "w-2/3" : "w-full"} />
      ))}
    </div>
  );
}

// --- States -----------------------------------------------------------------

/** An empty state always names the action that resolves it. */
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {icon && <div className="text-ink-3">{icon}</div>}
      <div>
        <p className="text-sm font-medium text-ink">{title}</p>
        {description && <p className="mx-auto mt-1 max-w-md text-[13px] text-ink-3">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/**
 * An error state shows the cause, the backend's request id, and a retry.
 * The request id is the whole point: it turns "it broke" into one grep.
 */
export function ErrorState({
  title = "Something went wrong",
  message,
  code,
  requestId,
  onRetry,
}: {
  title?: string;
  message: string;
  code?: string;
  requestId?: string | null;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <AlertTriangle className="size-5 text-danger" aria-hidden />
      <div>
        <p className="text-sm font-medium text-ink">{title}</p>
        <p className="mx-auto mt-1 max-w-md text-[13px] text-ink-2">{message}</p>
        {(code || requestId) && (
          <p className="mt-2 font-mono text-[11px] text-ink-3">
            {code}
            {code && requestId ? " · " : ""}
            {requestId && `request ${requestId}`}
          </p>
        )}
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

// --- Dialog -----------------------------------------------------------------

/**
 * Modal built on the native `<dialog>` element, which supplies focus trapping, Escape
 * dismissal, inert background and the top layer for free.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      aria-labelledby="dialog-title"
      className={cn(
        "w-[min(32rem,calc(100vw-2rem))] rounded-card border border-border bg-surface p-0 text-ink",
        "backdrop:bg-black/40 backdrop:backdrop-blur-sm",
      )}
    >
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div>
          <h2 id="dialog-title" className="text-sm font-semibold">
            {title}
          </h2>
          {description && <p className="mt-1 text-[13px] text-ink-2">{description}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
          className="rounded p-1 text-ink-3 hover:bg-surface-2 hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {children && <div className="px-5 py-4 text-[13px] text-ink-2">{children}</div>}
      {footer && (
        <div className="flex justify-end gap-2 border-t border-border bg-surface-2 px-5 py-3">
          {footer}
        </div>
      )}
    </dialog>
  );
}

// --- Tabs -------------------------------------------------------------------

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: ReadonlyArray<{ id: T; label: string; count?: number }>;
  active: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-border">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          type="button"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium transition-colors",
            active === tab.id
              ? "border-accent text-ink"
              : "border-transparent text-ink-3 hover:text-ink-2",
          )}
        >
          {tab.label}
          {tab.count !== undefined && (
            <span className="ml-1.5 tnum text-ink-3">{tab.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

// --- Field helpers ----------------------------------------------------------

export function Field({
  label,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-ink " +
  "placeholder:text-ink-3 focus:border-accent focus:outline-none";

// --- Inline notice ----------------------------------------------------------

export function Notice({
  tone = "neutral",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  const icons: Partial<Record<Tone, ReactNode>> = {
    ok: <Check className="size-4 shrink-0" aria-hidden />,
    warn: <AlertTriangle className="size-4 shrink-0" aria-hidden />,
    caution: <AlertTriangle className="size-4 shrink-0" aria-hidden />,
    danger: <AlertTriangle className="size-4 shrink-0" aria-hidden />,
    neutral: <Info className="size-4 shrink-0" aria-hidden />,
    accent: <Info className="size-4 shrink-0" aria-hidden />,
  };
  return (
    <div
      className={cn("flex gap-2.5 rounded-lg border px-3.5 py-3 text-[13px]", toneStyles[tone])}
    >
      {icons[tone]}
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        <div className={title ? "mt-0.5" : undefined}>{children}</div>
      </div>
    </div>
  );
}

import type { ComponentProps } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-sm px-4 text-sm font-medium transition-[transform,opacity,background-color,color] duration-150 ease-[var(--ease-out-smooth)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 disabled:pointer-events-none disabled:opacity-40 min-h-11",
  {
    variants: {
      variant: {
        default: "bg-accent text-accent-foreground hover:opacity-90 active:scale-[0.98]",
        secondary:
          "border border-border-strong bg-card text-foreground hover:bg-card-2",
        ghost: "text-muted hover:text-foreground hover:bg-card",
        kill: "bg-kill text-kill-foreground hover:opacity-90",
        go: "bg-go text-go-foreground hover:opacity-90",
      },
      size: {
        default: "h-11",
        sm: "h-9 min-h-9 px-3 text-xs",
        lg: "h-12 px-5",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  type = "button",
  ...props
}: ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return (
    <button
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

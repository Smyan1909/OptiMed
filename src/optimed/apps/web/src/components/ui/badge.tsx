import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-blue-600 text-white hover:bg-blue-700 shadow-md",
        secondary: "border-transparent bg-gray-600 text-white hover:bg-gray-700 shadow-md",
        destructive: "border-transparent bg-red-600 text-white hover:bg-red-700 shadow-md",
        outline: "text-gray-900 border-2 border-gray-400 bg-white hover:bg-gray-50 font-semibold",
        success: "border-transparent bg-green-600 text-white hover:bg-green-700 shadow-md",
        warning: "border-transparent bg-yellow-600 text-white hover:bg-yellow-700 shadow-md",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
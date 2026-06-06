/* Shared, restrained motion presets. Spread onto a framer-motion element.
   prefers-reduced-motion is honored globally via <MotionConfig reducedMotion="user"> in App. */
export const hoverLift = {
  whileHover: { y: -2 },
  whileTap: { scale: 0.97 },
  transition: { type: "spring", stiffness: 400, damping: 30 },
} as const;

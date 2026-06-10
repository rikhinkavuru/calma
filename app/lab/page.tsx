import type { Metadata } from "next";
import LabClient from "@/components/LabClient";

export const metadata: Metadata = {
  title: "The Calma Lab — verification for capital allocation",
  description:
    "A verification lab for capital allocation in the age of AI-produced research: Calma " +
    "independently re-executes the work and recomputes the result, deterministically, for the " +
    "people whose money is at stake.",
};

export default function LabPage() {
  return <LabClient />;
}

import type { Metadata } from "next";
import { ActionsScreen } from "@/components/screens/actions";

export const metadata: Metadata = { title: "Tasks & drafts" };

export default function Page() {
  return <ActionsScreen />;
}

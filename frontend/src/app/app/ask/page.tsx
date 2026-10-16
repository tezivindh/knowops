import type { Metadata } from "next";
import { Suspense } from "react";
import { AskScreen } from "@/components/screens/ask";
import { Loading } from "@/components/ui/spinner";

export const metadata: Metadata = { title: "Ask" };

export default function Page() {
  // AskScreen reads ?c= (the open conversation) from the URL.
  return (
    <Suspense fallback={<Loading />}>
      <AskScreen />
    </Suspense>
  );
}

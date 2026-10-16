import type { Metadata } from "next";
import { AuthForm } from "@/components/marketing/auth-form";

export const metadata: Metadata = { title: "Sign in" };

export default function Page() {
  return <AuthForm mode="login" />;
}

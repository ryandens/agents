"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import GoogleAuth from "../components/google-auth";

export default function LoginPage() {
  const router = useRouter();

  const handleAuthenticated = useCallback(() => {
    router.push("/");
  }, [router]);

  return (
    <div className="flex h-full items-center justify-center p-6 bg-stone-50 dark:bg-stone-950">
      <GoogleAuth onAuthenticated={handleAuthenticated} />
    </div>
  );
}

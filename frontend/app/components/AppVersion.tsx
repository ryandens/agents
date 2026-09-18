'use client';

import { useEffect, useState } from 'react';

export default function AppVersion() {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/version', { cache: 'no-store', signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!controller.signal.aborted && typeof data?.version === 'string' && data.version) {
          setVersion(data.version);
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  if (!version) return null;

  return (
    <footer className="shrink-0 px-4 py-2 text-right text-xs text-stone-500 dark:text-stone-400">
      Version {version}
    </footer>
  );
}

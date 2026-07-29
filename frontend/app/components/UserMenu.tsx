'use client';

import { useAuth } from './AuthProvider';

export default function UserMenu() {
  const { user, signOut } = useAuth();

  return (
    <div className="ml-auto flex items-center gap-3">
      <span
        className="text-xs text-stone-500 dark:text-stone-400 hidden sm:inline"
        title={user.email}
      >
        {user.email}
      </span>
      <button
        onClick={() => void signOut()}
        className="px-2.5 py-1 text-xs font-medium rounded-lg text-stone-600 dark:text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors"
      >
        Sign out
      </button>
    </div>
  );
}

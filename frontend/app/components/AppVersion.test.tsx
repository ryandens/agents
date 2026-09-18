import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import AppVersion from './AppVersion';
import { AuthProvider } from './AuthProvider';

afterEach(() => vi.unstubAllGlobals());

it('shows the API version after sign-in', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ sub: 'user' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ version: '0.7.0' }) });
  vi.stubGlobal('fetch', fetchMock);
  render(<AuthProvider><AppVersion /></AuthProvider>);
  expect(await screen.findByText('Version 0.7.0')).toBeInTheDocument();
  expect(fetchMock).toHaveBeenLastCalledWith('/api/version', expect.objectContaining({ cache: 'no-store' }));
});

it('does not fetch or display a version before sign-in', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: false });
  vi.stubGlobal('fetch', fetchMock);
  render(<AuthProvider><AppVersion /></AuthProvider>);
  await screen.findByText('Sign in to continue');
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
});

it.each([
  { ok: false },
  { ok: true, json: async () => ({ version: 123 }) },
])('omits the version when the endpoint cannot supply it', async (response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  render(<AppVersion />);
  await waitFor(() => expect(fetchMock).toHaveResolved());
  expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
});

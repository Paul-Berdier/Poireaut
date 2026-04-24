/**
 * Tiny hash-based router.
 *
 * Avoids adding react-router just to switch between /dashboard and
 * /investigations/:id. Uses the URL hash so it also works on Railway's
 * static hosting without needing SPA rewrite rules.
 *
 * Routes:
 *   #/                          → landing
 *   #/login                     → auth
 *   #/dashboard                 → dashboard
 *   #/investigations/{uuid}     → investigation canvas
 */
import { useEffect, useState } from 'react';

export type Route =
  | { name: 'landing' }
  | { name: 'login' }
  | { name: 'dashboard' }
  | { name: 'investigation'; id: string }
  | { name: 'admin' };

function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, '');
  if (h === '' || h === '/') return { name: 'landing' };
  if (h === 'login') return { name: 'login' };
  if (h === 'dashboard') return { name: 'dashboard' };
  if (h === 'admin') return { name: 'admin' };
  const m = h.match(/^investigations\/([0-9a-f-]+)$/i);
  if (m) return { name: 'investigation', id: m[1] };
  return { name: 'landing' };
}

export function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  const navigate = (r: Route) => {
    const hash = toHash(r);
    if (window.location.hash !== hash) window.location.hash = hash;
    else setRoute(r);
  };

  return [route, navigate];
}

export function toHash(r: Route): string {
  switch (r.name) {
    case 'landing': return '#/';
    case 'login': return '#/login';
    case 'dashboard': return '#/dashboard';
    case 'admin': return '#/admin';
    case 'investigation': return `#/investigations/${r.id}`;
  }
}

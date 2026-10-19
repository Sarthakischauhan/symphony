// Node 25+ ships a global localStorage that shadows jsdom's (and is undefined
// without --localstorage-file). Point the globals back at the jsdom window.
const dom = (globalThis as any).jsdom?.window;
if (dom)
  for (const key of ["localStorage", "sessionStorage"] as const)
    Object.defineProperty(globalThis, key, {
      configurable: true,
      value: dom[key],
    });
// shadcn's useIsMobile reads matchMedia, which jsdom does not implement.
if (typeof window !== "undefined" && !window.matchMedia)
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      addEventListener() {},
      removeEventListener() {},
    }) as unknown as MediaQueryList;

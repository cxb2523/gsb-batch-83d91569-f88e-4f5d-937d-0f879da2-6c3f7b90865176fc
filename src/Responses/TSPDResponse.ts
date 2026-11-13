export type TSPDResponse = {
  Domains: Record<
    string,
    {
      Cookies: Record<string, string>;
    }
  >;
};

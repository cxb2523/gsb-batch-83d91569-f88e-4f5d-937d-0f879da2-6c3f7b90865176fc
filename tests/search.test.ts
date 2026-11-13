import Olostep from '../src/index.js';

describe('Olostep SDK - Search Operations', () => {
  let client: Olostep;

  beforeAll(() => {
    if (!process.env.OLOSTEP_API_KEY) {
      throw new Error('OLOSTEP_API_KEY environment variable is required for tests');
    }
    client = new Olostep();
  });

  describe('Search - Create', () => {
    test('should create a search from a plain string query', async () => {
      const search = await client.searches.create('Best Answer Engine Optimization startups');

      expect(search).toBeDefined();
      expect(search.id).toBeDefined();
      expect(search.query).toBe('Best Answer Engine Optimization startups');
      expect(search.object).toBe('search');
      expect(search.created).toEqual(expect.any(Number));
      expect(Array.isArray(search.links)).toBe(true);
      expect(search.links.length).toBeGreaterThan(0);
      expect(search.credits_consumed).toEqual(expect.any(Number));

      const first = search.links[0];
      expect(first.url).toEqual(expect.any(String));
      expect(first.title).toEqual(expect.any(String));
      expect(first.description).toEqual(expect.any(String));
    }, 60000);

    test('should respect the limit parameter', async () => {
      const search = await client.searches.create({
        query: "What's going on with OpenAI's Sora shutting down?",
        limit: 5
      });

      expect(search.links.length).toBeLessThanOrEqual(5);
    }, 60000);

    test('should restrict results via includeDomains', async () => {
      const search = await client.searches.create({
        query: 'OpenAI Sora shutdown analysis',
        limit: 5,
        includeDomains: ['bbc.com']
      });

      expect(search.links.length).toBeGreaterThan(0);
      for (const link of search.links) {
        expect(link.url).toMatch(/(^https?:\/\/)([^/]*\.)?bbc\.com(\/|$)/);
      }
    }, 60000);

    test('should exclude results via excludeDomains', async () => {
      const search = await client.searches.create({
        query: 'OpenAI Sora shutdown',
        limit: 10,
        excludeDomains: ['pinterest.com']
      });

      for (const link of search.links) {
        expect(link.url).not.toMatch(/pinterest\.com/);
      }
    }, 60000);

    test('should embed scraped markdown when scrapeOptions provided (camelCase)', async () => {
      const search = await client.searches.create({
        query: 'OpenAI Sora shutdown',
        limit: 5,
        scrapeOptions: {
          formats: ['markdown'],
          timeout: 25
        }
      });

      expect(search.links.length).toBeGreaterThan(0);
      const withContent = search.links.filter((l) => typeof l.markdown_content === 'string' && l.markdown_content.length > 0);
      expect(withContent.length).toBeGreaterThan(0);
    }, 90000);

    test('should accept snake_case scrape_options', async () => {
      const search = await client.searches.create({
        query: 'OpenAI Sora shutdown',
        limit: 5,
        scrape_options: {
          formats: ['markdown'],
          timeout: 25
        }
      });

      expect(search.links.length).toBeGreaterThan(0);
      const withContent = search.links.filter((l) => typeof l.markdown_content === 'string' && l.markdown_content.length > 0);
      expect(withContent.length).toBeGreaterThan(0);
    }, 90000);

    test('should return both markdown and html when both formats requested', async () => {
      const search = await client.searches.create({
        query: 'OpenAI Sora shutdown',
        limit: 3,
        scrapeOptions: {
          formats: ['html', 'markdown'],
          timeout: 25
        }
      });

      const linkWithBoth = search.links.find(
        (l) =>
          typeof l.markdown_content === 'string' &&
          l.markdown_content.length > 0 &&
          typeof l.html_content === 'string' &&
          l.html_content.length > 0
      );
      expect(linkWithBoth).toBeDefined();
    }, 90000);
  });

  describe('Search - Get by ID', () => {
    test('should retrieve a previously created search by ID', async () => {
      const created = await client.searches.create({
        query: 'AI agent frameworks',
        limit: 3
      });

      const fetched = await client.searches.get(created.id);

      expect(fetched.id).toBe(created.id);
      expect(fetched.query).toBe(created.query);
      expect(fetched.object).toBe('search');
      expect(Array.isArray(fetched.links)).toBe(true);
      expect(fetched.links.length).toBe(created.links.length);
    }, 60000);
  });

  describe('Search - Shorthand & helper', () => {
    test('callable shorthand client.searches() works', async () => {
      const search = await client.searches('AI agent frameworks');
      expect(search.id).toBeDefined();
      expect(search.links.length).toBeGreaterThan(0);
    }, 60000);

    test('client.search() convenience method works', async () => {
      const search = await client.search('AI agent frameworks');
      expect(search.id).toBeDefined();
      expect(search.links.length).toBeGreaterThan(0);
    }, 60000);
  });
});

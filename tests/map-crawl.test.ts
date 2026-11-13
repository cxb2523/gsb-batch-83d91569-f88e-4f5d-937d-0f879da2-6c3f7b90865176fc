import Olostep from '../src/index.js';

describe('Olostep SDK - Map & Crawl Operations', () => {
  let client: Olostep;

  beforeAll(() => {
    if (!process.env.OLOSTEP_API_KEY) {
      throw new Error('OLOSTEP_API_KEY environment variable is required for tests');
    }
    client = new Olostep();
  });

  describe('Map Operations - camelCase', () => {
    test('should create map with camelCase params', async () => {
      const map = await client.maps({
        url: 'https://example.com',
        topN: 10
      });
      
      expect(map).toBeDefined();
      expect(map.id).toMatch(/^map_/);
    }, 120000);

    test('should stream URLs using map.urls()', async () => {
      const map = await client.maps('https://example.com');
      
      const urls: string[] = [];
      for await (const url of map.urls()) {
        urls.push(url);
      }
      
      expect(urls.length).toBeGreaterThan(0);
      expect(urls[0]).toContain('example.com');
    }, 120000);

    test('should use client.maps.create() explicit syntax', async () => {
      const map = await client.maps.create('https://example.com');
      
      expect(map).toBeDefined();
      expect(map.id).toMatch(/^map_/);
    }, 120000);
  });

  describe('Map Operations - snake_case', () => {
    test('should create map with snake_case params', async () => {
      const map = await client.maps({
        url: 'https://example.com',
        top_n: 10
      });

      expect(map).toBeDefined();
      expect(map.id).toMatch(/^map_/);
    }, 120000);

    test('should create map with snake_case include/exclude', async () => {
      const map = await client.maps({
        url: 'https://example.com',
        top_n: 5,
        include_subdomain: false
      });

      expect(map).toBeDefined();
      expect(map.id).toMatch(/^map_/);
    }, 120000);

    test('should use client.maps.create() with snake_case', async () => {
      const map = await client.maps.create({
        url: 'https://example.com',
        top_n: 10
      });

      expect(map).toBeDefined();
      expect(map.id).toMatch(/^map_/);
    }, 120000);
  });

  describe('Crawl Operations - camelCase', () => {
    test('should create crawl with camelCase params', async () => {
      const crawl = await client.crawls({
        url: 'https://example.com',
        maxPages: 3,
        maxDepth: 1
      });
      
      expect(crawl).toBeDefined();
      expect(crawl.id).toMatch(/^crawl_/);
      expect(crawl.start_url).toBe('https://example.com');
      expect(crawl.max_pages).toBe(3);
      expect(crawl.max_depth).toBe(1);
    }, 30000);

    test('should get crawl info using crawl.info()', async () => {
      const crawl = await client.crawls({
        url: 'https://example.com',
        maxPages: 3,
        maxDepth: 1
      });
      
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      const info = await crawl.info();
      expect(info).toBeDefined();
      expect((info as any).id).toBe(crawl.id);
      expect((info as any).status).toBeDefined();
      expect(['in_progress', 'completed', 'failed']).toContain((info as any).status);
    }, 35000);

    test('should use client.crawls.create() explicit syntax', async () => {
      const crawl = await client.crawls.create({
        url: 'https://example.com',
        maxPages: 3,
        maxDepth: 1
      });
      
      expect(crawl).toBeDefined();
      expect(crawl.id).toMatch(/^crawl_/);
    }, 35000);

    test('should use client.crawls.info() to get crawl info by ID', async () => {
      const crawl = await client.crawls({
        url: 'https://example.com',
        maxPages: 3,
        maxDepth: 1
      });
      
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      const info = await client.crawls.info(crawl.id);
      expect(info).toBeDefined();
      expect((info as any).id).toBe(crawl.id);
    }, 35000);

    test('should wait for crawl completion with camelCase waitTillDone', async () => {
      const crawl = await client.crawls({
        url: 'https://example.com',
        maxPages: 3,
        maxDepth: 1
      });
      
      await expect(
        crawl.waitTillDone({checkEveryNSecs: 2, timeoutSeconds: 60})
      ).resolves.not.toThrow();
      
      const info = await crawl.info();
      expect((info as any).status).toBe('completed');
    }, 70000);
  });

  describe('Crawl Operations - snake_case', () => {
    test('should create crawl with snake_case params', async () => {
      const crawl = await client.crawls({
        url: 'https://example.com',
        max_pages: 3,
        max_depth: 1
      });

      expect(crawl).toBeDefined();
      expect(crawl.id).toMatch(/^crawl_/);
      expect(crawl.start_url).toBe('https://example.com');
      expect(crawl.max_pages).toBe(3);
      expect(crawl.max_depth).toBe(1);
    }, 30000);

    test('should create crawl with snake_case start_url', async () => {
      const crawl = await client.crawls({
        start_url: 'https://example.com',
        max_pages: 3,
        max_depth: 1
      });

      expect(crawl).toBeDefined();
      expect(crawl.id).toMatch(/^crawl_/);
      expect(crawl.start_url).toBe('https://example.com');
    }, 30000);

    test('should use client.crawls.create() with snake_case', async () => {
      const crawl = await client.crawls.create({
        url: 'https://example.com',
        max_pages: 3,
        max_depth: 1
      });

      expect(crawl).toBeDefined();
      expect(crawl.id).toMatch(/^crawl_/);
    }, 35000);

    test('should use client.crawls.info() with snake_case crawl', async () => {
      const crawl = await client.crawls({
        url: 'https://example.com',
        max_pages: 3,
        max_depth: 1
      });

      await new Promise(resolve => setTimeout(resolve, 2000));

      const info = await client.crawls.info(crawl.id);
      expect(info).toBeDefined();
      expect((info as any).id).toBe(crawl.id);
    }, 35000);

    test('should wait for crawl completion with snake_case waitTillDone', async () => {
      const crawl = await client.crawls({
        url: 'https://example.com',
        max_pages: 3,
        max_depth: 1
      });

      await expect(
        crawl.waitTillDone({check_every_n_secs: 2, timeout_seconds: 60})
      ).resolves.not.toThrow();

      const info = await crawl.info();
      expect((info as any).status).toBe('completed');
    }, 70000);
  });
});

import Olostep from '../src/index.js';

describe('Olostep SDK - Answers Operations', () => {
  let client: Olostep;

  beforeAll(() => {
    if (!process.env.OLOSTEP_API_KEY) {
      throw new Error('OLOSTEP_API_KEY environment variable is required for tests');
    }
    client = new Olostep();
  });

  describe('Answers - Create', () => {
    test('should create an answer from a plain string task', async () => {
      const answer = await client.answers.create(
        'What is the main topic of https://olostep.com?'
      );

      expect(answer).toBeDefined();
      expect(answer.id).toBeDefined();
      expect(answer.task).toBe('What is the main topic of https://olostep.com?');
      expect(answer.object).toBe('answer');
      expect(answer.created).toEqual(expect.any(Number));
      expect(answer.answer).toBeDefined();
      expect(Array.isArray(answer.sources)).toBe(true);
    }, 60000);

    test('should create an answer with json_format (snake_case)', async () => {
      const answer = await client.answers.create({
        task: 'List the headings on https://olostep.com',
        json_format: {
          headings: [{title: ''}]
        }
      });

      expect(answer).toBeDefined();
      expect(answer.id).toBeDefined();
      expect(answer.json_content).toBeDefined();
      expect(answer.json_hosted_url).toBeDefined();
    }, 60000);

    test('should create an answer with jsonFormat (camelCase)', async () => {
      const answer = await client.answers.create({
        task: 'List the headings on https://olostep.com',
        jsonFormat: {
          headings: [{title: ''}]
        }
      });

      expect(answer).toBeDefined();
      expect(answer.id).toBeDefined();
      expect(answer.json_content).toBeDefined();
    }, 60000);
  });

  describe('Answers - Get by ID', () => {
    test('should retrieve a previously created answer by ID', async () => {
      const created = await client.answers.create(
        'What is the main topic of https://olostep.com?'
      );

      const fetched = await client.answers.get(created.id);

      expect(fetched.id).toBe(created.id);
      expect(fetched.task).toBe(created.task);
      expect(fetched.object).toBe('answer');
      expect(fetched.answer).toBeDefined();
    }, 60000);
  });
});

import { z } from 'zod';

export const LockSecsSchema = z.coerce.number().int().positive().max(86400).default(60);

export const CreateQueueSchema = z.object({
  name: z
    .string()
    .min(1)
    .max(100)
    .regex(
      /^[a-zA-Z0-9._-]+$/,
      'Name must contain only letters, numbers, dots, dashes, and underscores'
    )
    .optional(),
});

export const AddRequestSchema = z.object({
  url: z.string().url().max(2048),
  uniqueKey: z.string().max(2048).optional(),
  method: z.enum(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']).default('GET'),
  payload: z.string().max(1_000_000).optional(),
  headers: z.record(z.string()).optional(),
  userData: z.record(z.unknown()).optional(),
  noRetry: z.boolean().default(false),
});

export const BatchAddRequestSchema = z.array(AddRequestSchema).max(1000);

export const UpdateRequestSchema = z.object({
  handledAt: z.string().datetime().nullable().optional(),
  retryCount: z.number().int().min(0).optional(),
  errorMessages: z.array(z.string()).optional(),
  userData: z.record(z.unknown()).optional(),
});

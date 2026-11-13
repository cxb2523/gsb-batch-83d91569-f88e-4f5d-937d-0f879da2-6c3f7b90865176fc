import { z } from 'zod';

export const CreateDatasetSchema = z.object({
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

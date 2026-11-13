import { RequestErrorKind } from '../utils/utils';

export type ScanStage = 'posts' | 'likers' | 'following' | 'followers';

// Why the scan stopped. Cursor/pagination faults use their own kind so the
// UI can name the concrete failure category; 'unknown' covers non-RequestError
// failures.
export type StopReason = RequestErrorKind | 'cursor' | 'unknown';

export interface ScanStopConclusion {
    readonly stage: ScanStage;
    readonly reason: StopReason;
    // Present only while collecting likers; 1-based index of the post whose
    // liker request (or validation) ended the run.
    readonly likerPostIndex: number | null;
    readonly errorMessage: string;
    // Unique identities collected before the stop. Partial counts are
    // diagnostic only; they are never turned into a leaderboard or cached.
    readonly uniquePostCount: number;
    readonly uniqueLikerCount: number;
    readonly followingCount: number;
    readonly followerCount: number;
    // Present for rate-limit stops; the earliest time a retry is sensible.
    readonly retryAt: number | null;
}

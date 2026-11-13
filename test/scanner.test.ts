import assert from 'node:assert/strict';
import test from 'node:test';
import { REQUEST_POLICY, RequestPolicy } from '../src/constants/constants';
import { PostNode } from '../src/model/post';
import { ScanOutcome, fetchAllLikers, fetchAllPosts, fetchFollowing, runScan } from '../src/utils/scanner';
import { IgRequester, PostsQuery, RequestError } from '../src/utils/utils';

function expectStopped(outcome: ScanOutcome): Extract<ScanOutcome, { status: 'stopped' }> {
    assert.equal(outcome.status, 'stopped');
    return outcome;
}

function expectComplete(outcome: ScanOutcome): Extract<ScanOutcome, { status: 'complete' }> {
    assert.equal(outcome.status, 'complete');
    return outcome;
}

function fakeRequester(
    responses: unknown[],
    policy: Partial<RequestPolicy> = {},
): IgRequester {
    let requestCount = 0;
    return {
        ownerId: 'owner',
        policy: { ...REQUEST_POLICY, ...policy },
        get requestCount() {
            return requestCount;
        },
        async request<T>() {
            requestCount++;
            const response = responses.shift();
            if (response instanceof Error) {
                throw response;
            }
            return response as T;
        },
    };
}

const rawPost = (id: string, ownerId = 'owner') => ({
    pk: id,
    like_count: Number(id) || 1,
    caption: null,
    user: { pk: ownerId },
});

const postsQuery: PostsQuery = { username: 'owner', docId: '1', lsd: 'lsd', fbDtsg: 'dtsg' };

const postPage = (items: unknown[], endCursor: string | null = null) => ({
    data: {
        xdt_api__v1__feed__user_timeline_graphql_connection: {
            edges: items.map(node => ({ node })),
            page_info: { has_next_page: endCursor !== null, end_cursor: endCursor },
        },
    },
});

const post = (id: string): PostNode => ({
    id,
    edge_media_preview_like: { count: 1 },
    edge_media_to_caption: { edges: [] },
});

const rawUser = (id: string) => ({
    pk: id,
    username: `user${id}`,
    full_name: `User ${id}`,
    profile_pic_url: '',
    is_verified: false,
});

test('post scanner deduplicates IDs and returns a bounded recent scope', async () => {
    const requester = fakeRequester([
        postPage([rawPost('1'), rawPost('1'), rawPost('2'), rawPost('3')]),
    ], { maxPosts: 2 });

    const result = await fetchAllPosts(requester, postsQuery, () => undefined);
    assert.deepEqual(result.posts.map(item => item.id), ['1', '2']);
    assert.equal(result.postScope, 'recent_limit');
});

test('post scanner rejects a repeated cursor before completion', async () => {
    const requester = fakeRequester([
        postPage([rawPost('1')], 'same'),
        postPage([rawPost('2')], 'same'),
    ]);

    await assert.rejects(fetchAllPosts(requester, postsQuery, () => undefined), error =>
        error instanceof RequestError && error.kind === 'cursor');
});

test('post scanner rejects a profile that is not the signed-in account', async () => {
    const requester = fakeRequester([postPage([rawPost('1', 'someone-else')])]);

    await assert.rejects(fetchAllPosts(requester, postsQuery, () => undefined), error =>
        error instanceof RequestError && error.kind === 'invalid_response');
});

test('scanner rejects missing usernames and invalid like counts', async () => {
    for (const likeCount of [undefined, -1, Number.NaN]) {
        const requester = fakeRequester([postPage([{ ...rawPost('1'), like_count: likeCount }])]);
        await assert.rejects(fetchAllPosts(requester, postsQuery, () => undefined), error =>
            error instanceof RequestError && error.kind === 'invalid_response');
    }

    const requester = fakeRequester([{
        users: [{ ...rawUser('1'), username: '' }],
    }]);
    await assert.rejects(fetchAllLikers([post('1')], requester, () => undefined), error =>
        error instanceof RequestError && error.kind === 'invalid_response');
});

test('liker scanner counts each identity at most once per post', async () => {
    const requester = fakeRequester([
        { users: [rawUser('1'), rawUser('1'), rawUser('2')] },
        { users: [rawUser('1')] },
    ]);
    const identifiedCounts: number[] = [];

    const likerMap = await fetchAllLikers(
        [post('1'), post('2')],
        requester,
        (_index, identifiedLikerCount) => identifiedCounts.push(identifiedLikerCount),
    );
    assert.equal(likerMap['1']?.likesCount, 2);
    assert.equal(likerMap['2']?.likesCount, 1);
    assert.deepEqual(identifiedCounts, [2, 2]);
});

test('liker scanner propagates a required-request failure', async () => {
    const failure = new RequestError('network', 'offline');
    const requester = fakeRequester([{ users: [rawUser('1')] }, failure]);

    await assert.rejects(
        fetchAllLikers([post('1'), post('2')], requester, () => undefined),
        error => error === failure,
    );
});

test('user-list scanner deduplicates users across pages', async () => {
    const requester = fakeRequester([
        { users: [rawUser('1')], next_max_id: 'next' },
        { users: [rawUser('1'), rawUser('2')] },
    ]);

    const result = await fetchFollowing(requester, () => undefined);
    assert.deepEqual([...result.ids], ['1', '2']);
    assert.equal(result.users['1']?.username, 'user1');
});

test('user parser keeps optional privacy and profile photo flags only when present', async () => {
    const requester = fakeRequester([{
        users: [{ ...rawUser('1'), is_private: true, has_anonymous_profile_picture: false }, rawUser('2')],
    }]);

    const result = await fetchFollowing(requester, () => undefined);
    assert.deepEqual(
        [result.users['1']?.is_private, result.users['1']?.has_anonymous_profile_picture],
        [true, false],
    );
    assert.deepEqual(Object.keys(result.users['2'] ?? {}).includes('is_private'), false);
});

// ============================================================
// runScan stop conclusions
// ============================================================

const likerPage = (ids: readonly string[]) => ({ users: ids.map(rawUser) });
const followingPage = (ids: readonly string[]) => ({ users: ids.map(rawUser) });

test('runScan records the posts stage and cursor reason on a repeated post cursor', async () => {
    const requester = fakeRequester([
        postPage([rawPost('1')], 'same'),
        postPage([rawPost('2')], 'same'),
    ]);

    const outcome = expectStopped(await runScan(requester, postsQuery, false));
    assert.equal(outcome.conclusion.stage, 'posts');
    assert.equal(outcome.conclusion.reason, 'cursor');
    // Both pages were ingested and counted before the repeated cursor on the
    // second page was rejected.
    assert.equal(outcome.conclusion.uniquePostCount, 2);
    assert.equal(outcome.conclusion.uniqueLikerCount, 0);
    assert.equal(outcome.conclusion.followingCount, 0);
    assert.equal(outcome.conclusion.followerCount, 0);
    assert.equal(outcome.conclusion.likerPostIndex, null);
    assert.equal(outcome.conclusion.retryAt, null);
    // Two post pages were consumed; no later phase may issue a request.
    assert.equal(requester.requestCount, 2);
});

test('runScan records the posts stage and cursor reason when a next page has no cursor', async () => {
    // An empty end_cursor still reports has_next_page === true.
    const requester = fakeRequester([postPage([rawPost('1')], '')]);

    const outcome = expectStopped(await runScan(requester, postsQuery, false));
    assert.equal(outcome.conclusion.stage, 'posts');
    assert.equal(outcome.conclusion.reason, 'cursor');
    assert.equal(outcome.conclusion.uniquePostCount, 1);
});

test('runScan records the likers stage, post index and identified count on liker failure', async () => {
    const failure = new RequestError('network', 'offline');
    const requester = fakeRequester([
        postPage([rawPost('1'), rawPost('2'), rawPost('3')]),
        likerPage(['1', '2']),
        failure,
    ]);

    const outcome = expectStopped(await runScan(requester, postsQuery, false));
    assert.equal(outcome.conclusion.stage, 'likers');
    assert.equal(outcome.conclusion.likerPostIndex, 2);
    assert.equal(outcome.conclusion.reason, 'network');
    assert.equal(outcome.conclusion.uniquePostCount, 3);
    assert.equal(outcome.conclusion.uniqueLikerCount, 2);
    assert.equal(outcome.conclusion.followingCount, 0);
    // The failing request was the last one; following/followers never run.
    assert.equal(requester.requestCount, 3);
});

test('runScan preserves the rate-limit retry time in the stop conclusion', async () => {
    const rateLimited = new RequestError('rate_limit', 'slow down', { retryAt: 1_800_000 });
    const requester = fakeRequester([
        postPage([rawPost('1')]),
        likerPage(['1']),
        rateLimited,
    ]);

    const outcome = expectStopped(await runScan(requester, postsQuery, false));
    assert.equal(outcome.conclusion.stage, 'following');
    assert.equal(outcome.conclusion.reason, 'rate_limit');
    assert.equal(outcome.conclusion.retryAt, 1_800_000);
    assert.equal(outcome.conclusion.uniquePostCount, 1);
    assert.equal(outcome.conclusion.uniqueLikerCount, 1);
    assert.equal(requester.requestCount, 3);
});

test('runScan distinguishes the followers stage and keeps follower counts', async () => {
    const failure = new RequestError('timeout', 'too slow');
    const requester = fakeRequester([
        postPage([rawPost('1')]),
        likerPage(['1', '2']),
        followingPage(['1', '2', '3']),
        { users: [rawUser('1')], next_max_id: 'next' },
        failure,
    ]);

    const outcome = expectStopped(await runScan(requester, postsQuery, true));
    assert.equal(outcome.conclusion.stage, 'followers');
    assert.equal(outcome.conclusion.reason, 'timeout');
    assert.equal(outcome.conclusion.followingCount, 3);
    assert.equal(outcome.conclusion.followerCount, 1);
});

test('runScan completes without a stop conclusion and returns every phase result', async () => {
    const requester = fakeRequester([
        postPage([rawPost('1'), rawPost('2')]),
        likerPage(['1']),
        likerPage(['1', '2']),
        followingPage(['1']),
        { users: [rawUser('2')] },
    ]);

    const outcome = expectComplete(await runScan(requester, postsQuery, true));
    assert.deepEqual(outcome.scan.posts.map(item => item.id), ['1', '2']);
    assert.equal(outcome.scan.postScope, 'all_posts');
    assert.equal(Object.keys(outcome.scan.likerMap).length, 2);
    assert.equal(outcome.scan.following.ids.size, 1);
    assert.equal(outcome.scan.followers?.ids.size, 1);
    assert.equal(requester.requestCount, 5);
});

test('runScan skips the followers phase when follower analysis is disabled', async () => {
    const requester = fakeRequester([
        postPage([rawPost('1')]),
        likerPage(['1']),
        followingPage(['1']),
    ]);

    const outcome = expectComplete(await runScan(requester, postsQuery, false));
    assert.equal(outcome.scan.followers, null);
    assert.equal(requester.requestCount, 3);
});

test('runScan reports the first-post index when the opening liker request fails', async () => {
    const failure = new RequestError('invalid_response', 'bad liker list');
    const requester = fakeRequester([
        postPage([rawPost('1'), rawPost('2')]),
        failure,
    ]);

    const outcome = expectStopped(await runScan(requester, postsQuery, false));
    assert.equal(outcome.conclusion.stage, 'likers');
    assert.equal(outcome.conclusion.likerPostIndex, 1);
    assert.equal(outcome.conclusion.uniqueLikerCount, 0);
});
